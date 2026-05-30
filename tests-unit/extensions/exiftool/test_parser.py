import time

import pytest
from extensions.exiftool.parser import flatten, _parse_json_output


class _Pipe:
    def __init__(self, fail_write=False):
        self.fail_write = fail_write
        self.closed = False

    def write(self, _value):
        if self.fail_write:
            raise OSError("pipe closed")

    def flush(self):
        pass

    def close(self):
        self.closed = True


class _FailClosePipe(_Pipe):
    def close(self):
        raise OSError("close failed")


class _SlowStdout(_Pipe):
    def readline(self):
        time.sleep(0.05)
        return ""


class _OkStdin(_Pipe):
    def write(self, _value):
        return None


class _Proc:
    pid = 12345

    def __init__(self):
        self.stdin = _Pipe(fail_write=True)
        self.stdout = _Pipe()

    def wait(self, timeout=None):
        return 0


def test_exiftool_process_stop_fallback_terminates_tree(monkeypatch):
    from extensions.exiftool.parser import ExifToolProcess
    from extensions.exiftool import parser as parser_module

    calls = []
    proc = _Proc()
    tool = ExifToolProcess("exiftool.exe")
    tool._proc = proc

    monkeypatch.setattr(parser_module.psutil, "Process", lambda pid: f"ps-{pid}")
    monkeypatch.setattr(parser_module.AppProcess, "terminate_tree", lambda processes, timeout=1, kill_timeout=2: calls.append((processes, timeout, kill_timeout)))

    tool.stop()

    assert calls == [(["ps-12345"], 1, 2)]
    assert proc.stdin.closed is True
    assert proc.stdout.closed is True


def test_exiftool_process_close_pipes_logs_failure(monkeypatch):
    from extensions.exiftool import parser as parser_module

    messages = []
    proc = _Proc()
    proc.stdin = _FailClosePipe()
    proc.stdout = _FailClosePipe()
    monkeypatch.setattr(parser_module, "debug_non_recursive", lambda text: messages.append(text))

    parser_module.ExifToolProcess._close_pipes(proc)

    assert len(messages) == 2
    assert all("Pipe close failed" in msg for msg in messages)


def test_exiftool_process_query_timeout_kills_process(monkeypatch):
    from extensions.exiftool import parser as parser_module
    from extensions.exiftool.parser import ExifToolProcess

    warnings = []
    kills = []
    proc = _Proc()
    proc.stdin = _OkStdin()
    proc.stdout = _SlowStdout()
    proc.poll = lambda: None
    tool = ExifToolProcess("exiftool.exe")
    tool._proc = proc

    monkeypatch.setattr(parser_module, "_QUERY_TIMEOUT", 0.001)
    monkeypatch.setattr(parser_module.AppLogger, "warning", lambda text: warnings.append(text))
    monkeypatch.setattr(parser_module.ExifToolProcess, "_terminate_proc_tree", staticmethod(lambda p: kills.append(p)))

    assert tool.query("slow.jpg") is None
    assert warnings and "Query timed out" in warnings[0]
    assert kills == [proc]
    assert tool._proc is None


def test_exiftool_process_finalizer_logs_cleanup_failure(monkeypatch):
    from extensions.exiftool import parser as parser_module
    from extensions.exiftool.parser import ExifToolProcess

    messages = []
    tool = ExifToolProcess("exiftool.exe")
    monkeypatch.setattr(tool, "stop", lambda: (_ for _ in ()).throw(RuntimeError("cleanup failed")))
    monkeypatch.setattr(parser_module, "debug_non_recursive", lambda text: messages.append(text))

    tool.__del__()

    assert messages == ["[exiftool] Process cleanup failed: cleanup failed"]


class TestParseJsonOutput:
    def test_valid_json(self):
        raw = '[{"SourceFile": "test.jpg", "IFD0:Make": "Canon"}]'
        result = _parse_json_output(raw)
        assert result == {"SourceFile": "test.jpg", "IFD0:Make": "Canon"}

    def test_with_surrounding_text(self):
        raw = 'Warning: something\n[{"IFD0:Make": "Canon"}]\n'
        result = _parse_json_output(raw)
        assert result == {"IFD0:Make": "Canon"}

    def test_empty_string(self):
        assert _parse_json_output("") is None

    def test_no_json(self):
        assert _parse_json_output("not json at all") is None

    def test_empty_array(self):
        assert _parse_json_output("[]") is None

    def test_invalid_json(self):
        assert _parse_json_output("[{broken}]") is None


class TestFlatten:
    def test_basic_metadata(self):
        data = {
            "SourceFile": "photo.jpg",
            "ExifTool:ExifToolVersion": 13.25,
            "System:FileName": "photo.jpg",
            "System:FileSize": "2.5 MB",
            "File:FileType": "JPEG",
            "File:ImageWidth": 4000,
            "File:ImageHeight": 3000,
            "IFD0:Make": "Canon",
            "IFD0:Model": "Canon EOS R5",
            "ExifIFD:ExposureTime": "1/200",
        }
        meta, aspect = flatten(data)
        assert "File:FileType" in meta
        assert meta["File:FileType"] == "JPEG"
        assert meta["IFD0:Make"] == "Canon"
        assert meta["ExifIFD:ExposureTime"] == "1/200"
        assert "SourceFile" not in meta
        assert not any(k.startswith("System:") for k in meta)
        assert not any(k.startswith("ExifTool:") for k in meta)
        assert aspect == pytest.approx(4000 / 3000)

    def test_orientation_rotated_90(self):
        data = {
            "File:ImageWidth": 3000,
            "File:ImageHeight": 4000,
            "IFD0:Orientation": "Rotate 90 CW",
        }
        meta, aspect = flatten(data)
        assert aspect == pytest.approx(4000 / 3000)

    def test_orientation_rotated_270(self):
        data = {
            "File:ImageWidth": 3000,
            "File:ImageHeight": 4000,
            "IFD0:Orientation": "Rotate 270 CW",
        }
        meta, aspect = flatten(data)
        assert aspect == pytest.approx(4000 / 3000)

    def test_orientation_normal(self):
        data = {
            "File:ImageWidth": 4000,
            "File:ImageHeight": 3000,
            "IFD0:Orientation": "Horizontal (normal)",
        }
        meta, aspect = flatten(data)
        assert aspect == pytest.approx(4000 / 3000)

    def test_list_values(self):
        data = {
            "IPTC:Keywords": ["landscape", "nature", "sunset"],
        }
        meta, _ = flatten(data)
        assert meta["IPTC:Keywords"] == "landscape, nature, sunset"

    def test_empty_data(self):
        meta, aspect = flatten({})
        assert meta == {}
        assert aspect is None

    def test_exiftool_error_only(self):
        data = {
            "SourceFile": "missing.jpg",
            "ExifTool:Error": "File not found: missing.jpg",
        }
        meta, aspect = flatten(data)
        assert meta == {}
        assert aspect is None

    def test_error_with_partial_data(self):
        data = {
            "SourceFile": "corrupt.jpg",
            "ExifTool:Error": "Some warning",
            "IFD0:Make": "Canon",
        }
        meta, aspect = flatten(data)
        assert meta["IFD0:Make"] == "Canon"

    def test_no_dimensions(self):
        data = {"IFD0:Make": "Canon"}
        meta, aspect = flatten(data)
        assert aspect is None
        assert meta["IFD0:Make"] == "Canon"

    def test_none_values_skipped(self):
        data = {"IFD0:Make": None, "IFD0:Model": "R5"}
        meta, _ = flatten(data)
        assert "IFD0:Make" not in meta
        assert meta["IFD0:Model"] == "R5"

    def test_empty_string_skipped(self):
        data = {"IFD0:Make": "  ", "IFD0:Model": "R5"}
        meta, _ = flatten(data)
        assert "IFD0:Make" not in meta

    def test_exif_image_dimensions(self):
        data = {
            "ExifIFD:ExifImageWidth": 4000,
            "ExifIFD:ExifImageHeight": 3000,
        }
        _, aspect = flatten(data)
        assert aspect == pytest.approx(4000 / 3000)

    def test_file_dimensions_preferred(self):
        data = {
            "File:ImageWidth": 2000,
            "File:ImageHeight": 1000,
            "ExifIFD:ExifImageWidth": 4000,
            "ExifIFD:ExifImageHeight": 3000,
        }
        _, aspect = flatten(data)
        assert aspect == pytest.approx(2000 / 1000)

    def test_numeric_values_as_string(self):
        data = {"ExifIFD:FNumber": 4.0, "ExifIFD:ISO": 100}
        meta, _ = flatten(data)
        assert meta["ExifIFD:FNumber"] == "4.0"
        assert meta["ExifIFD:ISO"] == "100"

    def test_ungrouped_key(self):
        data = {"Orientation": "Rotate 90 CW"}
        meta, _ = flatten(data)
        assert "Orientation" in meta

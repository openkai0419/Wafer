from wafer.core.platform.folders import first_entry, make_directory
from wafer.core.common.virtual_paths import build_virtual_path


def test_first_entry_returns_none_for_missing(tmp_path):
    assert first_entry(str(tmp_path / "missing")) is None


def test_first_entry_returns_file_or_folder(tmp_path):
    sub = tmp_path / "d"
    sub.mkdir()
    a = tmp_path / "a.txt"
    a.write_text("x", encoding="utf-8")
    out = first_entry(str(tmp_path))
    assert out in {str(a), str(sub)}


def test_make_directory_creates_dir(tmp_path):
    target = str(tmp_path / "new_dir")
    result = make_directory(target)
    assert result == target
    assert (tmp_path / "new_dir").is_dir()


def test_make_directory_nested(tmp_path):
    target = str(tmp_path / "a" / "b" / "c")
    result = make_directory(target)
    assert result == target
    assert (tmp_path / "a" / "b" / "c").is_dir()


def test_make_directory_existing_is_ok(tmp_path):
    target = str(tmp_path / "existing")
    (tmp_path / "existing").mkdir()
    result = make_directory(target)
    assert result == target


def test_open_file_calls_desktop_services(monkeypatch):
    from wafer.core.platform import folders
    from PySide6 import QtCore, QtGui

    opened: list[str] = []
    orig_open = QtGui.QDesktopServices.openUrl

    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))
    folders.open_file("/some/path")
    assert len(opened) == 1
    assert opened[0] == "/some/path"


def test_open_file_empty_path_is_noop():
    from wafer.core.platform import folders

    folders.open_file("")


def test_open_file_rejects_virtual_path(monkeypatch, tmp_path):
    from wafer.core.platform import folders
    from PySide6 import QtGui

    opened: list[str] = []
    monkeypatch.setattr(QtGui.QDesktopServices, "openUrl", staticmethod(lambda url: opened.append(url.toLocalFile())))

    folders.open_file(build_virtual_path(str(tmp_path / "archive.zip"), "image.png"))

    assert opened == []


def test_show_in_explorer_rejects_virtual_path(monkeypatch, tmp_path):
    from wafer.core.platform import folders

    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("virtual path reached show path resolution")

    monkeypatch.setattr(folders, "_resolve_show_path", fail_if_called)

    folders.show_in_explorer(build_virtual_path(str(tmp_path / "archive.zip"), "image.png"))


def test_open_with_starts_the_program_with_all_files(tmp_path):
    import sys
    import time
    from wafer.core.platform import folders

    out = tmp_path / "argv.txt"
    script = tmp_path / "record.py"
    script.write_text(f"import sys, pathlib\npathlib.Path({str(out)!r}).write_text('\\n'.join(sys.argv[1:]))\n", encoding="utf-8")
    other = tmp_path / "b.png"

    assert folders.open_with(sys.executable, [str(script), str(other)])

    deadline = time.monotonic() + 15
    while not out.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert out.read_text().splitlines() == [str(other)]


def _recording_batch(tmp_path):
    import sys

    out = tmp_path / "argv.txt"
    recorder = tmp_path / "record.py"
    recorder.write_text(f"import sys, pathlib\npathlib.Path({str(out)!r}).write_text('\\n'.join(sys.argv[1:]), encoding='utf-8')\n", encoding="utf-8")
    batch = tmp_path / "wrapper dir" / "open.bat"
    batch.parent.mkdir()
    batch.write_text(f'@"{sys.executable}" "{recorder}" %*\r\n', encoding="utf-8")
    return batch, out


def _wait_for_file(path):
    import time

    deadline = time.monotonic() + 15
    while not path.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    return path.read_text(encoding="utf-8").splitlines()


def test_open_with_batch_program_passes_names_with_shell_characters_unchanged(tmp_path):
    from wafer.core.platform import folders

    batch, out = _recording_batch(tmp_path)
    tricky = tmp_path / "Tom&Jerry ^(1)&cd&.png"
    plain = tmp_path / "b.png"

    assert folders.open_with(str(batch), [str(tricky), plain.as_posix()])

    assert _wait_for_file(out) == [str(tricky), str(plain)]


def test_open_with_batch_program_refuses_percent_in_names(monkeypatch, tmp_path):
    from wafer.core.platform import folders

    started = []
    monkeypatch.setattr(folders.subprocess, "Popen", lambda *a, **k: started.append(a))
    batch, _ = _recording_batch(tmp_path)

    assert not folders.open_with(str(batch), [str(tmp_path / "100%PATH%.png")])
    assert started == []


def test_open_with_skips_virtual_paths(monkeypatch, tmp_path):
    from wafer.core.platform import folders

    started = []
    monkeypatch.setattr(folders.subprocess, "Popen", lambda args: started.append(args))
    program = tmp_path / "app.exe"
    program.write_bytes(b"")
    real = (tmp_path / "a.png").as_posix()

    assert folders.open_with(str(program), [build_virtual_path(str(tmp_path / "x.zip"), "in.png"), real])
    assert started == [[str(program), str(tmp_path / "a.png")]]


def test_open_with_missing_program_does_not_start(monkeypatch, tmp_path):
    from wafer.core.platform import folders

    started = []
    monkeypatch.setattr(folders.subprocess, "Popen", lambda args: started.append(args))

    assert not folders.open_with(str(tmp_path / "missing.exe"), [str(tmp_path / "a.png")])
    assert not folders.open_with("", [str(tmp_path / "a.png")])
    assert started == []


def test_make_directory_rejects_virtual_path(tmp_path):
    virtual_dir = build_virtual_path(str(tmp_path / "archive.zip"), "new_folder")

    assert make_directory(virtual_dir) is None

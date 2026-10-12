import os
import tempfile
from pathlib import Path

import pytest

from wafer.constants import APP_DATA_DIR_NAME
from wafer.core.common.paths import (
    containing_dir,
    list_files,
    normalize_path,
    resolve_cache_path,
    resolve_temp_path,
    safe_exists,
    safe_getsize,
    safe_is_dir,
    safe_is_file,
    stem,
)


class _FakePlatformDirs:
    def __init__(self, appname=None):
        self.user_data_dir = "/tmp/wafer-data"


def test_normalize_path():
    result = normalize_path("a\\b\\c")
    assert "\\" not in result
    assert "/" in result


def test_normalize_path_absolute():
    result = normalize_path(os.path.abspath("."))
    assert "/" in result
    assert os.path.isabs(result)


def test_normalize_path_makes_relative_absolute():
    assert os.path.isabs(normalize_path("relative/path.txt"))


def test_normalize_path_resolves_parent_segments(tmp_path):
    assert ".." not in normalize_path(str(tmp_path / "sub" / ".." / "file.txt"))


def test_normalize_path_does_not_resolve_through_filesystem(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("normalize_path must be a pure string operation")

    monkeypatch.setattr(Path, "resolve", fail)
    monkeypatch.setattr(os.path, "realpath", fail)
    assert normalize_path("C:/data/a.png") == "C:/data/a.png"


@pytest.mark.skipif(os.name != "nt", reason="Windows drive letters")
def test_normalize_path_uppercases_drive_letter_only():
    assert normalize_path(r"b:\Data\Foo.PNG") == "B:/Data/Foo.PNG"


@pytest.mark.skipif(os.name != "nt", reason="Windows drive letters")
def test_normalize_path_collapses_redundant_segments():
    assert normalize_path("B:/a//b/./c/../d.zip") == "B:/a/b/d.zip"


@pytest.mark.skipif(os.name != "nt", reason="Windows drive letters")
def test_normalize_path_is_idempotent():
    for raw in (r"b:\x\..\Y.png", "B:/ダウン/a b.zip", "M:/x/", "C:/"):
        once = normalize_path(raw)
        assert normalize_path(once) == once


def test_safe_exists(tmp_path):
    p = tmp_path / "exists.txt"
    p.write_text("ok")
    assert safe_exists(str(p)) is True
    assert safe_exists(str(tmp_path / "nope.txt")) is False


def test_safe_is_file(tmp_path):
    p = tmp_path / "file.txt"
    p.write_text("ok")
    assert safe_is_file(str(p)) is True
    assert safe_is_file(str(tmp_path)) is False


def test_safe_is_dir(tmp_path):
    assert safe_is_dir(str(tmp_path)) is True
    assert safe_is_dir(str(tmp_path / "nope")) is False


def test_safe_getsize(tmp_path):
    p = tmp_path / "sized.bin"
    p.write_bytes(b"12345")
    assert safe_getsize(str(p)) == 5
    assert safe_getsize(str(tmp_path / "nope")) is None


def test_containing_dir_returns_dir_itself(tmp_path):
    assert containing_dir(str(tmp_path)) == os.path.abspath(str(tmp_path))


def test_containing_dir_returns_parent_for_file(tmp_path):
    f = tmp_path / "a.txt"
    f.write_text("x")
    assert containing_dir(str(f)) == os.path.abspath(str(tmp_path))


def test_containing_dir_uses_parent_for_nonexistent(tmp_path):
    missing = tmp_path / "nope" / "file.txt"
    assert containing_dir(str(missing)) == os.path.abspath(str(tmp_path / "nope"))


def test_resolve_cache_path_uses_app_cache_dir(monkeypatch):
    import wafer.core.common.paths as paths

    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    result = resolve_cache_path("updates/latest.json")

    assert result.endswith(f"/wafer-data/{APP_DATA_DIR_NAME}/.cache/updates/latest.json")


def test_resolve_temp_path_uses_app_temp_dir(monkeypatch):
    import wafer.core.common.paths as paths

    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    result = resolve_temp_path("comfyui_workflows/abc.json")

    assert result.endswith(f"/wafer-data/{APP_DATA_DIR_NAME}/.temp/comfyui_workflows/abc.json")


def test_get_name_without_ext():
    assert stem("/path/to/file.txt") == "file"
    assert stem("image.png") == "image"
    assert stem("noext") == "noext"
    assert stem("/a/b.c.d.txt") == "b.c.d"
    assert stem("/dir/.hidden") == ".hidden"


def test_list_files():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.txt").write_text("a")
        (Path(d) / "b.txt").write_text("b")
        (Path(d) / "c.json").write_text("{}")
        result = list_files(d, ".txt")
        assert len(result) == 2
        names = [os.path.basename(r) for r in result]
        assert "a.txt" in names
        assert "b.txt" in names


def test_list_files_dot_prefix():
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / "a.log").write_text("")
        result = list_files(d, "log")
        assert len(result) == 1


def test_list_files_no_match(tmp_path):
    (tmp_path / "a.txt").write_text("x")
    assert list_files(str(tmp_path), ".py") == []


def test_list_files_extension_is_case_insensitive(tmp_path):
    (tmp_path / "upper.TXT").write_text("x")
    assert len(list_files(str(tmp_path), ".txt")) == 1

import os
import tempfile
from pathlib import Path

from wafer.constants import APP_DATA_DIR_NAME
from wafer.utils.paths import normalize_path, natural_sort, resolve_cache_path, stem, list_files


class _FakePlatformDirs:
    def __init__(self, appname=None):
        self.user_cache_dir = "/tmp/wafer-cache"


def test_normalize_path():
    result = normalize_path("a\\b\\c")
    assert "\\" not in result
    assert "/" in result


def test_normalize_path_absolute():
    result = normalize_path(os.path.abspath("."))
    assert "/" in result


def test_resolve_cache_path_uses_app_cache_dir(monkeypatch):
    import wafer.utils.paths as paths

    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    result = resolve_cache_path("updates/latest.json")

    assert result.endswith(f"/wafer-cache/{APP_DATA_DIR_NAME}/updates/latest.json")


def test_natural_sort():
    result = natural_sort(["b2", "a10", "a2", "a1"])
    assert result[0] == "a1"
    assert result[1] == "a2"
    assert result[2] == "a10"
    assert result[3] == "b2"


def test_get_name_without_ext():
    assert stem("/path/to/file.txt") == "file"
    assert stem("image.png") == "image"
    assert stem("noext") == "noext"


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

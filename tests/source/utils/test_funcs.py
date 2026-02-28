import os
import tempfile
from pathlib import Path

from source.utils.paths import normalize_path, natural_sort, stem, list_files
from source.utils.formatting import split_last, format_timestamp, format_aspect, format_size, format_size_detail


def test_normalize_path():
    result = normalize_path("a\\b\\c")
    assert "\\" not in result
    assert "/" in result


def test_normalize_path_absolute():
    result = normalize_path(os.path.abspath("."))
    assert "/" in result


def test_natural_sort():
    result = natural_sort(["b2", "a10", "a2", "a1"])
    assert result[0] == "a1"
    assert result[1] == "a2"
    assert result[2] == "a10"
    assert result[3] == "b2"


def test_split_last():
    rest, last = split_last([1, 2, 3])
    assert rest == [1, 2]
    assert last == 3


def test_split_last_empty():
    rest, last = split_last([])
    assert rest == []
    assert last is None


def test_split_last_single():
    rest, last = split_last([42])
    assert rest == []
    assert last == 42


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


def test_format_timestamp():
    import datetime
    ts = datetime.datetime(2024, 1, 15, 12, 30, 45).timestamp()
    result = format_timestamp(ts)
    assert "2024-01-15" in result
    assert "12:30:45" in result


def test_format_timestamp_none():
    assert format_timestamp(None) is None


def test_format_aspect():
    assert format_aspect(1.0) == "1:1"
    assert format_aspect(None) is None
    assert format_aspect(0) == "N/A"
    assert format_aspect(-1) == "N/A"


def test_format_aspect_ratio():
    result = format_aspect(16 / 9)
    assert "16" in result
    assert "9" in result


def test_format_size():
    assert format_size(0) == "0.0 B"
    assert "KB" in format_size(1024)
    assert "MB" in format_size(1024 * 1024)
    assert format_size(None) is None


def test_format_size_detail():
    result = format_size_detail(1500)
    assert "bytes" in result
    assert "1,500" in result
    assert format_size_detail(None) is None

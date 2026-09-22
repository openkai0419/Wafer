from wafer.core.common.formatting import (
    split_last,
    format_timestamp,
    format_aspect,
    format_size,
    format_size_detail,
    format_source_entries,
    format_file_entries,
)


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


def test_format_source_entries_formats_and_skips_empty():
    entries = format_source_entries({"source": "C:/a.png", "size": 1500, "created": "", "modified": None})
    assert dict(entries) == {"source": "C:/a.png", "size": format_size_detail(1500)}


def test_format_source_entries_falls_back_on_invalid_timestamp():
    entries = format_source_entries({"modified": float("inf")})
    assert dict(entries) == {"modified": "inf"}


def test_format_file_entries_formats_aspect_and_skips_empty():
    entries = format_file_entries({"name": "a.png", "path": "", "aspect_ratio": 2.0})
    assert dict(entries) == {"name": "a.png", "aspect_ratio": format_aspect(2.0)}


def test_format_file_entries_falls_back_on_invalid_aspect_ratio():
    entries = format_file_entries({"aspect_ratio": float("inf")})
    assert dict(entries) == {"aspect_ratio": "inf"}

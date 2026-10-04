from wafer.core.common.formatting import (
    natural_key,
    display_prefixed_key,
    format_timestamp,
    format_aspect,
    format_size,
    format_size_detail,
    format_source_entries,
    format_file_entries,
)


def test_natural_key_pure_alpha():
    assert natural_key("abc") == ["abc"]


def test_natural_key_parses_numeric_segments():
    assert 10 in natural_key("file10name")


def test_natural_key_sorts_numbers_numerically():
    assert sorted(["item2", "item10", "item1"], key=natural_key) == ["item1", "item2", "item10"]


def test_natural_key_case_insensitive():
    assert sorted(["B.jpg", "a.jpg", "C.jpg"], key=natural_key) == ["a.jpg", "B.jpg", "C.jpg"]


def test_natural_key_leading_zeros_equal():
    assert natural_key("file_001.jpg") == natural_key("file_1.jpg")


def test_natural_key_keeps_non_ascii_digits_as_text():
    assert natural_key("file①.jpg") == ["file①.jpg"]
    assert sorted(["b①", "a②", "c"], key=natural_key) == ["a②", "b①", "c"]


def test_display_prefixed_key_with_prefix():
    assert display_prefixed_key("exif.width") == "[exif]  width"


def test_display_prefixed_key_without_prefix():
    assert display_prefixed_key("name") == "name"


def test_display_prefixed_key_splits_on_first_dot_only():
    assert display_prefixed_key("nai.prompt.text") == "[nai]  prompt.text"


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


def test_format_aspect_integer_ratio():
    assert format_aspect(2.0) == "2:1"


def test_format_aspect_ratio():
    result = format_aspect(16 / 9)
    assert "16" in result
    assert "9" in result


def test_format_size():
    assert format_size(0) == "0.0 B"
    assert format_size(500) == "500.0 B"
    assert format_size(1024) == "1.0 KB"
    assert format_size(1024 * 1024) == "1.0 MB"
    assert format_size(1024**3) == "1.0 GB"
    assert format_size(None) is None


def test_format_size_detail():
    result = format_size_detail(1500)
    assert "bytes" in result
    assert "1,500" in result
    assert "KB" in result
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

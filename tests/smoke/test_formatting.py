from wafer.utils.formatting import (
    natural_key,
    format_size,
    format_size_detail,
    format_timestamp,
    format_aspect,
    split_last,
    display_prefixed_key,
)


class TestNaturalKey:
    def test_pure_alpha(self):
        assert natural_key("abc") == ["abc"]

    def test_numeric_segments(self):
        key = natural_key("file10name")
        assert 10 in key

    def test_sort_order(self):
        items = ["item2", "item10", "item1"]
        result = sorted(items, key=natural_key)
        assert result == ["item1", "item2", "item10"]


class TestFormatSize:
    def test_bytes(self):
        assert format_size(500) == "500.0 B"

    def test_kilobytes(self):
        assert format_size(1024) == "1.0 KB"

    def test_megabytes(self):
        assert format_size(1024 * 1024) == "1.0 MB"

    def test_gigabytes(self):
        assert format_size(1024**3) == "1.0 GB"

    def test_none_returns_none(self):
        assert format_size(None) is None

    def test_zero(self):
        assert format_size(0) == "0.0 B"


class TestFormatSizeDetail:
    def test_includes_byte_count(self):
        result = format_size_detail(1536)
        assert "1,536 bytes" in result
        assert "KB" in result

    def test_none_returns_none(self):
        assert format_size_detail(None) is None


class TestFormatTimestamp:
    def test_valid_timestamp(self):
        result = format_timestamp(0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_none_returns_none(self):
        assert format_timestamp(None) is None


class TestFormatAspect:
    def test_square(self):
        assert format_aspect(1.0) == "1:1"

    def test_widescreen(self):
        result = format_aspect(16 / 9)
        assert "16" in result and "9" in result

    def test_zero_returns_na(self):
        assert format_aspect(0) == "N/A"

    def test_negative_returns_na(self):
        assert format_aspect(-1.0) == "N/A"

    def test_none_returns_none(self):
        assert format_aspect(None) is None

    def test_2_to_1(self):
        assert format_aspect(2.0) == "2:1"


class TestSplitLast:
    def test_normal_list(self):
        head, last = split_last([1, 2, 3])
        assert head == [1, 2]
        assert last == 3

    def test_single_item(self):
        head, last = split_last([42])
        assert head == []
        assert last == 42

    def test_empty_list(self):
        head, last = split_last([])
        assert head == []
        assert last is None


class TestDisplayPrefixedKey:
    def test_with_prefix(self):
        assert display_prefixed_key("exif.width") == "[exif]  width"

    def test_no_prefix(self):
        assert display_prefixed_key("name") == "name"

    def test_multiple_dots(self):
        result = display_prefixed_key("nai.prompt.text")
        assert result == "[nai]  prompt.text"

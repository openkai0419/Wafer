import py_compile
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from PIL import Image
from PIL.TiffImagePlugin import IFDRational

from source.io.exif_parser import (
    ExifParser,
    _clean_text,
    _looks_binary_payload,
    _summarize_binary_value,
    _decode_bytes_safely,
    _decode_xp_value,
    _decode_user_comment,
    _rational_to_float,
    _dms_to_deg,
    _orientation_adjusted_size,
)


def test_compile_exif_parser():
    py_compile.compile('source/io/exif_parser.py')


class TestCleanText:
    def test_removes_null(self):
        assert _clean_text("abc\x00def") == "abcdef"

    def test_removes_control_chars(self):
        assert _clean_text("ab\x01cd") == "abcd"

    def test_keeps_tab_newline(self):
        assert _clean_text("a\tb\n") == "a\tb\n"

    def test_nfc_normalization(self):
        result = _clean_text("\u0041\u0301")
        assert result == "\u00C1"

    def test_non_string_input(self):
        assert _clean_text(123) == "123"


class TestLooksBinaryPayload:
    def test_empty(self):
        is_bin, ratio = _looks_binary_payload(b'')
        assert not is_bin
        assert ratio == 0.0

    def test_text(self):
        is_bin, _ = _looks_binary_payload(b'Hello World')
        assert not is_bin

    def test_binary(self):
        is_bin, _ = _looks_binary_payload(bytes(range(256)))
        assert is_bin


class TestSummarizeBinaryValue:
    def test_format(self):
        data = bytes(range(20))
        result = _summarize_binary_value("test", data, 0.8)
        assert "bin=test" in result
        assert "80.0%" in result
        assert "size=20" in result


class TestDecodeByteSafely:
    def test_utf8(self):
        assert _decode_bytes_safely("hello".encode('utf-8')) == "hello"

    def test_utf16_bom(self):
        data = "hello".encode('utf-16')
        result = _decode_bytes_safely(data)
        assert "hello" in result

    def test_latin1_fallback(self):
        data = bytes([0xC0, 0xC1, 0x41])
        result = _decode_bytes_safely(data)
        assert isinstance(result, str)


class TestDecodeXpValue:
    def test_bytes_utf16le(self):
        data = "Test".encode('utf-16-le')
        assert _decode_xp_value(data) == "Test"

    def test_list_to_bytes(self):
        data = list("AB".encode('utf-16-le'))
        assert _decode_xp_value(data) == "AB"

    def test_string_passthrough(self):
        assert _decode_xp_value("hello") == "hello"


class TestDecodeUserComment:
    def test_ascii_prefix(self):
        data = b'ASCII\x00\x00\x00Hello'
        assert _decode_user_comment(data) == "Hello"

    def test_unicode_prefix(self):
        payload = "Test".encode('utf-16-le')
        data = b'UNICODE\x00' + b'\xff\xfe' + payload
        result = _decode_user_comment(data)
        assert "Test" in result

    def test_short_data(self):
        result = _decode_user_comment(b'short')
        assert isinstance(result, str)

    def test_non_bytes(self):
        result = _decode_user_comment(bytearray(b'ASCII\x00\x00\x00test'))
        assert result == "test"


class TestRationalToFloat:
    def test_ifd_rational(self):
        r = IFDRational(3, 2)
        assert _rational_to_float(r) == 1.5

    def test_tuple(self):
        assert _rational_to_float((3, 2)) == 1.5

    def test_zero_denominator(self):
        assert _rational_to_float((1, 0)) is None

    def test_plain_float(self):
        assert _rational_to_float(2.5) == 2.5

    def test_invalid(self):
        assert _rational_to_float("bad") is None


class TestDmsToDeg:
    def test_north(self):
        dms = (IFDRational(35, 1), IFDRational(30, 1), IFDRational(0, 1))
        result = _dms_to_deg(dms, 'N')
        assert result == pytest.approx(35.5)

    def test_south(self):
        dms = (IFDRational(35, 1), IFDRational(30, 1), IFDRational(0, 1))
        result = _dms_to_deg(dms, 'S')
        assert result == pytest.approx(-35.5)

    def test_invalid_input(self):
        assert _dms_to_deg(None, 'N') is None
        assert _dms_to_deg((1, 2), 'N') is None


class TestOrientationAdjustedSize:
    def test_normal(self):
        assert _orientation_adjusted_size(100, 200, 1) == (100, 200)

    def test_rotated(self):
        assert _orientation_adjusted_size(100, 200, 6) == (200, 100)

    @pytest.mark.parametrize("orient,swapped", [
        (1, False), (2, False), (3, False), (4, False),
        (5, True), (6, True), (7, True), (8, True),
    ])
    def test_all_orientations(self, orient, swapped):
        w, h = _orientation_adjusted_size(100, 200, orient)
        if swapped:
            assert (w, h) == (200, 100)
        else:
            assert (w, h) == (100, 200)


class TestExifParserToStr:
    def test_string(self):
        assert ExifParser._to_str("hello") == "hello"

    def test_int(self):
        assert ExifParser._to_str(42) == "42"

    def test_ifd_rational(self):
        r = IFDRational(1, 2)
        assert ExifParser._to_str(r) == "0.5"

    def test_tuple(self):
        result = ExifParser._to_str((1, 2, 3))
        assert result == "1, 2, 3"

    def test_bytes(self):
        result = ExifParser._to_str(b'hello')
        assert result == "hello"

    def test_xp_tag(self):
        data = "Title".encode('utf-16-le')
        result = ExifParser._to_str(data, tag_id=0x9C9B)
        assert result == "Title"

    def test_user_comment_tag(self):
        data = b'ASCII\x00\x00\x00Comment'
        result = ExifParser._to_str(data, tag_id=0x9286)
        assert result == "Comment"


class TestExifParserParseGps:
    def test_valid_gps(self):
        gps_ifd = {
            1: 'N',
            2: (IFDRational(35, 1), IFDRational(40, 1), IFDRational(0, 1)),
            3: 'E',
            4: (IFDRational(139, 1), IFDRational(45, 1), IFDRational(0, 1)),
        }
        result = ExifParser._parse_gps(gps_ifd)
        assert "GPS/GPSLatitudeDecimal" in result
        assert "GPS/GPSLongitudeDecimal" in result
        assert result["GPS/GPSLatitudeDecimal"] == pytest.approx(35.6667, abs=0.01)

    def test_invalid_input(self):
        assert ExifParser._parse_gps("not a dict") == {}


class TestExifParserExtractFromExifObj:
    def test_empty(self):
        assert ExifParser._extract_from_exif_obj(None) == {}
        assert ExifParser._extract_from_exif_obj({}) == {}

    def test_known_tag(self):
        result = ExifParser._extract_from_exif_obj({271: "Canon"})
        assert result.get("Make") == "Canon"


class TestExifParserParseInfoDict:
    def test_empty(self):
        assert ExifParser.parse_info_dict({}) == {}
        assert ExifParser.parse_info_dict(None) == {}

    def test_text_value(self):
        result = ExifParser.parse_info_dict({"key": "value"})
        assert result["key"] == "value"

    def test_binary_value(self):
        data = bytes(range(256))
        result = ExifParser.parse_info_dict({"bin": data})
        assert result["bin"].startswith("<bin=")

    def test_bytes_text(self):
        result = ExifParser.parse_info_dict({"txt": b"hello"})
        assert result["txt"] == "hello"


class TestExifParserParseImg:
    def test_with_mock_image(self):
        img = MagicMock(spec=Image.Image)
        img.size = (100, 200)
        exif_mock = MagicMock()
        exif_mock.__bool__ = lambda s: True
        exif_mock.get = lambda k, d=None: 1
        exif_mock.items = lambda: [(271, "Canon")]
        img.getexif.return_value = exif_mock
        img.info = {"test": "value"}

        result = ExifParser.parse_img(img)
        assert result["width"] == 100
        assert result["height"] == 200
        assert result["orientation"] == 1
        assert result["aspect"] == pytest.approx(0.5)
        assert result["error"] is None

    def test_rotated_orientation(self):
        img = MagicMock(spec=Image.Image)
        img.size = (100, 200)
        exif_mock = MagicMock()
        exif_mock.__bool__ = lambda s: True
        exif_mock.get = lambda k, d=None: 6
        exif_mock.items = lambda: []
        img.getexif.return_value = exif_mock
        img.info = {}

        result = ExifParser.parse_img(img)
        assert result["width"] == 200
        assert result["height"] == 100

    def test_no_exif(self):
        img = MagicMock(spec=Image.Image)
        img.size = (100, 200)
        exif_mock = MagicMock()
        exif_mock.__bool__ = lambda s: False
        exif_mock.get = lambda k, d=None: None
        exif_mock.items = lambda: []
        img.getexif.return_value = exif_mock
        img.info = {}

        result = ExifParser.parse_img(img)
        assert result["width"] == 100
        assert result["height"] == 200
        assert result["orientation"] == 1

    def test_exception_handling(self):
        img = MagicMock(spec=Image.Image)
        img.getexif.side_effect = RuntimeError("test error")

        result = ExifParser.parse_img(img)
        assert result["error"] is not None
        assert "test error" in result["error"]

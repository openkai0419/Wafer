import json
import tempfile
from pathlib import Path

from wayfer.utils.json_io import read_json_file, write_json_file


def test_write_and_read():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "test.json"
        data = {"key": "value", "num": 42}
        assert write_json_file(p, data) is True
        result = read_json_file(p)
        assert result == data


def test_read_nonexistent_returns_default():
    result = read_json_file("/nonexistent/path.json")
    assert result is None


def test_read_nonexistent_custom_default():
    result = read_json_file("/nonexistent/path.json", default=[])
    assert result == []


def test_read_invalid_json_returns_default():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "bad.json"
        p.write_text("not valid json {{{", encoding="utf-8")
        result = read_json_file(p, default="fallback")
        assert result == "fallback"


def test_write_creates_parent_dirs():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "sub" / "deep" / "test.json"
        assert write_json_file(p, [1, 2, 3]) is True
        assert p.exists()
        assert read_json_file(p) == [1, 2, 3]


def test_write_unicode():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "unicode.json"
        data = {"text": "日本語テスト"}
        write_json_file(p, data)
        raw = p.read_text(encoding="utf-8")
        assert "日本語" in raw


def test_write_indent():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "indent.json"
        write_json_file(p, {"a": 1}, indent=4)
        raw = p.read_text(encoding="utf-8")
        assert "    " in raw


def test_roundtrip_complex():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "complex.json"
        data = {"list": [1, 2, 3], "nested": {"a": True, "b": None}}
        write_json_file(p, data)
        assert read_json_file(p) == data

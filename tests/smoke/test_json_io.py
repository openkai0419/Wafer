from pathlib import Path

from wafer.utils.json_io import read_json_file, write_json_file


class TestReadJsonFile:
    def test_read_valid_json(self, tmp_path):
        p = tmp_path / "data.json"
        p.write_text('{"key": "value", "num": 42}', encoding="utf-8")
        result = read_json_file(str(p))
        assert result == {"key": "value", "num": 42}

    def test_read_nonexistent_returns_default(self, tmp_path):
        result = read_json_file(str(tmp_path / "nope.json"), default={"empty": True})
        assert result == {"empty": True}

    def test_read_nonexistent_returns_none_by_default(self, tmp_path):
        result = read_json_file(str(tmp_path / "nope.json"))
        assert result is None

    def test_read_invalid_json_returns_default(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("{broken", encoding="utf-8")
        result = read_json_file(str(p), default=[])
        assert result == []

    def test_read_with_path_object(self, tmp_path):
        p = tmp_path / "path.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        result = read_json_file(p)
        assert result == [1, 2, 3]


class TestWriteJsonFile:
    def test_write_and_read_roundtrip(self, tmp_path):
        p = tmp_path / "out.json"
        data = {"name": "test", "values": [1, 2, 3], "nested": {"a": True}}
        assert write_json_file(str(p), data) is True
        result = read_json_file(str(p))
        assert result == data

    def test_write_creates_parent_dirs(self, tmp_path):
        p = tmp_path / "a" / "b" / "c" / "deep.json"
        assert write_json_file(str(p), {"deep": True}) is True
        assert read_json_file(str(p)) == {"deep": True}

    def test_write_unicode(self, tmp_path):
        p = tmp_path / "unicode.json"
        data = {"text": "日本語テスト", "emoji": "🎨"}
        write_json_file(str(p), data, ensure_ascii=False)
        result = read_json_file(str(p))
        assert result["text"] == "日本語テスト"

    def test_type_preservation(self, tmp_path):
        p = tmp_path / "types.json"
        data = {
            "str": "hello",
            "int": 42,
            "float": 3.14,
            "bool_t": True,
            "bool_f": False,
            "null": None,
            "list": [1, "two", 3.0],
            "dict": {"inner": "val"},
        }
        write_json_file(str(p), data)
        result = read_json_file(str(p))
        assert result["str"] == "hello"
        assert result["int"] == 42
        assert result["float"] == 3.14
        assert result["bool_t"] is True
        assert result["bool_f"] is False
        assert result["null"] is None
        assert result["list"] == [1, "two", 3.0]
        assert result["dict"] == {"inner": "val"}

    def test_overwrite_existing(self, tmp_path):
        p = tmp_path / "rw.json"
        write_json_file(str(p), {"v": 1})
        write_json_file(str(p), {"v": 2})
        assert read_json_file(str(p)) == {"v": 2}

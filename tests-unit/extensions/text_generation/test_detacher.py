import json

from extensions.text_generation.detacher import NovelAiImageDetacher
from wafer.plugin.detacher.base import BaseSingletonDetacher, DetacherResult


class TestNovelAiImageDetacher:
    def setup_method(self):
        self.detacher = NovelAiImageDetacher()

    def test_inherits_singleton(self):
        assert isinstance(self.detacher, BaseSingletonDetacher)

    def test_trigger_keys(self):
        assert self.detacher.TRIGGER_KEYS == ("exif.Comment",)

    def test_valid_json_dict(self):
        data = {"prompt": "a cat", "steps": 20, "cfg": 7.5}
        metadata = {"exif.Comment": json.dumps(data)}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {
            "prompt": "a cat",
            "steps": "20",
            "cfg": "7.5",
        }
        assert result.delete_keys == ["exif.Comment", "exif.Description"]

    def test_nested_value_stringified(self):
        data = {"model": {"name": "v3", "hash": "abc"}}
        metadata = {"exif.Comment": json.dumps(data)}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["model"] == "{'name': 'v3', 'hash': 'abc'}"

    def test_empty_dict(self):
        metadata = {"exif.Comment": "{}"}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {}

    def test_invalid_json(self):
        metadata = {"exif.Comment": "not json at all"}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_json_list_rejected(self):
        metadata = {"exif.Comment": "[1, 2, 3]"}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_json_string_rejected(self):
        metadata = {"exif.Comment": '"just a string"'}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_missing_key(self):
        metadata = {}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result is None

    def test_none_value(self):
        metadata = {"exif.Comment": None}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert result is None

    def test_result_type(self):
        data = {"seed": 42}
        metadata = {"exif.Comment": json.dumps(data)}
        result = self.detacher.process("img.png", (100, 1.0), metadata)
        assert isinstance(result, DetacherResult)

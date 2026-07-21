import json

from extensions.text_generation.parser import NovelAiImageParser
from wafer.plugin.parser.base import BaseSingletonParser, ParserResult


class TestNovelAiImageParser:
    def setup_method(self):
        self.parser = NovelAiImageParser()

    def test_inherits_singleton(self):
        assert isinstance(self.parser, BaseSingletonParser)

    def test_trigger_keys(self):
        assert self.parser.TRIGGER_KEYS == ("exiftool.PNG:Comment", "exiftool.ExifIFD:UserComment")

    def test_valid_json_dict(self):
        data = {"prompt": "a cat", "steps": 20, "cfg": 7.5}
        metadata = {"exiftool.PNG:Comment": json.dumps(data)}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {
            "prompt": "a cat",
            "steps": "20",
            "cfg": "7.5",
        }
        assert result.delete_keys == ["exiftool.PNG:Comment", "exiftool.ExifIFD:UserComment"]

    def test_nested_value_flattened_recursively(self):
        data = {"model": {"name": "v3", "details": {"hash": "abc", "samplers": ["k_euler"]}}}
        metadata = {"exiftool.PNG:Comment": json.dumps(data)}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {
            "model/name": "v3",
            "model/details/hash": "abc",
            "model/details/samplers": "['k_euler']",
        }

    def test_empty_dict(self):
        metadata = {"exiftool.PNG:Comment": "{}"}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {}

    def test_invalid_json(self):
        metadata = {"exiftool.PNG:Comment": "not json at all"}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_json_list_rejected(self):
        metadata = {"exiftool.PNG:Comment": "[1, 2, 3]"}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_json_string_rejected(self):
        metadata = {"exiftool.PNG:Comment": '"just a string"'}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is False

    def test_missing_key(self):
        metadata = {}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result is None

    def test_none_value(self):
        metadata = {"exiftool.PNG:Comment": None}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result is None

    def test_result_type(self):
        data = {"seed": 42}
        metadata = {"exiftool.PNG:Comment": json.dumps(data)}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert isinstance(result, ParserResult)

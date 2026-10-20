import json

from extensions.text_generation import novelai_parser
from extensions.text_generation.novelai_parser import NovelAiImageParser


class TestNovelAiImageParser:
    def setup_method(self):
        self.parser = NovelAiImageParser()

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
        assert result.delete_meta_keys == ["exiftool.PNG:Comment"]

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

    def test_embedded_json_comment_expanded_transparently(self):
        inner = {"prompt": "a cat", "steps": 28, "seed": 123}
        data = {"Software": "NovelAI", "Comment": json.dumps(inner)}
        metadata = {"exiftool.ExifIFD:UserComment": json.dumps(data)}
        result = self.parser.process("img.jpg", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {
            "Software": "NovelAI",
            "prompt": "a cat",
            "steps": "28",
            "seed": "123",
        }

    def test_embedded_json_string_not_dict_kept_as_string(self):
        data = {"Comment": "[1, 2, 3]", "note": '"plain"'}
        metadata = {"exiftool.PNG:Comment": json.dumps(data)}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {"Comment": "[1, 2, 3]", "note": '"plain"'}

    def test_v4_char_captions_expanded_per_character(self):
        characters = [
            {"char_caption": "1girl, red hair", "centers": [{"x": 0.3, "y": 0.5}]},
            {"char_caption": "1boy, glasses", "centers": [{"x": 0.7, "y": 0.5}]},
        ]
        data = {
            "v4_prompt": {"caption": {"base_caption": "classroom", "char_captions": characters}, "use_order": True},
            "v4_negative_prompt": {"caption": {"base_caption": "lowres", "char_captions": [{"char_caption": "blurry"}]}},
        }
        metadata = {"exiftool.PNG:Comment": json.dumps(data)}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.meta_info == {
            "v4_prompt/caption/base_caption": "classroom",
            "v4_prompt/caption/char_captions": "1girl, red hair\n1boy, glasses",
            "v4_prompt/caption/char_captions/0/char_caption": "1girl, red hair",
            "v4_prompt/caption/char_captions/0/centers/0/x": "0.3",
            "v4_prompt/caption/char_captions/0/centers/0/y": "0.5",
            "v4_prompt/caption/char_captions/1/char_caption": "1boy, glasses",
            "v4_prompt/caption/char_captions/1/centers/0/x": "0.7",
            "v4_prompt/caption/char_captions/1/centers/0/y": "0.5",
            "v4_prompt/use_order": "True",
            "v4_negative_prompt/caption/base_caption": "lowres",
            "v4_negative_prompt/caption/char_captions": "blurry",
            "v4_negative_prompt/caption/char_captions/0/char_caption": "blurry",
        }

    def test_v4_char_captions_empty_list_kept_as_string(self):
        data = {"v4_prompt": {"caption": {"base_caption": "sky", "char_captions": []}}}
        result = self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Comment": json.dumps(data)})
        assert result.meta_info == {"v4_prompt/caption/base_caption": "sky", "v4_prompt/caption/char_captions": "[]"}

    def test_v4_char_captions_inside_embedded_comment(self):
        inner = {"v4_prompt": {"caption": {"char_captions": [{"char_caption": "1girl"}]}}}
        data = {"Software": "NovelAI", "Comment": json.dumps(inner)}
        result = self.parser.process("img.jpg", (100, 1.0), {"exiftool.ExifIFD:UserComment": json.dumps(data)})
        assert result.meta_info == {
            "Software": "NovelAI",
            "v4_prompt/caption/char_captions": "1girl",
            "v4_prompt/caption/char_captions/0/char_caption": "1girl",
        }

    def test_empty_dict(self):
        metadata = {"exiftool.PNG:Comment": "{}"}
        result = self.parser.process("img.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {}

    def test_non_json_comment_skipped_without_log(self, monkeypatch):
        logs = []
        monkeypatch.setattr(novelai_parser.AppLogger, "debug", logs.append)
        infotext = "1girl, solo\nNegative prompt: lowres\nSteps: 28, Sampler: Euler a"
        result = self.parser.process("img.jpg", (100, 1.0), {"exiftool.ExifIFD:UserComment": infotext})
        assert result.status is False
        assert logs == []

    def test_broken_json_logs_path_without_raw(self, monkeypatch):
        logs = []
        monkeypatch.setattr(novelai_parser.AppLogger, "debug", logs.append)
        raw = '{"prompt": "secret prompt text", '
        result = self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Comment": raw})
        assert result.status is False
        assert len(logs) == 1
        assert "img.png" in logs[0]
        assert "secret prompt text" not in logs[0]

    def test_json_non_dict_rejected(self):
        for raw in ("[1, 2, 3]", '"just a string"'):
            result = self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Comment": raw})
            assert result.status is False

    def test_missing_key(self):
        assert self.parser.process("img.png", (100, 1.0), {}) is None
        assert self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Comment": None}) is None

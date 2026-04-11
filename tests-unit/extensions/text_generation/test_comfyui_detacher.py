import json

from extensions.text_generation.comfyui_detacher import ComfyUiDetacher
from wafer.plugin.detacher.base import BaseSingletonDetacher, DetacherResult


class TestComfyUiDetacher:
    def setup_method(self):
        self.detacher = ComfyUiDetacher()

    def test_inherits_singleton(self):
        assert isinstance(self.detacher, BaseSingletonDetacher)

    def test_trigger_keys(self):
        assert self.detacher.TRIGGER_KEYS == ("ffmpeg.Tag/comment",)

    def test_valid_json_dict(self):
        data = {"prompt": "a cat", "steps": 20, "cfg": 7.5}
        metadata = {"ffmpeg.Tag/comment": json.dumps(data)}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {"prompt": "a cat", "steps": "20", "cfg": "7.5"}
        assert result.delete_keys == ["ffmpeg.Tag/comment"]

    def test_all_toplevel_keys_included(self):
        data = {"workflow": "basic", "seed": 42, "custom_key": "value"}
        metadata = {"ffmpeg.Tag/comment": json.dumps(data)}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {"workflow": "basic", "seed": "42", "custom_key": "value"}

    def test_nested_value_stringified(self):
        data = {"model": {"name": "v3", "hash": "abc"}}
        metadata = {"ffmpeg.Tag/comment": json.dumps(data)}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["model"] == "{'name': 'v3', 'hash': 'abc'}"

    def test_empty_dict(self):
        metadata = {"ffmpeg.Tag/comment": "{}"}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info == {}

    def test_invalid_json(self):
        metadata = {"ffmpeg.Tag/comment": "not json"}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is False

    def test_json_list_rejected(self):
        metadata = {"ffmpeg.Tag/comment": "[1, 2, 3]"}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is False

    def test_json_string_rejected(self):
        metadata = {"ffmpeg.Tag/comment": '"just a string"'}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result.status is False

    def test_missing_key(self):
        result = self.detacher.process("video.mp4", (100, 1.0), {})
        assert result is None

    def test_none_value(self):
        metadata = {"ffmpeg.Tag/comment": None}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert result is None

    def test_result_type(self):
        data = {"seed": 42}
        metadata = {"ffmpeg.Tag/comment": json.dumps(data)}
        result = self.detacher.process("video.mp4", (100, 1.0), metadata)
        assert isinstance(result, DetacherResult)

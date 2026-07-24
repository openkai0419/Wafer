import json

from extensions.text_generation.comfyui_parser import ComfyUiParser
from wafer.plugin.parser.base import BaseSingletonParser, ParserResult

PROMPT = {
    "3": {"class_type": "KSampler", "inputs": {"seed": 42, "steps": 20, "model": ["4", 0]}},
    "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "v3.safetensors"}},
}
WORKFLOW = {"nodes": [{"id": 3, "type": "KSampler"}], "links": []}


class TestComfyUiParser:
    def setup_method(self):
        self.parser = ComfyUiParser()

    def test_inherits_singleton(self):
        assert isinstance(self.parser, BaseSingletonParser)

    def test_name_matches_prefix(self):
        assert self.parser.NAME == "comfyui"

    def test_trigger_keys(self):
        assert self.parser.TRIGGER_KEYS == (
            "exiftool.PNG:Prompt",
            "exiftool.PNG:Workflow",
            "exiftool.IFD0:Model",
            "exiftool.IFD0:Make",
            "ffmpeg.Tag/prompt",
            "ffmpeg.Tag/workflow",
            "ffmpeg.Tag/comment",
        )

    def test_png_prompt_and_workflow(self):
        metadata = {"exiftool.PNG:Prompt": json.dumps(PROMPT), "exiftool.PNG:Workflow": json.dumps(WORKFLOW)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["KSampler#0/seed"] == "42"
        assert result.meta_info["KSampler#0/steps"] == "20"
        assert "KSampler#0/model" not in result.meta_info
        assert result.meta_info["CheckpointLoaderSimple#0/ckpt_name"] == "v3.safetensors"
        assert result.meta_info["workflow"] == json.dumps(WORKFLOW)
        assert set(result.delete_keys) == {"exiftool.PNG:Prompt", "exiftool.PNG:Workflow"}

    def test_webp_prefix_stripped(self):
        metadata = {
            "exiftool.IFD0:Model": "prompt:" + json.dumps(PROMPT),
            "exiftool.IFD0:Make": "workflow:" + json.dumps(WORKFLOW),
        }
        result = self.parser.process("a.webp", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["KSampler#0/seed"] == "42"
        assert result.meta_info["workflow"] == json.dumps(WORKFLOW)

    def test_ffmpeg_prompt_workflow(self):
        metadata = {"ffmpeg.Tag/prompt": json.dumps(PROMPT), "ffmpeg.Tag/workflow": json.dumps(WORKFLOW)}
        result = self.parser.process("a.flac", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["CheckpointLoaderSimple#0/ckpt_name"] == "v3.safetensors"

    def test_comment_wrapper(self):
        metadata = {"ffmpeg.Tag/comment": json.dumps({"prompt": PROMPT, "workflow": WORKFLOW})}
        result = self.parser.process("a.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["KSampler#0/seed"] == "42"
        assert result.meta_info["workflow"] == json.dumps(WORKFLOW)

    def test_comment_workflow_only(self):
        metadata = {"ffmpeg.Tag/comment": json.dumps(WORKFLOW)}
        result = self.parser.process("a.mp4", (100, 1.0), metadata)
        assert result.status is True
        assert result.meta_info["workflow"] == json.dumps(WORKFLOW)

    def test_ordinal_by_ascending_node_id(self):
        prompt = {
            "10": {"class_type": "KSampler", "inputs": {"seed": 10}},
            "2": {"class_type": "KSampler", "inputs": {"seed": 2}},
        }
        metadata = {"exiftool.PNG:Prompt": json.dumps(prompt)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.meta_info["KSampler#0/seed"] == "2"
        assert result.meta_info["KSampler#1/seed"] == "10"

    def test_title_ignored_uses_class_type(self):
        prompt = {"3": {"class_type": "KSampler", "_meta": {"title": "MySampler"}, "inputs": {"seed": 7}}}
        metadata = {"exiftool.PNG:Prompt": json.dumps(prompt)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.meta_info["KSampler#0/seed"] == "7"
        assert "MySampler#0/seed" not in result.meta_info

    def test_connections_excluded(self):
        prompt = {"3": {"class_type": "KSampler", "inputs": {"seed": 42, "model": ["4", 0], "latent": ["5", 0]}}}
        metadata = {"exiftool.PNG:Prompt": json.dumps(prompt)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.meta_info == {"KSampler#0/seed": "42"}

    def test_nested_input_expanded(self):
        prompt = {"3": {"class_type": "Node", "inputs": {"opts": {"a": 1, "b": 2}}}}
        metadata = {"exiftool.PNG:Prompt": json.dumps(prompt)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.meta_info["Node#0/opts/a"] == "1"
        assert result.meta_info["Node#0/opts/b"] == "2"

    def test_non_comfy_trigger_marked_fail(self):
        metadata = {"exiftool.IFD0:Make": "Canon", "exiftool.IFD0:Model": "EOS R5"}
        result = self.parser.process("photo.jpg", (100, 1.0), metadata)
        assert result.status is False
        assert result.meta_info is None

    def test_missing_keys(self):
        result = self.parser.process("a.png", (100, 1.0), {})
        assert result is None

    def test_invalid_json(self):
        metadata = {"exiftool.PNG:Prompt": "not json"}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert result.status is False

    def test_result_type(self):
        metadata = {"exiftool.PNG:Prompt": json.dumps(PROMPT)}
        result = self.parser.process("a.png", (100, 1.0), metadata)
        assert isinstance(result, ParserResult)

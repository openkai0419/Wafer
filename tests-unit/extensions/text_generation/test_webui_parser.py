import json

from extensions.text_generation.webui_parser import WebUiImageParser, parse_infotext

SAMPLE = (
    "masterpiece, 1girl, blue eyes\n"
    "Negative prompt: lowres, bad anatomy\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x768, "
    "Model hash: abc123, Model: some_model, Clip skip: 2, Version: f1.0.0"
)


class TestWebUiImageParser:
    def setup_method(self):
        self.parser = WebUiImageParser()

    def test_full_infotext(self):
        result = self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Parameters": SAMPLE})
        assert result.status is True
        assert result.meta_info == {
            "prompt": "masterpiece, 1girl, blue eyes",
            "negative_prompt": "lowres, bad anatomy",
            "Steps": "20",
            "Sampler": "Euler a",
            "CFG scale": "7",
            "Seed": "12345",
            "width": "512",
            "height": "768",
            "Model hash": "abc123",
            "Model": "some_model",
            "Clip skip": "2",
            "Version": "f1.0.0",
        }
        assert result.delete_meta_keys == ["exiftool.PNG:Parameters"]

    def test_multiline_prompt(self):
        raw = "line one\nline two\nNegative prompt: neg one\nneg two\nSteps: 10, Sampler: DPM++ 2M, CFG scale: 5"
        meta = parse_infotext(raw)
        assert meta["prompt"] == "line one\nline two"
        assert meta["negative_prompt"] == "neg one\nneg two"
        assert meta["Steps"] == "10"

    def test_no_negative_prompt(self):
        raw = "just a prompt\nSteps: 20, Sampler: Euler, CFG scale: 7"
        meta = parse_infotext(raw)
        assert meta["prompt"] == "just a prompt"
        assert "negative_prompt" not in meta

    def test_quoted_value_with_comma(self):
        raw = 'p\nSteps: 20, Sampler: Euler, CFG scale: 7, Lora hashes: "a: h1, b: h2"'
        meta = parse_infotext(raw)
        assert meta["Lora hashes"] == "a: h1, b: h2"

    def test_embedded_json_value_expanded(self):
        hashes = {"model": "abc", "lora:x": "def"}
        raw = f"p\nSteps: 20, Sampler: Euler, CFG scale: 7, Hashes: {json.dumps(json.dumps(hashes))}"
        meta = parse_infotext(raw)
        assert meta["Hashes/model"] == "abc"
        assert meta["Hashes/lora:x"] == "def"

    def test_novelai_json_rejected(self):
        data = {"prompt": "a cat", "steps": 28}
        result = self.parser.process("img.png", (100, 1.0), {"exiftool.ExifIFD:UserComment": json.dumps(data)})
        assert result.status is False

    def test_plain_text_without_params_rejected(self):
        result = self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Parameters": "just a caption"})
        assert result.status is False

    def test_missing_key(self):
        assert self.parser.process("img.png", (100, 1.0), {}) is None
        assert self.parser.process("img.png", (100, 1.0), {"exiftool.PNG:Parameters": None}) is None

    def test_usercomment_fallback(self):
        result = self.parser.process("img.jpg", (100, 1.0), {"exiftool.ExifIFD:UserComment": SAMPLE})
        assert result.status is True
        assert result.meta_info["Steps"] == "20"

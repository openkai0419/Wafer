from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image
from transformers import AutoModelForCausalLM, AutoProcessor

from wafer.utils.logs import AppLogger


class FlorenceInference:
    def __init__(self, model_dir: Path):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32

        if self.device.type == "cpu":
            AppLogger.warning("Florence-2 running on CPU. Inference will be significantly slower")

        self.processor = AutoProcessor.from_pretrained(str(model_dir), trust_remote_code=True)
        self.model = (
            AutoModelForCausalLM.from_pretrained(
                str(model_dir),
                torch_dtype=self.dtype,
                trust_remote_code=True,
                attn_implementation="eager",
            )
            .to(self.device)
            .eval()
        )
        self._patch_generate()

        AppLogger.info(f"Florence-2 engine loaded: device={self.device}, dtype={self.dtype}, model={model_dir.name}")

    def _patch_generate(self):
        lang = self.model.language_model
        _orig = lang.prepare_inputs_for_generation

        def _patched(input_ids, past_key_values=None, **kwargs):
            if past_key_values is not None and not isinstance(past_key_values, tuple):
                if hasattr(past_key_values, "to_legacy_cache"):
                    past_key_values = past_key_values.to_legacy_cache() or None
            if isinstance(past_key_values, (list, tuple)) and len(past_key_values) > 0:
                if past_key_values[0][0] is None:
                    past_key_values = None
            return _orig(input_ids, past_key_values=past_key_values, **kwargs)

        lang.prepare_inputs_for_generation = _patched

    def predict(self, image: Image.Image, task: str, *, max_new_tokens: int = 1024, num_beams: int = 3) -> str:
        image = image.convert("RGB")
        inputs = self.processor(text=task, images=image, return_tensors="pt").to(self.device, self.dtype)
        with torch.inference_mode():
            output_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=max_new_tokens,
                early_stopping=False,
                do_sample=False,
                num_beams=num_beams,
            )
        decoded = self.processor.batch_decode(output_ids, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(decoded, task=task, image_size=(image.width, image.height))
        result = parsed.get(task, decoded)
        return result if isinstance(result, str) else str(result)

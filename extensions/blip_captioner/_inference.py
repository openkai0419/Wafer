from __future__ import annotations

from pathlib import Path

import torch
from PIL import Image
from transformers import BlipForConditionalGeneration, BlipProcessor

from wafer.utils.logs import AppLogger


class BlipInference:
    def __init__(self, model_dir: Path):
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.dtype = torch.float16 if self.device.type == "cuda" else torch.float32

        if self.device.type == "cpu":
            AppLogger.warning("BLIP running on CPU. Inference will be significantly slower. Install CUDA-enabled PyTorch for GPU acceleration")

        self.processor = BlipProcessor.from_pretrained(str(model_dir))
        self.model = BlipForConditionalGeneration.from_pretrained(str(model_dir), torch_dtype=self.dtype, use_safetensors=True).to(self.device)
        self.model.eval()

        AppLogger.info(f"BLIP engine loaded: device={self.device}, dtype={self.dtype}")

    def predict(self, image: Image.Image) -> str:
        image = image.convert("RGB")
        inputs = self.processor(images=image, return_tensors="pt").to(self.device, self.dtype)
        with torch.inference_mode():
            output_ids = self.model.generate(**inputs, max_length=50, num_beams=3)
        caption = self.processor.decode(output_ids[0], skip_special_tokens=True)
        return caption.strip()

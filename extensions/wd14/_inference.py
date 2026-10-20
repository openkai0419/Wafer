import os
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from wafer.core.logs import AppLogger

from ._models import CATEGORIES, NAMED_CATEGORIES, TaggerSpec, load_tags


def _preload_cuda_libs():
    if sys.platform != "win32":
        return
    try:
        ort.preload_dlls(cuda=True, cudnn=True, msvc=True)
    except Exception as e:
        AppLogger.debug(f"_preload_cuda_libs failed: {e}")
    cuda_path = os.environ.get("CUDA_PATH", "")
    if cuda_path:
        cuda_bin = Path(cuda_path) / "bin"
        if cuda_bin.is_dir() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(cuda_bin))
            if str(cuda_bin) not in os.environ.get("PATH", ""):
                os.environ["PATH"] = str(cuda_bin) + os.pathsep + os.environ.get("PATH", "")


_preload_cuda_libs()


RESAMPLE = {"bicubic": Image.BICUBIC, "bilinear": Image.BILINEAR, "lanczos": Image.LANCZOS}
GPU_PROVIDERS = ("CUDAExecutionProvider", "ROCmExecutionProvider", "CoreMLExecutionProvider", "DmlExecutionProvider")


class TaggerInference:
    def __init__(self, spec: TaggerSpec):
        self.spec = spec
        available = ort.get_available_providers()
        providers = [p for p in available if p != "TensorrtExecutionProvider"]
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self.session = ort.InferenceSession(str(spec.model_path), options, providers=providers)

        model_input = self.session.get_inputs()[0]
        self.input_name = model_input.name
        self.input_dtype = np.float16 if model_input.type == "tensor(float16)" else np.float32
        self.channels_first = model_input.shape[1] == 3
        static_size = model_input.shape[2] if self.channels_first else model_input.shape[1]
        self.input_size = spec.size or (static_size if isinstance(static_size, int) else None)
        if not self.input_size:
            raise ValueError(f"Tagger '{spec.name}' has a dynamic input size. Set \"size\" in tagger.json")
        self.output_name = spec.output or self.session.get_outputs()[0].name

        self.tag_names, self.tag_categories = load_tags(spec)
        self.category_indices = {c: np.flatnonzero(np.array(self.tag_categories) == c) for c in CATEGORIES}

        active = self.session.get_providers()
        AppLogger.info(f"Tagger '{spec.name}' loaded: {len(self.tag_names)} tags, input {self.input_name} {'NCHW' if self.channels_first else 'NHWC'} {self.input_size}px, provider {active[0]}")
        if not any(p in active for p in GPU_PROVIDERS):
            AppLogger.warning(f"Tagger running on CPU only ({active}). Inference will be significantly slower")

    def preprocess(self, image: Image.Image) -> np.ndarray:
        spec = self.spec
        image = image.convert("RGBA")
        bg = Image.new("RGBA", image.size, "WHITE")
        bg.paste(image, mask=image)
        image = bg.convert("RGB")

        size = self.input_size
        resample = RESAMPLE[spec.resample]
        if spec.pad is None:
            scale = size / max(image.size)
            w, h = (max(spec.multiple_of, int(side * scale) // spec.multiple_of * spec.multiple_of) for side in image.size)
            image = image.resize((w, h), resample)
        else:
            w, h = image.size
            side = max(w, h)
            canvas = Image.new("RGB", (side, side), spec.pad)
            canvas.paste(image, ((side - w) // 2, (side - h) // 2))
            image = canvas if side == size else canvas.resize((size, size), resample)

        arr = np.asarray(image, dtype=np.float32)
        if spec.channels == "BGR":
            arr = arr[:, :, ::-1]
        if spec.mean is not None:
            arr = (arr / 255.0 - np.array(spec.mean, dtype=np.float32)) / np.array(spec.std, dtype=np.float32)
        if self.channels_first:
            arr = arr.transpose(2, 0, 1)
        return np.ascontiguousarray(arr[np.newaxis], dtype=self.input_dtype)

    def predict(self, image: Image.Image, general_threshold: float, character_threshold: float) -> dict[str, dict[str, float]]:
        scores = self.session.run([self.output_name], {self.input_name: self.preprocess(image)})[0][0].astype(np.float32)
        if scores.min() < 0.0 or scores.max() > 1.0:
            scores = 1.0 / (1.0 + np.exp(-np.clip(scores, -30.0, 30.0)))

        result = {}
        for category, indices in self.category_indices.items():
            if category == "rating":
                threshold = 0.0
            elif category in NAMED_CATEGORIES:
                threshold = character_threshold
            else:
                threshold = general_threshold
            picked = indices[scores[indices] >= threshold]
            picked = picked[np.argsort(-scores[picked])]
            result[category] = {self.tag_names[i]: float(scores[i]) for i in picked}
        return result

import csv
import os
import sys
from pathlib import Path

import numpy as np
import onnxruntime as ort
from PIL import Image

from wafer.utils.logs import AppLogger


def _add_nvidia_dll_paths():
    if sys.platform != 'win32' or not hasattr(os, 'add_dll_directory'):
        return
    try:
        nvidia_dir = Path(ort.__file__).parent.parent / 'nvidia'
        if not nvidia_dir.exists():
            return
        for bin_dir in nvidia_dir.rglob('bin'):
            if bin_dir.is_dir():
                bin_str = str(bin_dir)
                if bin_str not in os.environ.get('PATH', ''):
                    os.environ['PATH'] = bin_str + os.pathsep + os.environ.get('PATH', '')
                os.add_dll_directory(bin_str)
    except Exception as e:
        AppLogger.debug(f'_add_nvidia_dll_paths failed: {e}')


_add_nvidia_dll_paths()


class WD14Inference:
    def __init__(self, model_dir: Path):
        model_path = model_dir / 'model.onnx'
        tags_path = model_dir / 'selected_tags.csv'

        available = ort.get_available_providers()
        providers = [p for p in available if p != 'TensorrtExecutionProvider']
        AppLogger.debug(f"WD14 available providers: {providers}")
        self.session = ort.InferenceSession(str(model_path), providers=providers)

        _, self.input_height, _, _ = self.session.get_inputs()[0].shape
        self.input_name = self.session.get_inputs()[0].name
        self.output_name = self.session.get_outputs()[0].name
        AppLogger.debug(
            f"WD14 input size: {self.input_height}, "
            f"input_name: {self.input_name}, output_name: {self.output_name}"
        )

        active = self.session.get_providers()
        gpu_providers = ('CUDAExecutionProvider', 'ROCmExecutionProvider', 'CoreMLExecutionProvider')
        if not any(p in active for p in gpu_providers):
            AppLogger.warning(f"WD14 running on CPU only ({active}). Inference will be significantly slower")

        with open(tags_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            self.tag_names = []
            self.tag_categories = []
            for row in reader:
                self.tag_names.append(row['name'])
                self.tag_categories.append(int(row['category']))

        AppLogger.debug(f"WD14 loaded {len(self.tag_names)} tags")

    @staticmethod
    def _preprocess(image: Image.Image, size: int) -> np.ndarray:
        image = image.convert('RGBA')
        bg = Image.new('RGBA', image.size, 'WHITE')
        bg.paste(image, mask=image)
        image = bg.convert('RGB')

        w, h = image.size
        max_dim = max(w, h, size)
        canvas = Image.new('RGB', (max_dim, max_dim), (255, 255, 255))
        canvas.paste(image, ((max_dim - w) // 2, (max_dim - h) // 2))
        if max_dim != size:
            canvas = canvas.resize((size, size), Image.LANCZOS)

        arr = np.array(canvas, dtype=np.float32)[:, :, ::-1]
        return np.expand_dims(arr, axis=0)

    def predict(self, image: Image.Image, general_threshold: float = 0.053, character_threshold: float = 0.6) -> dict:
        tensor = self._preprocess(image, self.input_height)
        confidents = self.session.run([self.output_name], {self.input_name: tensor})[0][0]

        ratings = {}
        general_tags = {}
        character_tags = {}

        for name, category, conf in zip(self.tag_names, self.tag_categories, confidents):
            if category == 9:
                ratings[name] = float(conf)
            elif category == 4 and conf >= character_threshold:
                character_tags[name] = float(conf)
            elif conf >= general_threshold:
                general_tags[name] = float(conf)

        general_tags = dict(sorted(general_tags.items(), key=lambda x: x[1], reverse=True))
        character_tags = dict(sorted(character_tags.items(), key=lambda x: x[1], reverse=True))
        ratings = dict(sorted(ratings.items(), key=lambda x: x[1], reverse=True))

        return {
            'ratings': ratings,
            'general': general_tags,
            'character': character_tags,
        }

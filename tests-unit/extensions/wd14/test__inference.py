from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

pytest.importorskip("onnxruntime")

from extensions.wd14._inference import TaggerInference
from extensions.wd14._models import CATEGORIES, TaggerSpec


def make_engine(input_size=8, channels_first=False, input_dtype=np.float32, scores=None, **spec_fields):
    spec = TaggerSpec(name="test", model_path=Path("model.onnx"), tags_path=Path("tags.csv"), **spec_fields)
    engine = TaggerInference.__new__(TaggerInference)
    engine.spec = spec
    engine.input_size = input_size
    engine.channels_first = channels_first
    engine.input_dtype = input_dtype
    engine.input_name = "input"
    engine.output_name = "output"
    engine.tag_names = ["general", "explicit", "1girl", "solo", "miku", "vocaloid", "someone", "highres"]
    engine.tag_categories = ["rating", "rating", "general", "general", "character", "copyright", "artist", "meta"]
    engine.category_indices = {c: np.flatnonzero(np.array(engine.tag_categories) == c) for c in CATEGORIES}
    engine.session = MagicMock()
    engine.session.run.return_value = [np.array([scores], dtype=np.float32)]
    return engine


class TestPreprocess:
    def test_wd_default_is_nhwc_bgr_raw_with_white_pad(self):
        engine = make_engine()
        image = Image.new("RGB", (8, 4), (10, 20, 30))
        arr = engine.preprocess(image)
        assert arr.shape == (1, 8, 8, 3)
        assert arr.dtype == np.float32
        assert arr[0, 4, 4].tolist() == [30.0, 20.0, 10.0]
        assert arr[0, 0, 0].tolist() == [255.0, 255.0, 255.0]

    def test_nchw_rgb_normalized_with_black_pad(self):
        engine = make_engine(channels_first=True, channels="RGB", mean=(0.5, 0.5, 0.5), std=(0.5, 0.5, 0.5), pad=(0, 0, 0))
        arr = engine.preprocess(Image.new("RGB", (4, 8), (255, 0, 255)))
        assert arr.shape == (1, 3, 8, 8)
        assert arr[0, :, 4, 4].tolist() == [1.0, -1.0, 1.0]
        assert arr[0, :, 0, 0].tolist() == [-1.0, -1.0, -1.0]

    def test_resizes_to_input_size(self):
        engine = make_engine(input_size=16)
        assert engine.preprocess(Image.new("RGB", (40, 20))).shape == (1, 16, 16, 3)

    def test_transparent_pixels_become_white(self):
        engine = make_engine()
        arr = engine.preprocess(Image.new("RGBA", (8, 8), (0, 0, 0, 0)))
        assert arr.min() == 255.0

    def test_no_pad_keeps_aspect_on_patch_multiple(self):
        engine = make_engine(input_size=64, channels_first=True, pad=None, multiple_of=16)
        assert engine.preprocess(Image.new("RGB", (100, 30))).shape == (1, 3, 16, 64)

    def test_float16_input(self):
        engine = make_engine(input_dtype=np.float16)
        assert engine.preprocess(Image.new("RGB", (8, 8))).dtype == np.float16


class TestPredict:
    def test_probabilities_are_split_by_category_and_threshold(self):
        engine = make_engine(scores=[0.7, 0.2, 0.9, 0.3, 0.8, 0.6, 0.85, 0.5])
        result = engine.predict(Image.new("RGB", (8, 8)), general_threshold=0.4, character_threshold=0.7)
        assert result["rating"] == {"general": pytest.approx(0.7), "explicit": pytest.approx(0.2)}
        assert result["general"] == {"1girl": pytest.approx(0.9)}
        assert result["character"] == {"miku": pytest.approx(0.8)}
        assert result["copyright"] == {}
        assert result["artist"] == {"someone": pytest.approx(0.85)}
        assert result["meta"] == {"highres": pytest.approx(0.5)}

    def test_sorted_by_score(self):
        engine = make_engine(scores=[0.7, 0.2, 0.5, 0.9, 0.0, 0.0, 0.0, 0.0])
        result = engine.predict(Image.new("RGB", (8, 8)), general_threshold=0.1, character_threshold=0.7)
        assert list(result["general"]) == ["solo", "1girl"]

    def test_logits_get_sigmoid(self):
        engine = make_engine(scores=[2.0, -2.0, 3.0, -3.0, 0.0, -9.0, -9.0, -9.0])
        result = engine.predict(Image.new("RGB", (8, 8)), general_threshold=0.5, character_threshold=0.4)
        assert result["general"] == {"1girl": pytest.approx(1 / (1 + np.exp(-3.0)))}
        assert result["character"] == {"miku": pytest.approx(0.5)}
        assert result["rating"]["general"] == pytest.approx(1 / (1 + np.exp(-2.0)))

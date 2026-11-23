from unittest.mock import MagicMock

import pytest
from PIL import Image

pytest.importorskip("torch")

from extensions.florence._inference import FlorenceInference


def test_predict_batch_strips_padding():
    inference = FlorenceInference.__new__(FlorenceInference)
    inference.device = "cpu"
    inference.dtype = None
    inference.processor = MagicMock()
    inference.processor.tokenizer.pad_token = "<pad>"
    inference.processor.batch_decode.return_value = ["</s><s>a cat</s><pad><pad>", "</s><s>a dog on grass</s>"]
    inference.processor.post_process_generation.side_effect = lambda text, task, image_size: {task: text}
    inference.model = MagicMock()
    images = [Image.new("RGB", (8, 8)), Image.new("RGB", (8, 8))]

    texts = inference.predict_batch(images, "<CAPTION>")

    assert texts == ["</s><s>a cat</s>", "</s><s>a dog on grass</s>"]
    assert inference.processor.call_args.kwargs["text"] == ["<CAPTION>"] * 2
    inference.model.generate.assert_called_once()


def test_predict_delegates_to_predict_batch():
    inference = FlorenceInference.__new__(FlorenceInference)
    image = Image.new("RGB", (8, 8))
    inference.predict_batch = MagicMock(return_value=["a cat"])

    assert inference.predict(image, "<CAPTION>", max_new_tokens=5, num_beams=2) == "a cat"
    inference.predict_batch.assert_called_once_with([image], "<CAPTION>", max_new_tokens=5, num_beams=2)

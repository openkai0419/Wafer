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

import numpy as np
import pytest
from PIL import Image

from extensions.image.loader import ImageFileLoader


@pytest.fixture()
def plugin():
    return ImageFileLoader()


@pytest.fixture()
def rgb_png(tmp_path):
    p = tmp_path / "rgb.png"
    Image.new("RGB", (80, 60), (255, 0, 0)).save(str(p))
    return str(p)


class TestMetadata:
    def test_name(self):
        assert ImageFileLoader.NAME == "image"

    def test_extensions(self):
        expected = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
        assert ImageFileLoader.EXTENSIONS == expected

    def test_priority(self):
        assert ImageFileLoader.PRIORITY == 100


class TestLoad:
    def test_fullsize(self, plugin, rgb_png):
        arr = plugin.load(rgb_png)
        assert arr is not None
        assert isinstance(arr, np.ndarray)
        assert arr.shape == (60, 80, 3)

    def test_with_size(self, plugin, rgb_png):
        arr = plugin.load(rgb_png, size=40)
        assert arr is not None
        assert isinstance(arr, np.ndarray)

    def test_nonexistent_returns_none(self, plugin, tmp_path):
        result = plugin.load(str(tmp_path / "nonexistent.png"))
        assert result is None

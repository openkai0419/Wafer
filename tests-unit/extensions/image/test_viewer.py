from unittest.mock import patch

import pytest
from PIL import Image
from PySide6 import QtGui

from extensions.image.viewer import ImageViewerPlugin


@pytest.fixture()
def plugin():
    return ImageViewerPlugin()


@pytest.fixture()
def rgb_png(tmp_path):
    p = tmp_path / "rgb.png"
    Image.new("RGB", (80, 60), (255, 0, 0)).save(str(p))
    return str(p)


class TestMetadata:
    def test_name(self):
        assert ImageViewerPlugin.NAME == "image"

    def test_extensions(self):
        expected = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
        assert ImageViewerPlugin.EXTENSIONS == expected

    def test_priority(self):
        assert ImageViewerPlugin.PRIORITY == 100


class TestLoadContent:
    def test_returns_fullsize_image(self, plugin, rgb_png):
        img = plugin.load_content(rgb_png)
        assert img is not None
        assert isinstance(img, QtGui.QImage)
        assert img.width() == 80
        assert img.height() == 60

    def test_nonexistent_returns_none(self, plugin):
        result = plugin.load_content("/no/such/file.png")
        assert result is None

    def test_delegates_to_loader_without_size(self, plugin, rgb_png):
        with patch("extensions.image.viewer.load_image") as mock:
            mock.return_value = None
            plugin.load_content(rgb_png)
            mock.assert_called_once_with(rgb_png)

from unittest.mock import patch

import pytest
from PIL import Image
from PySide6 import QtCore

from extensions.image.grid import ImageGridPlugin


@pytest.fixture()
def plugin():
    return ImageGridPlugin()


@pytest.fixture()
def rgb_png(tmp_path):
    p = tmp_path / 'rgb.png'
    Image.new('RGB', (80, 60), (255, 0, 0)).save(str(p))
    return str(p)


class TestMetadata:
    def test_name(self):
        assert ImageGridPlugin.NAME == 'image'

    def test_extensions(self):
        expected = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
        assert ImageGridPlugin.EXTENSIONS == expected

    def test_priority(self):
        assert ImageGridPlugin.PRIORITY == 100


class TestLoad:
    def test_fullsize(self, plugin, rgb_png):
        img = plugin.load(rgb_png)
        assert img is not None
        assert img.width() == 80
        assert img.height() == 60

    def test_with_size(self, plugin, rgb_png):
        size = QtCore.QSize(40, 30)
        img = plugin.load(rgb_png, size)
        assert img is not None
        assert img.width() == 40
        assert img.height() == 30

    def test_delegates_to_loader(self, plugin, rgb_png):
        with patch('extensions.image.grid.load_image') as mock:
            mock.return_value = None
            size = QtCore.QSize(40, 30)
            plugin.load(rgb_png, size)
            mock.assert_called_once_with(rgb_png, size)

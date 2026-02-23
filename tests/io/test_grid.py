import py_compile
import pytest
from PIL import Image

from source.io.grid.handler import grid_handler
from source.io.grid.base import BaseGridPlugin
from source.io.grid.image import ImageGridPlugin


def test_compile_base():
    py_compile.compile('source/io/grid/base.py')


def test_compile_image():
    py_compile.compile('source/io/grid/image.py')


def test_compile_handler():
    py_compile.compile('source/io/grid/handler.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseGridPlugin()


def test_image_plugin_registered():
    assert 'image' in grid_handler.registry.names()


def test_resolve_jpg():
    assert grid_handler.registry.resolve('photo.jpg') is ImageGridPlugin


def test_resolve_unknown_extension():
    assert grid_handler.registry.resolve('file.xyz') is None


def test_image_plugin_load(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    from PySide6 import QtCore
    size = QtCore.QSize(50, 50)
    plugin = ImageGridPlugin()
    result = plugin.load(str(img_path), size)
    assert result is not None
    assert not result.isNull()


def test_image_plugin_load_no_size(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    plugin = ImageGridPlugin()
    result = plugin.load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_grid_load_function(tmp_path):
    img_path = tmp_path / 'test.jpg'
    Image.new('RGB', (50, 50)).save(str(img_path))
    result = grid_handler.load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_grid_load_fallback_for_unknown_extension(tmp_path):
    img_path = tmp_path / 'test.bmp'
    Image.new('RGB', (50, 50)).save(str(img_path), format='BMP')
    result = grid_handler.load(str(img_path))
    assert result is not None


def test_image_plugin_load_nonexistent():
    plugin = ImageGridPlugin()
    result = plugin.load('nonexistent.png')
    assert result is None


def test_image_widget_class_is_none():
    assert ImageGridPlugin.WIDGET_CLASS is None


def test_has_widget_image():
    assert not grid_handler.has_widget('photo.jpg')


def test_has_widget_unknown():
    assert not grid_handler.has_widget('file.xyz')


def test_render_does_nothing_without_widget_plugin():
    grid_handler.render('photo.jpg', None)

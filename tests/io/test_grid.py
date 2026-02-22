import py_compile
import pytest
from PIL import Image

from source.io.grid import grid_registry, load as grid_load
from source.io.grid.base import BaseGridPlugin
from source.io.grid.image import ImageGridPlugin
from source.io.grid.fallback import FallbackGridPlugin


def test_compile_base():
    py_compile.compile('source/io/grid/base.py')


def test_compile_image():
    py_compile.compile('source/io/grid/image.py')


def test_compile_fallback():
    py_compile.compile('source/io/grid/fallback.py')


def test_compile_init():
    py_compile.compile('source/io/grid/__init__.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseGridPlugin()


def test_image_plugin_registered():
    assert 'image' in grid_registry.names()


def test_fallback_plugin_registered():
    assert 'fallback' in grid_registry.names()


def test_image_higher_priority_than_fallback():
    assert ImageGridPlugin.PRIORITY > FallbackGridPlugin.PRIORITY


def test_resolve_jpg():
    assert grid_registry.resolve('photo.jpg') is ImageGridPlugin


def test_resolve_unknown_extension():
    assert grid_registry.resolve('file.xyz') is FallbackGridPlugin


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
    result = grid_load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_image_plugin_load_nonexistent():
    plugin = ImageGridPlugin()
    result = plugin.load('nonexistent.png')
    assert result is None


def test_image_create_cell_widget():
    plugin = ImageGridPlugin()
    assert plugin.create_cell_widget() is None


def test_fallback_create_cell_widget():
    plugin = FallbackGridPlugin()
    assert plugin.create_cell_widget() is None

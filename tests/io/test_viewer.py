import py_compile
import pytest

from source.io.viewer import viewer_registry, resolve_viewer
from source.io.viewer.base import BaseViewerPlugin
from source.io.viewer.image import ImageViewerPlugin


def test_compile_base():
    py_compile.compile('source/io/viewer/base.py')


def test_compile_image():
    py_compile.compile('source/io/viewer/image.py')


def test_compile_init():
    py_compile.compile('source/io/viewer/__init__.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseViewerPlugin()


def test_image_plugin_registered():
    assert 'image' in viewer_registry.names()


def test_resolve_jpg():
    assert resolve_viewer('photo.jpg') is ImageViewerPlugin


def test_resolve_png():
    assert resolve_viewer('image.png') is ImageViewerPlugin


def test_resolve_unknown():
    assert resolve_viewer('file.xyz') is None


def test_image_plugin_priority():
    assert ImageViewerPlugin.PRIORITY == 100


def test_image_plugin_extensions():
    assert '.jpg' in ImageViewerPlugin.EXTENSIONS
    assert '.png' in ImageViewerPlugin.EXTENSIONS
    assert '.gif' in ImageViewerPlugin.EXTENSIONS

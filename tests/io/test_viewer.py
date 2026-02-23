import py_compile
import pytest
from PIL import Image

from source.io.viewer.handler import viewer_handler
from source.io.viewer.base import BaseViewerPlugin
from source.io.viewer.image import ImageViewerPlugin


def test_compile_base():
    py_compile.compile('source/io/viewer/base.py')


def test_compile_image():
    py_compile.compile('source/io/viewer/image.py')


def test_compile_handler():
    py_compile.compile('source/io/viewer/handler.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseViewerPlugin()


def test_image_plugin_registered():
    assert 'image' in viewer_handler.registry.names()


def test_resolve_jpg():
    assert viewer_handler.resolve('photo.jpg') is ImageViewerPlugin


def test_resolve_png():
    assert viewer_handler.resolve('image.png') is ImageViewerPlugin


def test_resolve_unknown():
    assert viewer_handler.resolve('file.xyz') is None


def test_image_plugin_priority():
    assert ImageViewerPlugin.PRIORITY == 100


def test_image_plugin_extensions():
    assert '.jpg' in ImageViewerPlugin.EXTENSIONS
    assert '.png' in ImageViewerPlugin.EXTENSIONS
    assert '.gif' in ImageViewerPlugin.EXTENSIONS


def test_image_plugin_no_custom_widget():
    plugin = ImageViewerPlugin()
    assert plugin.create_widget() is None


def test_image_plugin_load_content(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (50, 50)).save(str(img_path))
    plugin = ImageViewerPlugin()
    result = plugin.load_content(str(img_path))
    assert result is not None


def test_load_content_function(tmp_path):
    img_path = tmp_path / 'test.jpg'
    Image.new('RGB', (50, 50)).save(str(img_path))
    result = viewer_handler.load_content(str(img_path))
    assert result is not None


def test_create_default_widget(qtbot):
    from source.image_viewer.shower.image_viewer import ImageViewerWidget
    widget = viewer_handler.create_default_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, ImageViewerWidget)


def test_create_widget_for_image(qtbot):
    from source.image_viewer.shower.image_viewer import ImageViewerWidget
    widget = viewer_handler.create_widget('photo.jpg')
    qtbot.addWidget(widget)
    assert isinstance(widget, ImageViewerWidget)


def test_create_widget_for_unknown(qtbot):
    from source.image_viewer.shower.image_viewer import ImageViewerWidget
    widget = viewer_handler.create_widget('file.xyz')
    qtbot.addWidget(widget)
    assert isinstance(widget, ImageViewerWidget)

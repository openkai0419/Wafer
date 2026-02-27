import py_compile
import pytest
from PIL import Image

from source.io.viewer.handler import viewer_handler
from source.io.viewer.base import BaseViewerPlugin


def _get_image_plugin():
    return viewer_handler.registry.get('image')


def test_compile_base():
    py_compile.compile('source/io/viewer/base.py')


def test_compile_handler():
    py_compile.compile('source/io/viewer/handler.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseViewerPlugin()


def test_image_plugin_registered():
    assert 'image' in viewer_handler.registry.names()


def test_resolve_jpg():
    plugin_cls = _get_image_plugin()
    assert viewer_handler.resolve('photo.jpg') is plugin_cls


def test_resolve_png():
    plugin_cls = _get_image_plugin()
    assert viewer_handler.resolve('image.png') is plugin_cls


def test_resolve_unknown():
    assert viewer_handler.resolve('file.xyz') is None


def test_image_plugin_priority():
    plugin_cls = _get_image_plugin()
    assert plugin_cls.PRIORITY == 100


def test_image_plugin_extensions():
    plugin_cls = _get_image_plugin()
    assert '.jpg' in plugin_cls.EXTENSIONS
    assert '.png' in plugin_cls.EXTENSIONS
    assert '.gif' in plugin_cls.EXTENSIONS


def test_image_plugin_widget_class_is_none():
    plugin_cls = _get_image_plugin()
    assert plugin_cls.WIDGET_CLASS is None


def test_has_widget_image():
    assert not viewer_handler.has_widget('photo.jpg')


def test_has_widget_unknown():
    assert not viewer_handler.has_widget('file.xyz')


def test_widget_classes_empty():
    assert viewer_handler.widget_classes() == {}


def test_render_does_nothing_without_widget_plugin():
    viewer_handler.render('photo.jpg', None)


def test_image_plugin_load_content(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (50, 50)).save(str(img_path))
    plugin = _get_image_plugin()()
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

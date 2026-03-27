import py_compile
import pytest
from PIL import Image

from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.viewer.base import BaseViewerPlugin, ImageViewerPlugin, WidgetViewerPlugin


def _get_image_plugin():
    return viewer_resolver.registry.get('image')


def test_compile_base():
    py_compile.compile('wafer/plugin/viewer/base.py')


def test_compile_handler():
    py_compile.compile('wafer/plugin/viewer/handler.py')


def test_image_viewer_plugin_is_abstract():
    with pytest.raises(TypeError):
        ImageViewerPlugin()


def test_image_plugin_registered():
    assert 'image' in viewer_resolver.registry.names()


def test_resolve_jpg():
    plugin_cls = _get_image_plugin()
    assert viewer_resolver.resolve('photo.jpg') is plugin_cls


def test_resolve_png():
    plugin_cls = _get_image_plugin()
    assert viewer_resolver.resolve('image.png') is plugin_cls


def test_resolve_unknown():
    from wafer.builtins.viewer import DefaultViewerPlugin
    assert viewer_resolver.resolve('file.xyz') is DefaultViewerPlugin


def test_image_plugin_priority():
    plugin_cls = _get_image_plugin()
    assert plugin_cls.PRIORITY == 100


def test_image_plugin_extensions():
    plugin_cls = _get_image_plugin()
    assert '.jpg' in plugin_cls.EXTENSIONS
    assert '.png' in plugin_cls.EXTENSIONS
    assert '.gif' in plugin_cls.EXTENSIONS


def test_image_plugin_is_image_viewer_plugin():
    plugin_cls = _get_image_plugin()
    assert issubclass(plugin_cls, ImageViewerPlugin)
    assert not issubclass(plugin_cls, WidgetViewerPlugin)


def test_is_widget_plugin_image():
    assert not viewer_resolver.is_widget_plugin('photo.jpg')


def test_is_widget_plugin_unknown():
    assert not viewer_resolver.is_widget_plugin('file.xyz')


def test_viewer_plugins_includes_registered():
    plugins = viewer_resolver.viewer_plugins()
    for name, inst in plugins.items():
        assert isinstance(name, str)
        assert isinstance(inst, WidgetViewerPlugin)
        assert inst.widget is not None


def test_render_does_nothing_without_widget_plugin():
    viewer_resolver.render('photo.jpg')


def test_image_plugin_load_content_returns_image(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (50, 50)).save(str(img_path))
    plugin = _get_image_plugin()()
    result = plugin.load_content(str(img_path))
    from PySide6 import QtGui
    assert isinstance(result, QtGui.QImage)


def test_load_content_function(tmp_path):
    img_path = tmp_path / 'test.jpg'
    Image.new('RGB', (50, 50)).save(str(img_path))
    result = viewer_resolver.load_content(str(img_path))
    assert result is not None


def test_create_default_widget(qtbot):
    from wafer.app.viewer.preview.image_viewer import ImageDisplayWidget
    widget = viewer_resolver.create_default_widget()
    qtbot.addWidget(widget)


def test_widget_viewer_plugin_activate_default():
    class Stub(WidgetViewerPlugin):
        NAME = 'stub'
        EXTENSIONS = ('.stub',)
        PRIORITY = 1
    plugin = Stub()
    plugin.activate()
    plugin.deactivate()


def test_set_autoplay_default_returns_false():
    class Stub(WidgetViewerPlugin):
        NAME = 'stub_ap'
        EXTENSIONS = ('.stub',)
        PRIORITY = 1
    plugin = Stub()
    assert plugin.set_autoplay(lambda: None) is False


def test_set_autoplay_none_returns_false():
    class Stub(WidgetViewerPlugin):
        NAME = 'stub_ap2'
        EXTENSIONS = ('.stub',)
        PRIORITY = 1
    plugin = Stub()
    assert plugin.set_autoplay(None) is False


def test_activate_deactivate_via_resolver():
    viewer_resolver.activate('__nonexistent__')
    viewer_resolver.deactivate('__nonexistent__')

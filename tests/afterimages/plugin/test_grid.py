import py_compile
import pytest
from PIL import Image

from afterimages.plugin.grid.handler import grid_resolver
from afterimages.plugin.grid.base import BaseGridPlugin


def _get_image_plugin():
    return grid_resolver.registry.get('image')


def test_compile_base():
    py_compile.compile('afterimages/plugin/grid/base.py')


def test_compile_handler():
    py_compile.compile('afterimages/plugin/grid/handler.py')


def test_base_is_abstract():
    with pytest.raises(TypeError):
        BaseGridPlugin()


def test_image_plugin_registered():
    assert 'image' in grid_resolver.registry.names()


def test_resolve_jpg():
    ImageGridPlugin = _get_image_plugin()
    assert grid_resolver.registry.resolve('photo.jpg') is ImageGridPlugin


def test_resolve_unknown_extension():
    assert grid_resolver.registry.resolve('file.xyz') is None


def test_image_plugin_load(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    from PySide6 import QtCore
    size = QtCore.QSize(50, 50)
    plugin = _get_image_plugin()()
    result = plugin.load(str(img_path), size)
    assert result is not None
    assert not result.isNull()


def test_image_plugin_load_no_size(tmp_path):
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 200)).save(str(img_path))
    plugin = _get_image_plugin()()
    result = plugin.load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_grid_load_function(tmp_path):
    img_path = tmp_path / 'test.jpg'
    Image.new('RGB', (50, 50)).save(str(img_path))
    result = grid_resolver.load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_grid_load_fallback_for_unknown_extension(tmp_path):
    img_path = tmp_path / 'test.bmp'
    Image.new('RGB', (50, 50)).save(str(img_path), format='BMP')
    result = grid_resolver.load(str(img_path))
    assert result is not None


def test_image_plugin_load_nonexistent():
    plugin = _get_image_plugin()()
    result = plugin.load('nonexistent.png')
    assert result is None


def test_image_widget_class_is_none():
    assert _get_image_plugin().WIDGET_CLASS is None


def test_has_widget_image():
    assert not grid_resolver.has_widget('photo.jpg')


def test_has_widget_unknown():
    assert not grid_resolver.has_widget('file.xyz')


def test_render_does_nothing_without_widget_plugin():
    grid_resolver.render('photo.jpg', None)


def test_base_release_default_is_noop():
    class _ConcretePlugin(BaseGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
        def load(self, path, size=None):
            return None
    _ConcretePlugin().release(None)


def test_base_select_default_is_noop():
    class _ConcretePlugin(BaseGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
        def load(self, path, size=None):
            return None
    _ConcretePlugin().select(None, '/test.mp4')


def test_base_deselect_default_is_noop():
    class _ConcretePlugin(BaseGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
        def load(self, path, size=None):
            return None
    _ConcretePlugin().deselect(None)


def test_grid_resolver_release_delegates_to_plugin():
    from unittest.mock import MagicMock, patch
    mock_plugin = MagicMock()
    mock_plugin.WIDGET_CLASS = object
    with patch.object(grid_resolver.registry, 'get', return_value=mock_plugin):
        widget = MagicMock()
        grid_resolver.release('video', widget)
        mock_plugin().release.assert_called_once_with(widget)


def test_grid_resolver_release_unknown_plugin():
    grid_resolver.release('nonexistent', None)


def test_grid_resolver_select_delegates_to_plugin():
    from unittest.mock import MagicMock, patch
    mock_plugin = MagicMock()
    mock_plugin.WIDGET_CLASS = object
    with patch.object(grid_resolver.registry, 'get', return_value=mock_plugin):
        widget = MagicMock()
        grid_resolver.select('video', widget, '/test.mp4')
        mock_plugin().select.assert_called_once_with(widget, '/test.mp4')


def test_grid_resolver_select_unknown_plugin():
    grid_resolver.select('nonexistent', None, '/test.mp4')


def test_grid_resolver_deselect_delegates_to_plugin():
    from unittest.mock import MagicMock, patch
    mock_plugin = MagicMock()
    mock_plugin.WIDGET_CLASS = object
    with patch.object(grid_resolver.registry, 'get', return_value=mock_plugin):
        widget = MagicMock()
        grid_resolver.deselect('video', widget)
        mock_plugin().deselect.assert_called_once_with(widget)


def test_grid_resolver_deselect_unknown_plugin():
    grid_resolver.deselect('nonexistent', None)


def test_load_thumbnail_api(tmp_path):
    from afterimages.plugin import load_thumbnail
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 100)).save(str(img_path))
    from PySide6 import QtCore
    result = load_thumbnail(str(img_path), QtCore.QSize(50, 50))
    assert result is not None
    assert not result.isNull()


def test_load_thumbnail_api_returns_none_for_missing():
    from afterimages.plugin import load_thumbnail
    result = load_thumbnail('/nonexistent/file.xyz')
    assert result is None

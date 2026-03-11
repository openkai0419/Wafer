import py_compile
import pytest
from unittest.mock import MagicMock
from PIL import Image

from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import BaseGridPlugin, ImageGridPlugin, WidgetGridPlugin


def _get_image_plugin():
    return grid_resolver.registry.get('image')


def test_compile_base():
    py_compile.compile('wafer/plugin/grid/base.py')


def test_compile_handler():
    py_compile.compile('wafer/plugin/grid/handler.py')


def test_image_grid_plugin_is_abstract():
    with pytest.raises(TypeError):
        ImageGridPlugin()


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


def test_image_plugin_is_image_grid_plugin():
    assert issubclass(_get_image_plugin(), ImageGridPlugin)
    assert not issubclass(_get_image_plugin(), WidgetGridPlugin)


def test_is_widget_plugin_image():
    assert not grid_resolver.is_widget_plugin('photo.jpg')


def test_resolve_instance_returns_plugin():
    instance = grid_resolver.resolve_instance('photo.jpg')
    assert isinstance(instance, ImageGridPlugin)


def test_resolve_instance_unknown_returns_none():
    assert grid_resolver.resolve_instance('file.xyz') is None


def test_is_widget_plugin_unknown():
    assert not grid_resolver.is_widget_plugin('file.xyz')


def test_base_lifecycle_defaults_are_noop():
    class _ConcretePlugin(WidgetGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
    p = _ConcretePlugin()
    p.release(None)
    p.select(None)
    p.deselect(None)
    p.appear(None)
    p.disappear(None)
    p.on_thumb_loaded(None, None)


def test_widget_grid_plugin_render_default_noop():
    from unittest.mock import MagicMock
    class _ConcretePlugin(WidgetGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
    p = _ConcretePlugin()
    job = MagicMock()
    p.render(job)


class TestImageGridPluginRender:

    @pytest.fixture(autouse=True)
    def _qapp(self):
        from PySide6 import QtWidgets
        app = QtWidgets.QApplication.instance()
        if app is None:
            app = QtWidgets.QApplication([])
        return app

    def test_render_loads_and_invokes(self, tmp_path):
        import time
        from PySide6 import QtCore, QtWidgets
        from wafer.core.qt.dispatcher import Dispatcher, CancelToken
        from wafer.plugin.grid.cell_job import CellJob
        img_path = tmp_path / 'test.png'
        Image.new('RGB', (100, 100)).save(str(img_path))
        plugin = _get_image_plugin()()
        dispatcher = Dispatcher()

        class FakeCache:
            def __init__(self):
                self.store = {}
            def get(self, key, default=None):
                return self.store.get(key, default)
            def get_if_sufficient(self, key, size, default=None):
                image = self.store.get(key)
                if image is not None and image.width() >= size.width() and image.height() >= size.height():
                    return image
                return default
            def __setitem__(self, key, value):
                self.store[key] = value

        cache = FakeCache()
        result_widget = MagicMock()
        job = CellJob(
            index=0, path=str(img_path), size=QtCore.QSize(50, 50),
            image_cache=cache, cancel=CancelToken(), dispatcher=dispatcher,
            widget_lookup=lambda i: result_widget,
        )
        plugin.render(job)
        app = QtWidgets.QApplication.instance()
        deadline = time.monotonic() + 3.0
        while not result_widget.set_image.called and time.monotonic() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        result_widget.set_image.assert_called_once()
        assert str(img_path) in cache.store

    def test_render_uses_cache_hit(self, tmp_path):
        import time
        from PySide6 import QtCore, QtWidgets
        from wafer.core.qt.dispatcher import Dispatcher, CancelToken
        from wafer.plugin.grid.cell_job import CellJob
        plugin = _get_image_plugin()()
        dispatcher = Dispatcher()
        sentinel = MagicMock()

        class FakeCache:
            def get(self, key, default=None):
                return sentinel
            def get_if_sufficient(self, key, size, default=None):
                return sentinel
            def __setitem__(self, key, value):
                pass

        result_widget = MagicMock()
        job = CellJob(
            index=0, path='/fake.png', size=QtCore.QSize(50, 50),
            image_cache=FakeCache(), cancel=CancelToken(), dispatcher=dispatcher,
            widget_lookup=lambda i: result_widget,
        )
        plugin.render(job)
        app = QtWidgets.QApplication.instance()
        deadline = time.monotonic() + 3.0
        while not result_widget.set_image.called and time.monotonic() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        result_widget.set_image.assert_called_once_with(sentinel, '/fake.png')

    def test_render_skips_when_cancelled(self, tmp_path):
        import time
        from PySide6 import QtCore, QtWidgets
        from wafer.core.qt.dispatcher import Dispatcher, CancelToken
        from wafer.plugin.grid.cell_job import CellJob
        img_path = tmp_path / 'test.png'
        Image.new('RGB', (100, 100)).save(str(img_path))
        plugin = _get_image_plugin()()
        dispatcher = Dispatcher()

        class FakeCache:
            def get(self, key, default=None):
                return None
            def get_if_sufficient(self, key, size, default=None):
                return None
            def __setitem__(self, key, value):
                pass

        cancel = CancelToken()
        cancel.set()
        result_widget = MagicMock()
        job = CellJob(
            index=0, path=str(img_path), size=QtCore.QSize(50, 50),
            image_cache=FakeCache(), cancel=cancel, dispatcher=dispatcher,
            widget_lookup=lambda i: result_widget,
        )
        plugin.render(job)
        time.sleep(0.1)
        QtWidgets.QApplication.instance().processEvents()
        result_widget.set_image.assert_not_called()

    def test_render_shows_error_placeholder_on_load_failure(self):
        import time
        from PySide6 import QtCore, QtGui, QtWidgets
        from wafer.core.qt.dispatcher import Dispatcher, CancelToken
        from wafer.plugin.grid.cell_job import CellJob
        plugin = _get_image_plugin()()
        dispatcher = Dispatcher()

        class FakeCache:
            def __init__(self):
                self.store = {}
            def get(self, key, default=None):
                return self.store.get(key, default)
            def get_if_sufficient(self, key, size, default=None):
                image = self.store.get(key)
                if image is not None and image.width() >= size.width() and image.height() >= size.height():
                    return image
                return default
            def __setitem__(self, key, value):
                self.store[key] = value

        cache = FakeCache()
        result_widget = MagicMock()
        job = CellJob(
            index=0, path='/nonexistent_file.png', size=QtCore.QSize(50, 50),
            image_cache=cache, cancel=CancelToken(), dispatcher=dispatcher,
            widget_lookup=lambda i: result_widget,
        )
        plugin.render(job)
        app = QtWidgets.QApplication.instance()
        deadline = time.monotonic() + 3.0
        while not result_widget.set_image.called and time.monotonic() < deadline:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
            time.sleep(0.01)
        result_widget.set_image.assert_called_once()
        img = result_widget.set_image.call_args[0][0]
        assert isinstance(img, QtGui.QImage)
        assert not img.isNull()
        assert '/nonexistent_file.png' in cache.store


def test_require_thumbnail_default_false():
    class _ConcretePlugin(WidgetGridPlugin):
        NAME = 'noop'
        EXTENSIONS = ('.noop',)
    assert _ConcretePlugin.REQUIRE_THUMBNAIL is False


def test_load_thumbnail_api(tmp_path):
    from wafer.plugin import load_thumbnail
    img_path = tmp_path / 'test.png'
    Image.new('RGB', (100, 100)).save(str(img_path))
    from PySide6 import QtCore
    result = load_thumbnail(str(img_path), QtCore.QSize(50, 50))
    assert result is not None
    assert not result.isNull()


def test_load_thumbnail_api_returns_none_for_missing():
    from wafer.plugin import load_thumbnail
    result = load_thumbnail('/nonexistent/file.xyz')
    assert result is None


def test_resolve_falls_through_when_can_handle_false():
    from wafer.plugin.registry import PluginRegistry, BasePlugin
    from wafer.plugin.grid.base import ImageGridPlugin as _ImageBase

    class Strict(_ImageBase):
        NAME = 'strict'
        EXTENSIONS = ('.test',)
        PRIORITY = 200

        @classmethod
        def can_handle(cls, path):
            return False

        def load(self, path, size=None):
            return None

    class Fallback(_ImageBase):
        NAME = 'fallback'
        EXTENSIONS = ('.test',)
        PRIORITY = 100

        def load(self, path, size=None):
            return None

    reg = PluginRegistry()
    reg.register(Strict)
    reg.register(Fallback)
    assert reg.resolve('file.test') is Fallback


def test_resolve_returns_first_can_handle_true():
    from wafer.plugin.registry import PluginRegistry, BasePlugin
    from wafer.plugin.grid.base import ImageGridPlugin as _ImageBase

    class High(_ImageBase):
        NAME = 'hi'
        EXTENSIONS = ('.test',)
        PRIORITY = 200

        def load(self, path, size=None):
            return None

    class Low(_ImageBase):
        NAME = 'lo'
        EXTENSIONS = ('.test',)
        PRIORITY = 100

        def load(self, path, size=None):
            return None

    reg = PluginRegistry()
    reg.register(High)
    reg.register(Low)
    assert reg.resolve('file.test') is High


def test_resolve_static_png_to_image(tmp_path):
    from PIL import Image as PILImage
    png_path = tmp_path / 'static.png'
    PILImage.new('RGB', (10, 10)).save(str(png_path))
    plugin = grid_resolver.resolve(str(png_path))
    assert plugin is not None
    assert plugin.NAME in ('animated', 'image')


def test_resolve_animated_gif_to_animated(tmp_path):
    from PIL import Image as PILImage
    gif_path = tmp_path / 'anim.gif'
    frames = [PILImage.new('RGB', (10, 10), c) for c in ['red', 'blue']]
    frames[0].save(str(gif_path), save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = grid_resolver.resolve(str(gif_path))
    assert plugin is not None
    assert plugin.NAME == 'animated'


def test_resolve_chain_fallback_static_gif_to_image(tmp_path):
    from PIL import Image as PILImage
    gif_path = tmp_path / 'static.gif'
    PILImage.new('RGB', (10, 10)).save(str(gif_path))
    chain = grid_resolver.resolve_chain(str(gif_path))
    names = [p.NAME for p in chain]
    assert 'animated' in names
    assert 'image' in names


class TestWidgetNotifier:

    def _make_notifier(self):
        from unittest.mock import MagicMock
        from wafer.plugin.grid.handler import WidgetNotifier

        mock = MagicMock()

        class _StubPlugin(WidgetGridPlugin):
            NAME = 'stub'
            EXTENSIONS = ('.stub',)
            WIDGET_CLASS = object
            render = mock.render
            release = mock.release
            appear = mock.appear
            disappear = mock.disappear
            select = mock.select
            deselect = mock.deselect
            on_thumb_loaded = mock.on_thumb_loaded

        registry = MagicMock()
        registry.instance.return_value = _StubPlugin()
        notifier = WidgetNotifier(registry)
        return notifier, mock

    def test_bind_registers_name(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        notifier.bind(0, 'video')
        assert notifier.plugin_name(0) == 'video'
        plugin.render.assert_not_called()

    def test_unbind_visible_calls_disappear_and_release(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        widget.isVisible.return_value = True
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.unbind(0, widget)
        plugin.disappear.assert_called_once_with(widget)
        plugin.release.assert_called_once_with(widget)
        assert notifier.plugin_name(0) is None

    def test_unbind_hidden_skips_disappear(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        widget.isVisible.return_value = False
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.unbind(0, widget)
        plugin.disappear.assert_not_called()
        plugin.release.assert_called_once_with(widget)

    def test_unbind_unknown_index_is_noop(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        notifier.unbind(99, MagicMock())
        plugin.release.assert_not_called()

    def test_appear_delegates(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.appear(0, widget)
        plugin.appear.assert_called_once_with(widget)

    def test_disappear_delegates(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.disappear(0, widget)
        plugin.disappear.assert_called_once_with(widget)

    def test_select_delegates(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.select(0, widget)
        plugin.select.assert_called_once_with(widget)

    def test_deselect_delegates(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.deselect(0, widget)
        plugin.deselect.assert_called_once_with(widget)

    def test_select_unknown_index_is_noop(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        notifier.select(99, MagicMock())
        plugin.select.assert_not_called()

    def test_clear_removes_all(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        notifier.bind(0, 'video')
        notifier.bind(1, 'video')
        notifier.clear()
        assert notifier.plugin_name(0) is None
        assert notifier.plugin_name(1) is None

    def test_require_thumbnail_returns_flag(self):
        from unittest.mock import MagicMock
        from wafer.plugin.grid.handler import WidgetNotifier

        class _ThumbPlugin(WidgetGridPlugin):
            NAME = 'thumb'
            EXTENSIONS = ('.thumb',)
            REQUIRE_THUMBNAIL = True

        registry = MagicMock()
        registry.instance.return_value = _ThumbPlugin()
        notifier = WidgetNotifier(registry)
        assert notifier.require_thumbnail('thumb') is True

    def test_require_thumbnail_false_by_default(self):
        notifier, _ = self._make_notifier()
        assert notifier.require_thumbnail('stub') is False

    def test_on_thumb_loaded_delegates(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        image = MagicMock()
        notifier.bind(0, 'video')
        plugin.reset_mock()
        notifier.on_thumb_loaded(0, widget, image)
        plugin.on_thumb_loaded.assert_called_once_with(widget, image)

    def test_on_thumb_loaded_unknown_index_is_noop(self):
        from unittest.mock import MagicMock
        notifier, plugin = self._make_notifier()
        notifier.on_thumb_loaded(99, MagicMock(), MagicMock())
        plugin.on_thumb_loaded.assert_not_called()


def test_registry_instance_cached():
    instance = grid_resolver.registry.instance('image')
    assert instance is not None
    assert instance is grid_resolver.registry.instance('image')
    assert isinstance(instance, ImageGridPlugin)


def test_resolve_instance():
    instance = grid_resolver.registry.resolve_instance('photo.jpg')
    assert instance is not None
    assert isinstance(instance, ImageGridPlugin)


def test_resolve_instance_unknown():
    assert grid_resolver.registry.resolve_instance('file.xyz') is None


def test_resolve_chain_returns_priority_sorted():
    from wafer.plugin.registry import PluginRegistry
    from wafer.plugin.grid.base import ImageGridPlugin as _ImageBase

    class High(_ImageBase):
        NAME = 'hi'
        EXTENSIONS = ('.test',)
        PRIORITY = 200
        def load(self, path, size=None):
            return None

    class Low(_ImageBase):
        NAME = 'lo'
        EXTENSIONS = ('.test',)
        PRIORITY = 100
        def load(self, path, size=None):
            return None

    reg = PluginRegistry()
    reg.register(High)
    reg.register(Low)
    chain = reg.resolve_chain('file.test')
    assert chain == [High, Low]


def test_resolve_chain_empty_for_unknown():
    assert grid_resolver.registry.resolve_chain('file.xyz') == []


def test_resolve_chain_uses_cache():
    from wafer.plugin.registry import PluginRegistry
    from wafer.plugin.grid.base import ImageGridPlugin as _ImageBase

    class Stub(_ImageBase):
        NAME = 'stub_cache'
        EXTENSIONS = ('.cachetest',)
        PRIORITY = 100
        def load(self, path, size=None):
            return None

    reg = PluginRegistry()
    reg.register(Stub)
    first = reg.resolve_chain('a.cachetest')
    second = reg.resolve_chain('b.cachetest')
    assert first is second


def test_resolve_chain_cache_cleared_on_register():
    from wafer.plugin.registry import PluginRegistry
    from wafer.plugin.grid.base import ImageGridPlugin as _ImageBase

    class A(_ImageBase):
        NAME = 'a_clear'
        EXTENSIONS = ('.clr',)
        PRIORITY = 100
        def load(self, path, size=None):
            return None

    class B(_ImageBase):
        NAME = 'b_clear'
        EXTENSIONS = ('.clr',)
        PRIORITY = 200
        def load(self, path, size=None):
            return None

    reg = PluginRegistry()
    reg.register(A)
    first = reg.resolve_chain('x.clr')
    assert first == [A]
    reg.register(B)
    second = reg.resolve_chain('x.clr')
    assert second == [B, A]
    assert first is not second


def test_resolve_chain_includes_all_candidates():
    chain = grid_resolver.registry.resolve_chain('test.gif')
    names = [p.NAME for p in chain]
    assert 'animated' in names
    assert 'image' in names
    assert names.index('animated') < names.index('image')

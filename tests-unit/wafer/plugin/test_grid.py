import numpy as np
import py_compile
import pytest
from unittest.mock import MagicMock
from PIL import Image

from wafer.plugin.grid.handler import grid_resolver
from wafer.plugin.grid.base import BaseGridPlugin, WidgetGridPlugin
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.plugin.imageloader.base import BaseImageLoader


def _get_image_loader():
    return image_loader_resolver.registry.get("image")


def test_compile_base():
    py_compile.compile("wafer/plugin/grid/base.py")


def test_compile_handler():
    py_compile.compile("wafer/plugin/grid/handler.py")


def test_image_loader_registered():
    assert "image" in image_loader_resolver.registry.names()


def test_resolve_jpg_imageloader():
    loader_cls = _get_image_loader()
    assert image_loader_resolver.registry.resolve("photo.jpg") is loader_cls


def test_resolve_unknown_extension_imageloader():
    from wafer.builtins.imageloader import SystemImageLoader

    assert image_loader_resolver.registry.resolve("file.xyz") is SystemImageLoader


def test_image_loader_load(tmp_path):
    img_path = tmp_path / "test.png"
    Image.new("RGB", (100, 200)).save(str(img_path))
    plugin = _get_image_loader()()
    result = plugin.load(str(img_path), size=50)
    assert result is not None
    assert isinstance(result, np.ndarray)


def test_image_loader_load_no_size(tmp_path):
    img_path = tmp_path / "test.png"
    Image.new("RGB", (100, 200)).save(str(img_path))
    plugin = _get_image_loader()()
    result = plugin.load(str(img_path))
    assert result is not None
    assert isinstance(result, np.ndarray)


def test_grid_load_function(tmp_path):
    img_path = tmp_path / "test.jpg"
    Image.new("RGB", (50, 50)).save(str(img_path))
    result = grid_resolver.load(str(img_path))
    assert result is not None
    assert not result.isNull()


def test_grid_load_fallback_for_unknown_extension(tmp_path):
    img_path = tmp_path / "test.bmp"
    Image.new("RGB", (50, 50)).save(str(img_path), format="BMP")
    result = grid_resolver.load(str(img_path))
    assert result is not None


def test_image_loader_load_nonexistent():
    plugin = _get_image_loader()()
    result = plugin.load("nonexistent.png")
    assert result is None


def test_image_loader_is_base_image_loader():
    assert issubclass(_get_image_loader(), BaseImageLoader)
    assert not issubclass(_get_image_loader(), WidgetGridPlugin)


def test_is_widget_plugin_image():
    assert not grid_resolver.is_widget_plugin("photo.jpg")


def test_imageloader_resolve_instance():
    instance = image_loader_resolver.registry.resolve_instance("photo.jpg")
    assert instance is not None
    assert isinstance(instance, BaseImageLoader)


def test_imageloader_resolve_instance_unknown():
    from wafer.builtins.imageloader import SystemImageLoader

    instance = image_loader_resolver.registry.resolve_instance("file.xyz")
    assert isinstance(instance, SystemImageLoader)


def test_is_widget_plugin_unknown():
    assert not grid_resolver.is_widget_plugin("file.xyz")


def test_base_lifecycle_defaults_are_noop():
    class _ConcretePlugin(WidgetGridPlugin):
        NAME = "noop"
        EXTENSIONS = (".noop",)

    p = _ConcretePlugin()
    p.release(None)
    p.select(None)
    p.deselect(None)
    p.appear(None)
    p.disappear(None)
    p.on_thumb_loaded(None, None)


def test_widget_grid_plugin_render_default_noop():
    from unittest.mock import MagicMock
    from PySide6 import QtCore

    class _ConcretePlugin(WidgetGridPlugin):
        NAME = "noop"
        EXTENSIONS = (".noop",)

    p = _ConcretePlugin()
    widget = MagicMock()
    p.render(widget, "/test.noop", QtCore.QSize(50, 50))


def test_require_thumbnail_default_false():
    class _ConcretePlugin(WidgetGridPlugin):
        NAME = "noop"
        EXTENSIONS = (".noop",)

    assert _ConcretePlugin.REQUIRE_THUMBNAIL is False


def test_load_thumbnail_api(tmp_path):
    from wafer.plugin.grid.handler import load_thumbnail

    img_path = tmp_path / "test.png"
    Image.new("RGB", (100, 100)).save(str(img_path))
    from PySide6 import QtCore

    result = load_thumbnail(str(img_path), QtCore.QSize(50, 50))
    assert result is not None
    assert not result.isNull()


def test_load_thumbnail_api_returns_none_for_missing():
    from wafer.plugin.grid.handler import load_thumbnail

    result = load_thumbnail("/nonexistent/file.xyz")
    assert result is None


def test_resolve_falls_through_when_can_handle_false():
    from wafer.plugin.registry import FilePluginRegistry

    class Strict(BaseGridPlugin):
        NAME = "strict"
        EXTENSIONS = (".test",)
        PRIORITY = 200

        @classmethod
        def can_handle(cls, path):
            return False

    class Fallback(BaseGridPlugin):
        NAME = "fallback"
        EXTENSIONS = (".test",)
        PRIORITY = 100

    reg = FilePluginRegistry()
    reg.register(Strict)
    reg.register(Fallback)
    assert reg.resolve("file.test") is Fallback


def test_resolve_returns_first_can_handle_true():
    from wafer.plugin.registry import FilePluginRegistry

    class High(BaseGridPlugin):
        NAME = "hi"
        EXTENSIONS = (".test",)
        PRIORITY = 200

    class Low(BaseGridPlugin):
        NAME = "lo"
        EXTENSIONS = (".test",)
        PRIORITY = 100

    reg = FilePluginRegistry()
    reg.register(High)
    reg.register(Low)
    assert reg.resolve("file.test") is High


def test_resolve_static_png_to_imageloader(tmp_path):
    from PIL import Image as PILImage

    png_path = tmp_path / "static.png"
    PILImage.new("RGB", (10, 10)).save(str(png_path))
    plugin_cls = image_loader_resolver.resolve(str(png_path))
    assert plugin_cls is not None
    assert plugin_cls.NAME == "image"


def test_resolve_animated_gif_to_animated(tmp_path):
    from PIL import Image as PILImage

    gif_path = tmp_path / "anim.gif"
    frames = [PILImage.new("RGB", (10, 10), c) for c in ["red", "blue"]]
    frames[0].save(str(gif_path), save_all=True, append_images=frames[1:], duration=100, loop=0)
    plugin = grid_resolver.resolve(str(gif_path))
    assert plugin is not None
    assert plugin.NAME == "animated"


def test_merged_chain_gif_includes_animated_and_image():
    chain = grid_resolver.resolve_merged_chain("test.gif")
    names = [cls.NAME for cls, kind in chain]
    assert "animated" in names
    assert "image" in names


class TestWidgetNotifier:
    def _make_notifier(self):
        from unittest.mock import MagicMock
        from wafer.plugin.grid.handler import WidgetNotifier

        mock = MagicMock()

        class _StubPlugin(WidgetGridPlugin):
            NAME = "stub"
            EXTENSIONS = (".stub",)
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
        notifier.bind(0, "video")
        assert notifier.plugin_name(0) == "video"
        plugin.render.assert_not_called()

    def test_unbind_visible_calls_disappear_and_release(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        widget.isVisible.return_value = True
        notifier.bind(0, "video")
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
        notifier.bind(0, "video")
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
        notifier.bind(0, "video")
        plugin.reset_mock()
        notifier.appear(0, widget)
        plugin.appear.assert_called_once_with(widget)

    def test_disappear_delegates(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, "video")
        plugin.reset_mock()
        notifier.disappear(0, widget)
        plugin.disappear.assert_called_once_with(widget)

    def test_select_delegates(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, "video")
        plugin.reset_mock()
        notifier.select(0, widget)
        plugin.select.assert_called_once_with(widget)

    def test_deselect_delegates(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        notifier.bind(0, "video")
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
        notifier.bind(0, "video")
        notifier.bind(1, "video")
        notifier.clear()
        assert notifier.plugin_name(0) is None
        assert notifier.plugin_name(1) is None

    def test_require_thumbnail_returns_flag(self):
        from unittest.mock import MagicMock
        from wafer.plugin.grid.handler import WidgetNotifier

        class _ThumbPlugin(WidgetGridPlugin):
            NAME = "thumb"
            EXTENSIONS = (".thumb",)
            REQUIRE_THUMBNAIL = True

        registry = MagicMock()
        registry.instance.return_value = _ThumbPlugin()
        notifier = WidgetNotifier(registry)
        assert notifier.require_thumbnail("thumb") is True

    def test_require_thumbnail_false_by_default(self):
        notifier, _ = self._make_notifier()
        assert notifier.require_thumbnail("stub") is False

    def test_on_thumb_loaded_delegates(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        widget = MagicMock()
        image = MagicMock()
        notifier.bind(0, "video")
        plugin.reset_mock()
        notifier.on_thumb_loaded(0, widget, image)
        plugin.on_thumb_loaded.assert_called_once_with(widget, image)

    def test_on_thumb_loaded_unknown_index_is_noop(self):
        from unittest.mock import MagicMock

        notifier, plugin = self._make_notifier()
        notifier.on_thumb_loaded(99, MagicMock(), MagicMock())
        plugin.on_thumb_loaded.assert_not_called()


def test_imageloader_instance_cached():
    instance = image_loader_resolver.registry.instance("image")
    assert instance is not None
    assert instance is image_loader_resolver.registry.instance("image")
    assert isinstance(instance, BaseImageLoader)


def test_imageloader_resolve_instance_by_path():
    instance = image_loader_resolver.registry.resolve_instance("photo.jpg")
    assert instance is not None
    assert isinstance(instance, BaseImageLoader)


def test_imageloader_resolve_instance_unknown():
    from wafer.builtins.imageloader import SystemImageLoader

    assert isinstance(image_loader_resolver.registry.resolve_instance("file.xyz"), SystemImageLoader)


def test_resolve_chain_returns_priority_sorted():
    from wafer.plugin.registry import FilePluginRegistry

    class High(BaseGridPlugin):
        NAME = "hi"
        EXTENSIONS = (".test",)
        PRIORITY = 200

    class Low(BaseGridPlugin):
        NAME = "lo"
        EXTENSIONS = (".test",)
        PRIORITY = 100

    reg = FilePluginRegistry()
    reg.register(High)
    reg.register(Low)
    chain = reg.resolve_chain("file.test")
    assert chain == [High, Low]


def test_imageloader_chain_for_unknown():
    from wafer.builtins.imageloader import SystemImageLoader

    chain = image_loader_resolver.registry.resolve_chain("file.xyz")
    assert chain[-1] is SystemImageLoader
    assert image_loader_resolver.registry.resolve("file.xyz") is SystemImageLoader


def test_imageloader_delegated_resolution_fallback_uses_materialized_path():
    from wafer.plugin.imageloader.handler import ImageLoaderResolver

    class Delegating(BaseImageLoader):
        NAME = "_delegating_loader"
        EXTENSIONS = ()
        PRIORITY = 300

        @classmethod
        def can_handle(cls, path):
            return path == "virtual.png"

        def resolve(self, path, context):
            if not self.can_handle(path):
                return None
            return context.resolve_new("materialized.png")

    class First(BaseImageLoader):
        NAME = "_first_loader"
        EXTENSIONS = (".png",)
        PRIORITY = 100

        def __init__(self):
            self.calls = []

        def load_qimage(self, path, size=None):
            self.calls.append(path)
            return None

    class Fallback(BaseImageLoader):
        NAME = "_fallback_loader"
        EXTENSIONS = ()
        PRIORITY = -100

        def __init__(self):
            self.calls = []

        def load_qimage(self, path, size=None):
            self.calls.append(path)
            return None

    resolver = ImageLoaderResolver()
    for plugin_cls in (Delegating, First, Fallback):
        resolver.registry.register(plugin_cls)

    resolver.load_qimage("virtual.png")

    first = resolver.registry.instance(First.NAME)
    fallback = resolver.registry.instance(Fallback.NAME)
    assert first.calls == ["materialized.png"]
    assert fallback.calls == ["materialized.png"]


def test_resolve_chain_uses_cache():
    from wafer.plugin.registry import FilePluginRegistry

    class Stub(BaseGridPlugin):
        NAME = "stub_cache"
        EXTENSIONS = (".cachetest",)
        PRIORITY = 100

    reg = FilePluginRegistry()
    reg.register(Stub)
    first = reg.resolve_chain("a.cachetest")
    second = reg.resolve_chain("b.cachetest")
    assert first is second


def test_resolve_chain_cache_cleared_on_register():
    from wafer.plugin.registry import FilePluginRegistry

    class A(BaseGridPlugin):
        NAME = "a_clear"
        EXTENSIONS = (".clr",)
        PRIORITY = 100

    class B(BaseGridPlugin):
        NAME = "b_clear"
        EXTENSIONS = (".clr",)
        PRIORITY = 200

    reg = FilePluginRegistry()
    reg.register(A)
    first = reg.resolve_chain("x.clr")
    assert first == [A]
    reg.register(B)
    second = reg.resolve_chain("x.clr")
    assert second == [B, A]
    assert first is not second


def test_merged_chain_includes_all_candidates():
    chain = grid_resolver.resolve_merged_chain("test.gif")
    names = [cls.NAME for cls, kind in chain]
    assert "animated" in names
    assert "image" in names
    assert names.index("animated") < names.index("image")


def test_all_classes_returns_name_cls_tuples():
    from wafer.plugin.registry import FilePluginRegistry

    class P1(BaseGridPlugin):
        NAME = "p1"
        EXTENSIONS = (".p1",)

    class P2(BaseGridPlugin):
        NAME = "p2"
        EXTENSIONS = (".p2",)

    reg = FilePluginRegistry()
    reg.register(P1)
    reg.register(P2)
    result = reg.all_classes()
    assert ("p1", P1) in result
    assert ("p2", P2) in result
    assert len(result) == 2


def test_all_classes_empty_registry():
    from wafer.plugin.registry import FilePluginRegistry

    reg = FilePluginRegistry()
    assert reg.all_classes() == []

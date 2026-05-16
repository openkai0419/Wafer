import py_compile

from wafer.builtins.image_viewer.viewer import ImageViewer
from wafer.plugin import ViewerContext
from wafer.plugin.viewer.handler import viewer_resolver
from wafer.plugin.viewer.base import MultiWidgetViewerPlugin, WidgetViewerPlugin


def _context(path: str) -> ViewerContext:
    return ViewerContext(path=path, source=path, render_path=path)


def test_compile_base():
    py_compile.compile("wafer/plugin/viewer/base.py")


def test_compile_handler():
    py_compile.compile("wafer/plugin/viewer/handler.py")


def test_resolve_jpg():
    assert viewer_resolver.resolve("photo.jpg") is ImageViewer


def test_resolve_png():
    assert viewer_resolver.resolve("image.png") is ImageViewer


def test_resolve_unknown():
    assert viewer_resolver.resolve("file.xyz") is ImageViewer


def test_resolve_plan_uses_image_fallback_plugin():
    plan = viewer_resolver.resolve_plan("photo.jpg")
    assert plan.handler.NAME == ImageViewer.NAME
    assert plan.path == "photo.jpg"
    assert plan.resolved_path == "photo.jpg"


def test_resolve_plan_widget_plugin():
    class Stub(WidgetViewerPlugin):
        NAME = "_stub_widget_viewer"
        EXTENSIONS = (".stubviewer",)
        PRIORITY = 1

    viewer_resolver.registry.register(Stub)
    plan = viewer_resolver.resolve_plan("sample.stubviewer")
    assert plan.handler.NAME == Stub.NAME


def test_is_widget_plugin_image():
    assert viewer_resolver.is_widget_plugin("photo.jpg")


def test_is_widget_plugin_unknown():
    assert viewer_resolver.is_widget_plugin("file.xyz")


def test_viewer_plugins_includes_registered(qtbot):
    plugins = viewer_resolver.viewer_plugins()
    for name, inst in plugins.items():
        assert isinstance(name, str)
        assert isinstance(inst, WidgetViewerPlugin)
        assert inst.widget is not None


def test_render_uses_image_fallback_plugin(qtbot):
    viewer_resolver.render((_context("photo.jpg"),))


def test_render_passes_single_context_to_widget_plugin():
    class Stub(WidgetViewerPlugin):
        NAME = "_stub_single_render"
        EXTENSIONS = (".single_render",)
        PRIORITY = 1
        received = None

        def render(self, context):
            type(self).received = context

    first = _context("first.single_render")
    second = _context("second.single_render")
    viewer_resolver.registry.register(Stub)

    viewer_resolver.render((first, second), plugin_name=Stub.NAME)

    assert Stub.received == first


def test_render_passes_contexts_to_multi_widget_plugin():
    class Stub(MultiWidgetViewerPlugin):
        NAME = "_stub_multi_render"
        EXTENSIONS = (".multi_render",)
        PRIORITY = 1
        received = None

        def render_contexts(self, contexts):
            type(self).received = tuple(contexts)

    contexts = (_context("first.multi_render"), _context("second.multi_render"))
    viewer_resolver.registry.register(Stub)

    viewer_resolver.render(contexts, plugin_name=Stub.NAME)

    assert Stub.received == contexts


def test_widget_viewer_plugin_activate_default():
    class Stub(WidgetViewerPlugin):
        NAME = "stub"
        EXTENSIONS = (".stub",)
        PRIORITY = 1

    plugin = Stub()
    plugin.activate()
    plugin.deactivate()


def test_set_autoplay_default_returns_false():
    class Stub(WidgetViewerPlugin):
        NAME = "stub_ap"
        EXTENSIONS = (".stub",)
        PRIORITY = 1

    plugin = Stub()
    assert plugin.set_autoplay(lambda: None) is False


def test_set_autoplay_none_returns_false():
    class Stub(WidgetViewerPlugin):
        NAME = "stub_ap2"
        EXTENSIONS = (".stub",)
        PRIORITY = 1

    plugin = Stub()
    assert plugin.set_autoplay(None) is False


def test_multi_display_count_default_returns_single_item():
    class Stub(MultiWidgetViewerPlugin):
        NAME = "stub_count"
        EXTENSIONS = (".stub",)
        PRIORITY = 1

    plugin = Stub()
    assert plugin.display_count(0, ["a", "b"]) == 1


def test_activate_deactivate_via_resolver():
    viewer_resolver.activate("__nonexistent__")
    viewer_resolver.deactivate("__nonexistent__")

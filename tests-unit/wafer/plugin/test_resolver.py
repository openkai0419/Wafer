from wafer.core.files.render_target import RenderPlan, ResolveContext, SURFACE_VIEWER
from wafer.plugin.grid.base import WidgetGridPlugin
from wafer.plugin.grid.handler import GridResolver
from wafer.plugin.imageloader.base import BaseImageLoader
from wafer.plugin.imageloader.handler import ImageLoaderResolver
from wafer.plugin.viewer.base import WidgetViewerPlugin
from wafer.plugin.viewer.handler import ViewerResolver


class DemoViewer(WidgetViewerPlugin):
    NAME = "demo_viewer"
    EXTENSIONS = (".png",)


class BrokenViewer(WidgetViewerPlugin):
    NAME = "broken_viewer_resolve"
    EXTENSIONS = (".brokenviewer",)
    PRIORITY = 20

    def resolve(self, path: str, context: ResolveContext):
        raise RuntimeError("broken viewer resolve")


class FallbackViewer(WidgetViewerPlugin):
    NAME = "fallback_viewer_resolve"
    EXTENSIONS = (".brokenviewer",)
    PRIORITY = 10


class BrokenGrid(WidgetGridPlugin):
    NAME = "broken_grid_resolve"
    EXTENSIONS = (".brokengrid",)
    PRIORITY = 20

    def resolve(self, path: str, context: ResolveContext):
        raise RuntimeError("broken grid resolve")


class FallbackGrid(WidgetGridPlugin):
    NAME = "fallback_grid_resolve"
    EXTENSIONS = (".brokengrid",)
    PRIORITY = 10


class BrokenImageLoader(BaseImageLoader):
    NAME = "broken_image_loader_resolve"
    EXTENSIONS = (".brokenloader",)
    PRIORITY = 20

    def resolve(self, path: str, context: ResolveContext):
        raise RuntimeError("broken image loader resolve")


class FallbackImageLoader(BaseImageLoader):
    NAME = "fallback_image_loader_resolve"
    EXTENSIONS = (".brokenloader",)
    PRIORITY = 10


def test_resolve_context_preserves_original_path_when_resolving_new_path():
    def resolver(path: str, context: ResolveContext):
        return RenderPlan(source=context.source, path=context.path, resolved_path=path, handler=DemoViewer())

    context = ResolveContext.create("archive.zip::child.demo", surface=SURFACE_VIEWER, resolver=resolver)
    plan = context.resolve_new("materialized.png")

    assert plan is not None
    assert plan.path == "archive.zip::child.demo"
    assert plan.resolved_path == "materialized.png"
    assert plan.source == "archive.zip"


def test_resolve_context_stops_recursive_resolution():
    def resolver(path: str, context: ResolveContext):
        return context.resolve_new(path)

    context = ResolveContext.create("asset.demo", surface=SURFACE_VIEWER, resolver=resolver, max_depth=1)

    try:
        context.resolve_new("asset.png")
    except RecursionError as exc:
        assert "exceeded depth" in str(exc)
    else:
        raise AssertionError("recursive render plan resolution did not stop")


def test_viewer_resolver_skips_failed_resolve():
    resolver = ViewerResolver()
    resolver.registry.register(BrokenViewer)
    resolver.registry.register(FallbackViewer)

    plan = resolver.resolve_plan("sample.brokenviewer")

    assert isinstance(plan.handler, FallbackViewer)


def test_grid_resolver_skips_failed_resolve():
    resolver = GridResolver()
    resolver.registry.register(BrokenGrid)
    resolver.registry.register(FallbackGrid)

    plan = resolver.resolve_plan("sample.brokengrid")

    assert isinstance(plan.handler, FallbackGrid)


def test_image_loader_resolver_skips_failed_resolve():
    resolver = ImageLoaderResolver()
    resolver.registry.register(BrokenImageLoader)
    resolver.registry.register(FallbackImageLoader)

    plan = resolver.resolve_plan("sample.brokenloader")

    assert isinstance(plan.handler, FallbackImageLoader)

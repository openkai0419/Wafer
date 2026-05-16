from wafer.core.files.render_target import RenderPlan, ResolveContext, SURFACE_VIEWER
from wafer.plugin.viewer.base import WidgetViewerPlugin


class DemoViewer(WidgetViewerPlugin):
    NAME = "demo_viewer"
    EXTENSIONS = (".png",)


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

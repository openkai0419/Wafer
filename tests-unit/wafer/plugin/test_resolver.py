from wafer.core.files.render_target import RenderTarget, ResolveContext, TARGET_IMAGE, TARGET_WIDGET
from wafer.plugin.resolver.base import BaseResolverPlugin
from wafer.plugin.resolver.handler import ResolverRegistry
from wafer.utils.virtual_paths import build_virtual_path, register_owner_extension


def test_resolver_accepts_non_virtual_extension_path():
    class DemoResolver(BaseResolverPlugin):
        NAME = "demo_resolver"
        EXTENSIONS = (".demo",)

        def materialize(self, path: str, *, purpose: str) -> str:
            assert purpose == "viewer"
            return path + ".png"

    registry = ResolverRegistry()
    registry.registry.register(DemoResolver)

    def resolve_child(path: str, context: ResolveContext) -> RenderTarget:
        return RenderTarget(context.logical_path, path, TARGET_IMAGE)

    target = registry.resolve_target("sample.demo", purpose="viewer", context=ResolveContext("sample.demo"), resolve_child=resolve_child)

    assert target is not None
    assert target.logical_path == "sample.demo"
    assert target.render_path == "sample.demo.png"


def test_resolver_accepts_non_virtual_catch_all_path():
    class CatchAllResolver(BaseResolverPlugin):
        NAME = "catch_all_resolver"
        EXTENSIONS = ()

        @classmethod
        def can_handle(cls, path: str) -> bool:
            return path.endswith(".external")

        def materialize(self, path: str, *, purpose: str) -> str:
            return path.removesuffix(".external") + ".jpg"

    registry = ResolverRegistry()
    registry.registry.register(CatchAllResolver)

    def resolve_child(path: str, context: ResolveContext) -> RenderTarget:
        return RenderTarget(context.logical_path, path, TARGET_IMAGE)

    target = registry.resolve_target("asset.external", purpose="grid", context=ResolveContext("asset.external"), resolve_child=resolve_child)

    assert target is not None
    assert target.render_path == "asset.jpg"


def test_virtual_path_uses_owner_resolver():
    class PackResolver(BaseResolverPlugin):
        NAME = "pack_resolver"
        EXTENSIONS = (".pack",)
        OWNS_VIRTUAL_CHILDREN = True

        def materialize(self, path: str, *, purpose: str) -> str:
            return "materialized.png"

    register_owner_extension(".pack")
    registry = ResolverRegistry()
    registry.registry.register(PackResolver)
    logical = build_virtual_path("archive.pack", "child.png")

    def resolve_child(path: str, context: ResolveContext) -> RenderTarget:
        return RenderTarget(context.logical_path, path, TARGET_IMAGE)

    target = registry.resolve_target(logical, purpose="viewer", context=ResolveContext(logical), resolve_child=resolve_child)

    assert target is not None
    assert target.logical_path == logical
    assert target.render_path == "materialized.png"


def test_resolver_can_return_widget_target_directly():
    class WidgetResolver(BaseResolverPlugin):
        NAME = "widget_resolver"
        EXTENSIONS = (".remote",)

        def resolve_target(self, path: str, *, purpose: str, context: ResolveContext, resolve_child) -> RenderTarget | None:
            return RenderTarget(context.logical_path, path, TARGET_WIDGET, plugin_name="remote_widget")

    registry = ResolverRegistry()
    registry.registry.register(WidgetResolver)

    target = registry.resolve_target(
        "asset.remote",
        purpose="viewer",
        context=ResolveContext("asset.remote"),
        resolve_child=lambda path, context: RenderTarget(context.logical_path, path, TARGET_IMAGE),
    )

    assert target is not None
    assert target.kind == TARGET_WIDGET
    assert target.plugin_name == "remote_widget"
from ...core.files.render_target import RenderTarget, ResolveContext, TARGET_IMAGE, TARGET_WIDGET
from ...utils.virtual_paths import source_path
from ..registry import FilePluginRegistry
from .base import MultiWidgetViewerPlugin, WidgetViewerPlugin


class ViewerResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def resolve(self, path: str) -> type[WidgetViewerPlugin] | None:
        return self.registry.resolve(path)

    def resolve_target(self, path: str, context: ResolveContext | None = None) -> RenderTarget:
        context = context or ResolveContext(path)
        from ..resolver.handler import resolver_registry

        resolved = resolver_registry.resolve_target(
            path,
            purpose="viewer",
            context=context,
            resolve_child=self.resolve_target,
        )
        if resolved is not None:
            return resolved

        for plugin_cls in self.registry.resolve_chain(path):
            if not plugin_cls.can_handle(path):
                continue
            if issubclass(plugin_cls, WidgetViewerPlugin):
                return RenderTarget(
                    logical_path=context.logical_path,
                    render_path=path,
                    kind=TARGET_WIDGET,
                    plugin_name=plugin_cls.NAME,
                    source_path=source_path(context.logical_path),
                )
        return RenderTarget(
            logical_path=context.logical_path,
            render_path=path,
            kind=TARGET_IMAGE,
            source_path=source_path(context.logical_path),
        )

    def is_widget_plugin(self, path: str) -> bool:
        target = self.resolve_target(path)
        plugin_cls = self.registry.get(target.plugin_name) if target.plugin_name else None
        return target.kind == TARGET_WIDGET and plugin_cls is not None and issubclass(plugin_cls, WidgetViewerPlugin)

    def viewer_plugins(self) -> dict[str, WidgetViewerPlugin]:
        result = {}
        for p in self.registry.list_all():
            if issubclass(p, WidgetViewerPlugin) and p.WIDGET_CLASS is not None:
                inst = self.registry.instance(p.NAME)
                if isinstance(inst, WidgetViewerPlugin):
                    result[p.NAME] = inst
        return result

    def render(self, contexts, plugin_name: str | None = None):
        contexts = tuple(contexts or ())
        if not contexts:
            return
        instance = self.registry.instance(plugin_name) if plugin_name else self.registry.resolve_instance(contexts[0].path)
        if isinstance(instance, MultiWidgetViewerPlugin):
            instance.render_contexts(contexts)
        elif isinstance(instance, WidgetViewerPlugin):
            instance.render(contexts[0])

    def activate(self, name: str):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.activate()

    def deactivate(self, name: str):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.deactivate()


viewer_resolver = ViewerResolver()

from ...core.files.render_target import RenderPlan, ResolveContext, SURFACE_VIEWER
from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ..registry import FilePluginRegistry
from .base import MultiWidgetViewerPlugin, WidgetViewerPlugin


class ViewerResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def resolve(self, path: str) -> type[WidgetViewerPlugin] | None:
        return self.registry.resolve(path)

    @profiler.profile
    def resolve_plan(self, path: str, context: ResolveContext | None = None) -> RenderPlan[WidgetViewerPlugin]:
        context = context or ResolveContext.create(path, surface=SURFACE_VIEWER, resolver=self.resolve_plan)
        for plugin_cls in self.registry.resolve_chain(path):
            instance = self.registry.instance(plugin_cls.NAME)
            if not isinstance(instance, WidgetViewerPlugin):
                continue
            try:
                plan = instance.resolve(path, context)
            except Exception as exc:
                AppLogger.warning(f"[ViewerResolver] resolve failed: plugin={plugin_cls.NAME} path={path} error={type(exc).__name__}: {exc}", exc=exc)
                continue
            if isinstance(plan, RenderPlan) and isinstance(plan.handler, WidgetViewerPlugin):
                return plan
        raise LookupError(f"no viewer plugin resolved: {path}")

    def is_widget_plugin(self, path: str) -> bool:
        return isinstance(self.resolve_plan(path).handler, WidgetViewerPlugin)

    def viewer_plugins(self) -> dict[str, WidgetViewerPlugin]:
        result = {}
        for p in self.registry.list_all():
            if issubclass(p, WidgetViewerPlugin) and p.WIDGET_CLASS is not None:
                inst = self.registry.instance(p.NAME)
                if isinstance(inst, WidgetViewerPlugin):
                    result[p.NAME] = inst
        return result

    @profiler.profile
    def render(self, contexts, plugin_name: str | None = None):
        contexts = tuple(contexts or ())
        if not contexts:
            return
        instance = self.registry.instance(plugin_name) if plugin_name else self.resolve_plan(contexts[0].path).handler
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

from PySide6 import QtGui

from ...core.files.render_target import RenderTarget, ResolveContext, TARGET_IMAGE, TARGET_WIDGET
from ...utils.virtual_paths import is_virtual_path, source_path
from ..registry import DISPATCH_OWNER, FilePluginRegistry
from .base import BaseViewerPlugin, ImageViewerPlugin, WidgetViewerPlugin


class ViewerResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def create_default_widget(self, parent=None):
        from ...app.viewer.preview.image_viewer import ImageDisplayWidget

        return ImageDisplayWidget(parent)

    def resolve(self, path: str) -> type[BaseViewerPlugin] | None:
        return self.registry.resolve(path)

    def resolve_target(self, path: str, context: ResolveContext | None = None) -> RenderTarget:
        context = context or ResolveContext(path)
        if is_virtual_path(path):
            owner_cls = self.registry.resolve(path, DISPATCH_OWNER)
            owner = self.registry.instance(owner_cls.NAME) if owner_cls is not None else None
            resolver = getattr(owner, "resolve_target", None)
            if resolver is not None:
                target = resolver(path, self, context)
                if isinstance(target, RenderTarget):
                    return target

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
            if issubclass(plugin_cls, ImageViewerPlugin):
                return RenderTarget(
                    logical_path=context.logical_path,
                    render_path=path,
                    kind=TARGET_IMAGE,
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
        return target.kind == TARGET_WIDGET and isinstance(self.registry.instance(target.plugin_name), WidgetViewerPlugin)

    def viewer_plugins(self) -> dict[str, WidgetViewerPlugin]:
        result = {}
        for p in self.registry.list_all():
            if issubclass(p, WidgetViewerPlugin) and p.WIDGET_CLASS is not None:
                inst = self.registry.instance(p.NAME)
                if isinstance(inst, WidgetViewerPlugin):
                    result[p.NAME] = inst
        return result

    def load_content(self, path: str) -> QtGui.QImage | None:
        for plugin_cls in self.registry.resolve_chain(path):
            instance = self.registry.instance(plugin_cls.NAME)
            if isinstance(instance, ImageViewerPlugin):
                result = instance.load_content(path)
                if result is not None:
                    return result
        return None

    def render(self, path: str):
        instance = self.registry.resolve_instance(path)
        if isinstance(instance, WidgetViewerPlugin):
            instance.render(path)

    def activate(self, name: str):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.activate()

    def deactivate(self, name: str):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.deactivate()


viewer_resolver = ViewerResolver()

from PySide6 import QtGui

from ..registry import PluginRegistry
from .base import BaseViewerPlugin, ImageViewerPlugin, WidgetViewerPlugin


class ViewerResolver:

    def __init__(self):
        self.registry = PluginRegistry()

    def create_default_widget(self, parent=None):
        from ...app.viewer.preview.image_viewer import ImageDisplayWidget
        return ImageDisplayWidget(parent)

    def resolve(self, path: str) -> type[BaseViewerPlugin] | None:
        return self.registry.resolve(path)

    def is_widget_plugin(self, path: str) -> bool:
        return isinstance(self.registry.resolve_instance(path), WidgetViewerPlugin)

    def widget_classes(self) -> dict[str, type]:
        return {
            p.NAME: p.WIDGET_CLASS
            for p in self.registry.list_all()
            if issubclass(p, WidgetViewerPlugin) and p.WIDGET_CLASS is not None
        }

    def load_content(self, path: str) -> QtGui.QImage | None:
        for plugin_cls in self.registry.resolve_chain(path):
            instance = self.registry.instance(plugin_cls.NAME)
            if isinstance(instance, ImageViewerPlugin):
                result = instance.load_content(path)
                if result is not None:
                    return result
        return None

    def render(self, widget, path: str):
        instance = self.registry.resolve_instance(path)
        if isinstance(instance, WidgetViewerPlugin):
            instance.render(widget, path)

    def activate(self, name: str, widget):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.activate(widget)

    def deactivate(self, name: str, widget):
        instance = self.registry.instance(name)
        if isinstance(instance, WidgetViewerPlugin):
            instance.deactivate(widget)


viewer_resolver = ViewerResolver()

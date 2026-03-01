from PySide6 import QtGui

from ..registry import PluginRegistry
from .base import BaseViewerPlugin


class ViewerResolver:

    def __init__(self):
        self.registry = PluginRegistry()

    def create_default_widget(self, parent=None):
        from afterimages.app.viewer.preview.image_viewer import ImageDisplayWidget
        return ImageDisplayWidget(parent)

    def resolve(self, path: str) -> type[BaseViewerPlugin] | None:
        return self.registry.resolve(path)

    def has_widget(self, path: str) -> bool:
        plugin_cls = self.registry.resolve(path)
        return plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None

    def widget_classes(self) -> dict[str, type]:
        return {
            p.NAME: p.WIDGET_CLASS
            for p in self.registry.list_all()
            if p.WIDGET_CLASS is not None
        }

    def load_content(self, path: str) -> QtGui.QImage | None:
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is None:
            result = plugin_cls().load_content(path)
            if result is not None:
                return result
        from ..grid.handler import grid_resolver
        return grid_resolver.load(path)

    def render(self, path: str, widget):
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            plugin_cls().render(path, widget)


viewer_resolver = ViewerResolver()

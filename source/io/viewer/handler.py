from PySide6 import QtGui

from ...common.logs import AppLogger
from ..registry import PluginRegistry
from ..grid.handler import grid_handler
from .base import BaseViewerPlugin
from .image import ImageViewerPlugin


class ViewerHandler:

    def __init__(self, grid):
        self.registry = PluginRegistry()
        self._grid = grid

    def create_default_widget(self, parent=None):
        from ...image_viewer.shower.image_viewer import ImageViewerWidget
        return ImageViewerWidget(parent)

    def resolve(self, path: str) -> type[BaseViewerPlugin] | None:
        return self.registry.resolve(path)

    def create_widget(self, path: str, parent=None):
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None:
            widget = plugin_cls().create_widget(parent)
            if widget is not None:
                return widget
        return self.create_default_widget(parent)

    def load_content(self, path: str) -> QtGui.QImage | None:
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None:
            result = plugin_cls().load_content(path)
            if result is not None:
                return result
        return self._grid.load(path)


viewer_handler = ViewerHandler(grid_handler)
viewer_handler.registry.register(ImageViewerPlugin)

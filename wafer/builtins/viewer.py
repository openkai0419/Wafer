from PySide6 import QtGui

from ..plugin.viewer.base import ImageViewerPlugin


class DefaultViewerPlugin(ImageViewerPlugin):
    NAME = "default_viewer"
    EXTENSIONS = ()
    PRIORITY = -100

    def load_content(self, path: str) -> QtGui.QImage | None:
        from ..plugin.grid.handler import grid_resolver

        return grid_resolver.load(path)

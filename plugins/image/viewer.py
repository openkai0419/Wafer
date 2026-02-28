from PySide6 import QtGui
from afterimages import BaseViewerPlugin


class ImageViewerPlugin(BaseViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load_content(self, path: str) -> QtGui.QImage | None:
        from source.plugin_core.grid.handler import grid_resolver
        return grid_resolver.load(path)

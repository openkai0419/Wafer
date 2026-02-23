from PySide6 import QtGui
from .base import BaseViewerPlugin
from ..grid.handler import grid_handler


class ImageViewerPlugin(BaseViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load_content(self, path: str) -> QtGui.QImage | None:
        return grid_handler.load(path)

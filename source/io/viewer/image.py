from PySide6 import QtGui
from ...common.logs import AppLogger
from .base import BaseViewerPlugin
from ..grid import load as grid_load


class ImageViewerPlugin(BaseViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def create_widget(self, parent=None):
        from ...image_viewer.shower.image_viewer import ImageViewerWidget
        return ImageViewerWidget(parent)

    def load_content(self, path: str) -> QtGui.QImage | None:
        return grid_load(path)

    def clear(self, widget):
        widget.clear()

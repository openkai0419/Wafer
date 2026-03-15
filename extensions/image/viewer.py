from PySide6 import QtGui

from wafer.plugin import ImageViewerPlugin as _ImageViewerPlugin

from .loader import load_image


class ImageViewerPlugin(_ImageViewerPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def load_content(self, path: str) -> QtGui.QImage | None:
        return load_image(path)

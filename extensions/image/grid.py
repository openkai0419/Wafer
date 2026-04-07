from PySide6 import QtGui

from wafer.plugin import ImageGridPlugin as _ImageGridPlugin

from .loader import load_image


class ImageGridPlugin(_ImageGridPlugin):
    NAME = "image"
    EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
    PRIORITY = 100
    DEFAULT_ENABLED = True

    def load(self, path: str, size=None) -> QtGui.QImage | None:
        return load_image(path, size)

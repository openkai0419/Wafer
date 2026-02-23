from PySide6 import QtCore, QtGui

from ...common.logs import AppLogger
from ..registry import PluginRegistry
from .base import BaseGridPlugin
from .image import ImageGridPlugin


def _pil_to_qimage(img):
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    data = img.tobytes('raw', 'BGRA')
    qimage = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return qimage.copy()


class GridHandler:

    def __init__(self):
        self.registry = PluginRegistry()
        self._thumbnailer = None

    def _get_thumbnailer(self):
        if self._thumbnailer is None:
            from ...os.thumbnails import FileThumbnailer
            self._thumbnailer = FileThumbnailer()
        return self._thumbnailer

    def _fallback_load(self, path: str, size=None) -> QtGui.QImage | None:
        try:
            thumb_size = 256
            if size is not None:
                thumb_size = max(size.width(), size.height(), 256)
            pil_img = self._get_thumbnailer().get_thumbnail(path, size=thumb_size)
            if pil_img is None:
                return None
            qimage = _pil_to_qimage(pil_img)
            if size is not None:
                qimage = qimage.scaled(size, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            return qimage
        except Exception as e:
            AppLogger.debug(f'[GridHandler] Fallback load failed: {path} ({e})')
            return None

    def load(self, path: str, size=None) -> QtGui.QImage | None:
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None:
            result = plugin_cls().load(path, size)
            if result is not None:
                return result
        return self._fallback_load(path, size)


grid_handler = GridHandler()
grid_handler.registry.register(ImageGridPlugin)

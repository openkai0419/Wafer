from PySide6 import QtCore

from ...common.logs import AppLogger
from .base import BaseGridPlugin


def _pil_to_qimage(img):
    from PySide6 import QtGui
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    data = img.tobytes('raw', 'BGRA')
    qimage = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return qimage.copy()


class FallbackGridPlugin(BaseGridPlugin):
    NAME = 'fallback'
    EXTENSIONS = ()
    PRIORITY = 0

    _thumbnailer = None

    @classmethod
    def _get_thumbnailer(cls):
        if cls._thumbnailer is None:
            from ...os.thumbnails import FileThumbnailer
            cls._thumbnailer = FileThumbnailer()
        return cls._thumbnailer

    def load(self, path: str, size=None):
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
            AppLogger.debug(f'[FallbackGridPlugin] Failed: {path} ({e})')
            return None

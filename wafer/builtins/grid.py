from PySide6 import QtCore, QtGui

from ..plugin.grid.base import ImageGridPlugin
from ..utils.logs import AppLogger
from ..utils.profiling import profiler


def _pil_to_qimage(img):
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    data = img.tobytes('raw', 'BGRA')
    qimage = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return qimage.copy()


class SystemThumbnailPlugin(ImageGridPlugin):
    NAME = 'system_thumbnail'
    EXTENSIONS = ()
    PRIORITY = -100

    _thumbnailer = None

    @classmethod
    def _get_thumbnailer(cls):
        if cls._thumbnailer is None:
            from ..core.platform.thumbnails import FileThumbnailer
            cls._thumbnailer = FileThumbnailer()
        return cls._thumbnailer

    @profiler.profile
    def load(self, path: str, size=None) -> QtGui.QImage | None:
        try:
            from ..plugin.grid.handler import grid_resolver
            thumb_size = grid_resolver.thumbnail_size
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
            AppLogger.debug(f'[SystemThumbnailPlugin] load failed: {path} ({e})')
            return None

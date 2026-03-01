from PySide6 import QtCore, QtGui

from ...utils.logs import AppLogger
from ..registry import PluginRegistry
from .base import BaseGridPlugin

VIEWER_THUMBNAIL_DEFAULT_SIZE = 512


def _pil_to_qimage(img):
    if img.mode != 'RGBA':
        img = img.convert('RGBA')
    data = img.tobytes('raw', 'BGRA')
    qimage = QtGui.QImage(data, img.width, img.height, img.width * 4, QtGui.QImage.Format_ARGB32)
    return qimage.copy()


class GridResolver:

    def __init__(self):
        self.registry = PluginRegistry()
        self._thumbnailer = None
        self.thumbnail_size = VIEWER_THUMBNAIL_DEFAULT_SIZE

    def _get_thumbnailer(self):
        if self._thumbnailer is None:
            from afterimages.core.platform.thumbnails import FileThumbnailer
            self._thumbnailer = FileThumbnailer()
        return self._thumbnailer

    def _fallback_load(self, path: str, size=None) -> QtGui.QImage | None:
        try:
            thumb_size = self.thumbnail_size
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
            AppLogger.debug(f'[GridResolver] Fallback load failed: {path} ({e})')
            return None

    def resolve(self, path: str) -> type[BaseGridPlugin] | None:
        return self.registry.resolve(path)

    def has_widget(self, path: str) -> bool:
        plugin_cls = self.registry.resolve(path)
        return plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None

    def load(self, path: str, size=None) -> QtGui.QImage | None:
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is None:
            result = plugin_cls().load(path, size)
            if result is not None:
                return result
        return self._fallback_load(path, size)

    def render(self, path: str, widget, size=None):
        plugin_cls = self.registry.resolve(path)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            plugin_cls().render(path, widget, size)

    def release(self, plugin_name: str, widget):
        plugin_cls = self.registry.get(plugin_name)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            plugin_cls().release(widget)

    def select(self, plugin_name: str, widget, path: str):
        plugin_cls = self.registry.get(plugin_name)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            plugin_cls().select(widget, path)

    def deselect(self, plugin_name: str, widget):
        plugin_cls = self.registry.get(plugin_name)
        if plugin_cls is not None and plugin_cls.WIDGET_CLASS is not None:
            plugin_cls().deselect(widget)


grid_resolver = GridResolver()

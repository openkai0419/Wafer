from PySide6 import QtCore, QtGui

from ...utils.logs import AppLogger
from ...utils.profiling import profiler
from ..registry import PluginRegistry
from .base import BaseGridPlugin, ImageGridPlugin, WidgetGridPlugin

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
            from ...core.platform.thumbnails import FileThumbnailer
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

    @profiler.profile
    def resolve(self, path: str) -> type[BaseGridPlugin] | None:
        return self.registry.resolve(path)

    def is_widget_plugin(self, path: str) -> bool:
        return isinstance(self.registry.resolve_instance(path), WidgetGridPlugin)

    def load(self, path: str, size=None) -> QtGui.QImage | None:
        instance = self.registry.resolve_instance(path)
        if isinstance(instance, ImageGridPlugin):
            result = instance.load(path, size)
            if result is not None:
                return result
        return self._fallback_load(path, size)


grid_resolver = GridResolver()


class WidgetNotifier:

    def __init__(self, registry: PluginRegistry):
        self._registry = registry
        self._names: dict[int, str] = {}

    def plugin_name(self, index: int) -> str | None:
        return self._names.get(index)

    @profiler.profile
    def _notify(self, index: int, method: str, widget):
        name = self._names.get(index)
        if not name:
            return
        instance = self._registry.instance(name)
        if isinstance(instance, WidgetGridPlugin):
            getattr(instance, method)(widget)

    @profiler.profile
    def bind(self, index: int, plugin_name: str, widget, path: str, size=None):
        self._names[index] = plugin_name
        instance = self._registry.instance(plugin_name)
        if isinstance(instance, WidgetGridPlugin):
            instance.render(widget, path, size)

    @profiler.profile
    def unbind(self, index: int, widget):
        name = self._names.pop(index, None)
        if not name:
            return
        instance = self._registry.instance(name)
        if isinstance(instance, WidgetGridPlugin):
            if widget.isVisible():
                instance.disappear(widget)
            instance.release(widget)

    @profiler.profile
    def appear(self, index: int, widget):
        self._notify(index, 'appear', widget)

    @profiler.profile
    def disappear(self, index: int, widget):
        self._notify(index, 'disappear', widget)

    @profiler.profile
    def select(self, index: int, widget):
        self._notify(index, 'select', widget)

    @profiler.profile
    def deselect(self, index: int, widget):
        self._notify(index, 'deselect', widget)

    def clear(self):
        self._names.clear()

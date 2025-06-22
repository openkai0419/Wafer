from collections import OrderedDict
from PySide6 import QtWidgets, QtGui, QtCore

from ...profiling import init_env
logger, profiler = init_env("viewer")


class FadeLabel(QtWidgets.QLabel):
    _FADE_DURATION = 120          # ms

    @profiler.profile
    def __init__(self, parent=None):
        super().__init__(parent)
        self.curpath = None

        self._opacity = 1.0

        eff = QtWidgets.QGraphicsOpacityEffect(self, opacity=self._opacity)
        self.setGraphicsEffect(eff)

        self.setScaledContents(True)
        self._fade_anim = QtCore.QPropertyAnimation(self, b"opacity", self)
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    # ------------------------------------------------------------- #
    # プロパティラッパ
    def get_opacity(self):
        return self._opacity

    def set_opacity(self, v):
        self._opacity = v
        self.graphicsEffect().setOpacity(v)
        self.update()

    opacity = QtCore.Property(float, get_opacity, set_opacity)
    # ------------------------------------------------------------- #

    @profiler.profile
    def set_pixmap(self, pixmap: QtGui.QPixmap, curpath=None):
        if self.curpath != curpath:
            self.setPixmap(pixmap)
            self.curpath = curpath
            self._fade_anim.stop()
            self.set_opacity(0.0)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            self.setPixmap(pixmap)
            self.curpath = curpath


class QLabelPool:
    def __init__(self, parent=None):
        self._available = []
        self._in_use = set()
        self._parent = parent

    def acquire(self):
        if self._available:
            label = self._available.pop()
        else:
            label = FadeLabel(self._parent)
        label.clear()
        label.show()
        self._in_use.add(label)
        return label

    def release(self, label):
        label.hide()
        label.clear()
        label.setParent(self._parent)
        self._in_use.discard(label)
        self._available.append(label)

    def reset(self):
        while self._in_use:
            label = self._in_use.pop()
            self.release(label)


class MemoryLimitedPixmapCache:
    def __init__(self, max_bytes=100 * 1024 * 1024):
        self.max_bytes = max_bytes
        self.current_bytes = 0
        self.cache = OrderedDict()

    @profiler.profile
    def _estimate_pixmap_size(self, pixmap: QtGui.QPixmap) -> int:
        size = pixmap.size()
        return size.width() * size.height() * 4

    @profiler.profile
    def __setitem__(self, key, pixmap: QtGui.QPixmap):
        if key in self.cache:
            self.current_bytes -= self._estimate_pixmap_size(self.cache[key])
            del self.cache[key]

        pixmap_size = self._estimate_pixmap_size(pixmap)
        self.cache[key] = pixmap
        self.cache.move_to_end(key)
        self.current_bytes += pixmap_size

        while self.current_bytes > self.max_bytes and self.cache:
            old_key, old_pixmap = self.cache.popitem(last=False)
            self.current_bytes -= self._estimate_pixmap_size(old_pixmap)

    def __getitem__(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        raise KeyError(key)

    def __contains__(self, key):
        return key in self.cache

    def __delitem__(self, key):
        if key in self.cache:
            self.current_bytes -= self._estimate_pixmap_size(self.cache[key])
            del self.cache[key]

    def clear(self):
        self.cache.clear()
        self.current_bytes = 0

    def get(self, key, default=None):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return default
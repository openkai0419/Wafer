from collections import OrderedDict
from PySide6 import QtCore, QtGui, QtWidgets
from ...common.profiling import profiler
from ...common.classes import singleton


class FadePixmapItem(QtWidgets.QGraphicsObject):
    _FADE_DURATION = 120

    @profiler.profile
    def __init__(self, parent=None):
        super().__init__(parent)
        self.curpath = None
        self._pixmap = QtGui.QPixmap()
        self._size = QtCore.QSizeF()
        self.setOpacity(0.0)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._fade_anim = QtCore.QPropertyAnimation(self, b'opacity', self)
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def boundingRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._size)

    def paint(self, painter, option, widget=None):
        if not self._pixmap.isNull():
            painter.drawPixmap(self.boundingRect().toRect(), self._pixmap)

    @profiler.profile
    def set_image(self, image, curpath=None):
        pixmap = QtGui.QPixmap.fromImage(image)
        if self.curpath != curpath:
            self._pixmap = pixmap
            self.curpath = curpath
            self._fade_anim.stop()
            self.setOpacity(0.0)
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
            self.setToolTip(curpath or "")
            self.update()
        else:
            self._pixmap = pixmap
            self.update()

    def setGeometry(self, rect):
        self.prepareGeometryChange()
        self.setPos(rect.x(), rect.y())
        self._size = QtCore.QSizeF(rect.width(), rect.height())
        self.update()

    def geometry(self):
        return QtCore.QRectF(self.pos(), self._size).toRect()

    def pixmap(self):
        return self._pixmap

    def size(self):
        return self._size.toSize()

    def clear(self):
        self._pixmap = QtGui.QPixmap()
        self.curpath = None
        self.setToolTip("")
        self.update()

    def delete(self):
        pass

    def grab(self):
        return self._pixmap.copy() if not self._pixmap.isNull() else QtGui.QPixmap(self.size())


class GraphicsItemPool:
    def __init__(self, scene):
        self._available = []
        self._in_use = set()
        self._scene = scene

    @profiler.profile
    def acquire(self):
        if self._available:
            item = self._available.pop()
        else:
            item = FadePixmapItem()
            self._scene.addItem(item)
        item.clear()
        item.show()
        self._in_use.add(item)
        return item

    @profiler.profile
    def release(self, item):
        if isinstance(item, FadePixmapItem):
            item.hide()
            item.clear()
            self._in_use.discard(item)
            self._available.append(item)
        else:
            item.hide()
            self._in_use.discard(item)
            if item.scene():
                item.scene().removeItem(item)

    @profiler.profile
    def reset(self):
        while self._in_use:
            item = self._in_use.pop()
            self.release(item)

@singleton
class MemoryLimitedImageCache:
    def __init__(self, max_mbytes=100):
        self.max_bytes = max_mbytes * 1024 * 1024
        self.current_bytes = 0
        self.cache = OrderedDict()

    @profiler.profile
    def _estimate_image_size(self, image):
        size = image.size()
        return size.width() * size.height() * 4

    @profiler.profile
    def __setitem__(self, key, image):
        if key in self.cache:
            self.current_bytes -= self._estimate_image_size(self.cache[key])
            del self.cache[key]
        image_size = self._estimate_image_size(image)
        self.cache[key] = image
        self.cache.move_to_end(key)
        self.current_bytes += image_size
        while self.current_bytes > self.max_bytes and self.cache:
            old_key, old_image = self.cache.popitem(last=False)
            self.current_bytes -= self._estimate_image_size(old_image)

    @profiler.profile
    def __getitem__(self, key):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        raise KeyError(key)

    @profiler.profile
    def __contains__(self, key):
        return key in self.cache

    @profiler.profile
    def __delitem__(self, key):
        if key in self.cache:
            self.current_bytes -= self._estimate_image_size(self.cache[key])
            del self.cache[key]

    def clear(self):
        self.cache.clear()
        self.current_bytes = 0

    def get(self, key, default=None):
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return default

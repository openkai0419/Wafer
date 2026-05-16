from PySide6 import QtCore, QtGui, QtWidgets
from ....core.qt.image_cache import MemoryLimitedImageCache, fullsize_key
from ....utils.profiling import profiler


class FadePixmapItem(QtWidgets.QGraphicsObject):
    _FADE_DURATION = 120

    @profiler.profile
    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_path = None
        self._pixmap = QtGui.QPixmap()
        self._size = QtCore.QSizeF()
        self.setOpacity(0.0)
        self.setAcceptedMouseButtons(QtCore.Qt.NoButton)
        self._fade_anim = QtCore.QPropertyAnimation(self, b"opacity", self)
        self._fade_anim.setDuration(self._FADE_DURATION)
        self._fade_anim.setEasingCurve(QtCore.QEasingCurve.OutCubic)

    def boundingRect(self):
        return QtCore.QRectF(QtCore.QPointF(0, 0), self._size)

    def paint(self, painter, option, widget=None):
        if not self._pixmap.isNull():
            br = self.boundingRect().toRect()
            pw, ph = self._pixmap.width(), self._pixmap.height()
            bw, bh = br.width(), br.height()
            if pw > 0 and ph > 0 and bw > 0 and bh > 0:
                scale = max(bw / pw, bh / ph)
                src_w = bw / scale
                src_h = bh / scale
                src_x = (pw - src_w) / 2
                src_y = (ph - src_h) / 2
                painter.drawPixmap(
                    QtCore.QRectF(br),
                    self._pixmap,
                    QtCore.QRectF(src_x, src_y, src_w, src_h),
                )

    @profiler.profile
    def set_image(self, image, curpath=None):
        pixmap = QtGui.QPixmap.fromImage(image)
        if self.current_path != curpath:
            self._pixmap = pixmap
            self.current_path = curpath
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

    @profiler.profile
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

    @profiler.profile
    def clear(self):
        self._pixmap = QtGui.QPixmap()
        self.current_path = None
        self.setToolTip("")
        self.update()

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
        for item in list(self._in_use):
            self.release(item)


class AdditionalWidgetPool:
    def __init__(self, grid_resolver):
        self._pools: dict[str, list[QtWidgets.QWidget]] = {}
        self._in_use: dict[QtWidgets.QWidget, str] = {}
        self._grid = grid_resolver

    @profiler.profile
    def acquire(self, plugin_name: str, parent: QtWidgets.QWidget) -> QtWidgets.QWidget | None:
        pool = self._pools.get(plugin_name)
        if pool:
            widget = pool.pop()
            widget.setParent(parent)
        else:
            from ....plugin.grid.base import WidgetGridPlugin

            plugin_cls = self._grid.registry.get(plugin_name)
            if plugin_cls is None or not issubclass(plugin_cls, WidgetGridPlugin) or plugin_cls.WIDGET_CLASS is None:
                return None
            widget = plugin_cls.WIDGET_CLASS(parent)
        self._in_use[widget] = plugin_name
        return widget

    def pool_size(self, plugin_name: str) -> int:
        return len(self._pools.get(plugin_name, []))

    def in_use_count(self, plugin_name: str) -> int:
        return sum(1 for n in self._in_use.values() if n == plugin_name)

    def plugin_name_of(self, widget: QtWidgets.QWidget) -> str | None:
        return self._in_use.get(widget)

    @profiler.profile
    def release(self, widget: QtWidgets.QWidget):
        plugin_name = self._in_use.pop(widget, None)
        if plugin_name is None:
            return
        widget.hide()
        pool = self._pools.setdefault(plugin_name, [])
        pool.append(widget)

    @profiler.profile
    def warm_up(self, parent: QtWidgets.QWidget):
        from ....plugin.grid.base import WidgetGridPlugin

        for plugin_cls in self._grid.registry.list_all():
            if not issubclass(plugin_cls, WidgetGridPlugin) or plugin_cls.WIDGET_CLASS is None:
                continue
            name = plugin_cls.NAME
            if self._pools.get(name):
                continue
            widget = plugin_cls.WIDGET_CLASS(parent)
            widget.hide()
            self._pools.setdefault(name, []).append(widget)

    def _safe_cleanup(self, widget: QtWidgets.QWidget):
        try:
            widget.hide()
        except RuntimeError:
            return
        if hasattr(widget, "cleanup"):
            widget.cleanup()

    @profiler.profile
    def reset(self):
        for widget in list(self._in_use):
            self._safe_cleanup(widget)
        self._in_use.clear()
        for pool in self._pools.values():
            for widget in pool:
                self._safe_cleanup(widget)
        self._pools.clear()

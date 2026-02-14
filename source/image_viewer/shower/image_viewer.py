from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from typing import Literal
from ...actions.bridge import Kit

FitMode = Literal["contain", "cover"]

_HUGE = 1_000_000_000.0

class ZoomPanGraphicsView(QtWidgets.QGraphicsView, Kit.UIMixin):
    zoomChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.scene().setSceneRect(-_HUGE, -_HUGE, _HUGE * 2, _HUGE * 2)
        self._pix_item: QtWidgets.QGraphicsPixmapItem | None = None
        self._min_scale = 0.05
        self._max_scale = 50.0
        self._is_panning = False
        self._last_pos = QtCore.QPoint()
        self._fit_mode: FitMode = "contain"
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.NoAnchor)
        self.setResizeAnchor(QtWidgets.QGraphicsView.NoAnchor)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setBackgroundBrush(self.palette().brush(QtGui.QPalette.ColorRole.Dark))
        self.init_command_binding("GraphicsView", enable_drops=True)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        vw = ctx.get_instance("ViewerWidget")
        p = getattr(vw, "path", None) if vw is not None else None
        return {"path": p, "paths": [p] if p else []}

    def set_image(self, pixmap: QtGui.QPixmap):
        if self._pix_item is None:
            self._pix_item = self.scene().addPixmap(pixmap)
            self._pix_item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        else:
            self._pix_item.setPixmap(pixmap)
        self.fit_in_view(padding=0.0)

    def set_fit_mode(self, mode: FitMode):
        self._fit_mode = mode

    def toggle_fit_mode(self):
        self._fit_mode = "cover" if self._fit_mode == "contain" else "contain"

    def _image_rect(self) -> QtCore.QRectF | None:
        if self._pix_item is None:
            return None
        return self._pix_item.boundingRect()

    def fit_in_view(self, padding: float = 0.0, mode: FitMode | None = None):
        r = self._image_rect()
        if r is None or r.isEmpty():
            return
        r = r.adjusted(padding, padding, -padding, -padding)
        mode = mode or self._fit_mode
        vp = self.viewport().rect()
        if vp.isEmpty():
            return
        vw, vh = max(1, vp.width()), max(1, vp.height())
        rw, rh = max(1.0, r.width()), max(1.0, r.height())
        sx, sy = vw / rw, vh / rh
        s = min(sx, sy) if mode == "contain" else max(sx, sy)
        s = max(self._min_scale, min(s, self._max_scale))
        t = QtGui.QTransform()
        t.scale(s, s)
        self.setTransform(t)
        self.centerOn(r.center())
        self.zoomChanged.emit(s)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_in_view(padding=0.0)

    def _current_scale(self) -> float:
        m = self.transform()
        return (m.m11() + m.m22()) / 2.0

    def _clamp_scale(self):
        s = self._current_scale()
        if s < self._min_scale:
            self.scale(self._min_scale / s, self._min_scale / s)
        elif s > self._max_scale:
            self.scale(self._max_scale / s, self._max_scale / s)

    def _clamp_center(self, margin_px: float = 50.0):
        r = self._image_rect()
        if r is None or r.isEmpty():
            return
        vp = self.viewport().rect()
        if vp.isEmpty():
            return
        s = self._current_scale()
        if s <= 0:
            return
        center = self.mapToScene(vp.center())
        m = margin_px / s
        hw = vp.width() / (2.0 * s) - m
        hh = vp.height() / (2.0 * s) - m
        cx = max(r.left() - hw, min(center.x(), r.right() + hw))
        cy = max(r.top() - hh, min(center.y(), r.bottom() + hh))
        if abs(cx - center.x()) > 0.01 or abs(cy - center.y()) > 0.01:
            self.centerOn(QtCore.QPointF(cx, cy))

    def zoom_at(self, factor: float, pos: QtCore.QPoint | None = None):
        if self._pix_item is None:
            return
        before = self._current_scale()
        anchor = self.mapToScene(pos) if pos is not None else None
        self.scale(factor, factor)
        self._clamp_scale()
        if anchor is not None:
            new_at_pos = self.mapToScene(pos)
            center = self.mapToScene(self.viewport().rect().center())
            self.centerOn(center + (anchor - new_at_pos))
        self._clamp_center()
        after = self._current_scale()
        if before != after:
            self.zoomChanged.emit(after)

    def pan_by(self, dx: float, dy: float):
        s = self._current_scale()
        if s <= 0:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(QtCore.QPointF(center.x() - dx / s, center.y() - dy / s))
        self._clamp_center()


class ImageViewerWidget(QtWidgets.QWidget):
    resized = QtCore.Signal()
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = ZoomPanGraphicsView(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def resizeEvent(self, event):
        self.resized.emit()
        return super().resizeEvent(event)

    def set_content(self, data, path=None):
        self.view.set_image(QtGui.QPixmap.fromImage(data))

    def set_image(self, image, path=None):
        self.set_content(image, path)

    def clear(self):
        if self.view._pix_item is not None:
            self.view._pix_item.setPixmap(QtGui.QPixmap())

    def load_image(self, path: str):
        pm = QtGui.QPixmap(path)
        self.view.set_image(pm)

    def set_contain(self, state):
        self.view.set_fit_mode("contain" if state else "cover")

    def is_contain(self):
        return True if self.view._fit_mode == "contain" else False

if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = ImageViewerWidget()
    if len(sys.argv) > 1:
        w.load_image(sys.argv[1])
    w.resize(1000, 700)
    w.show()
    sys.exit(app.exec())

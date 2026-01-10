from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets
from typing import Literal
from ...actions.bridge import Kit

FitMode = Literal["contain", "cover"]

class ZoomPanGraphicsView(QtWidgets.QGraphicsView, Kit.UIMixin):
    zoomChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self._pix_item: QtWidgets.QGraphicsPixmapItem | None = None
        self._min_scale = 0.05
        self._max_scale = 50.0
        self._is_panning = False
        self._last_pos = QtCore.QPoint()
        self._fit_mode: FitMode = "contain"
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setBackgroundBrush(self.palette().brush(QtGui.QPalette.ColorRole.Dark))
        self.init_command_binding("GraphicsView", enable_drops=True)

    def set_image(self, pixmap: QtGui.QPixmap):
        if self._pix_item is None:
            self._pix_item = self.scene().addPixmap(pixmap)
            self._pix_item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        else:
            self._pix_item.setPixmap(pixmap)
        self.scene().setSceneRect(self._pix_item.boundingRect())
        self.reset_view()

    def set_fit_mode(self, mode: FitMode):
        self._fit_mode = mode

    def toggle_fit_mode(self):
        self._fit_mode = "cover" if self._fit_mode == "contain" else "contain"

    def reset_view(self):
        self.setTransform(QtGui.QTransform())
        self.centerOn(self.sceneRect().center())
        self.fit_in_view(padding=0.0)

    def fit_in_view(self, padding: float = 0.0, mode: FitMode | None = None):
        if not self._pix_item:
            return
        r = self._pix_item.boundingRect().adjusted(padding, padding, -padding, -padding)
        if r.isEmpty():
            return

        mode = mode or self._fit_mode
        view_rect = self.viewport().rect()
        if view_rect.isEmpty():
            return

        vw = max(1, view_rect.width())
        vh = max(1, view_rect.height())
        rw = max(1.0, r.width())
        rh = max(1.0, r.height())

        sx = vw / rw
        sy = vh / rh
        s = min(sx, sy) if mode == "contain" else max(sx, sy)

        self.setTransform(QtGui.QTransform())
        t = QtGui.QTransform()
        t.scale(s, s)
        self.setTransform(t)

        cx = r.center().x()
        cy = r.top() + (vh / (2.0 * s))
        self.centerOn(QtCore.QPointF(cx, cy))

        self._clamp_scale()
        self.zoomChanged.emit(self._current_scale())

    def _current_scale(self) -> float:
        m = self.transform()
        return (m.m11() + m.m22()) / 2.0

    def _clamp_scale(self):
        s = self._current_scale()
        if s < self._min_scale:
            self._set_scale(self._min_scale / s)
        elif s > self._max_scale:
            self._set_scale(self._max_scale / s)

    def _set_scale(self, factor: float):
        self.scale(factor, factor)


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

    def set_image(self, image, path=None):
        self.view.set_image(QtGui.QPixmap.fromImage(image))

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

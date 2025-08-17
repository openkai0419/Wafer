from __future__ import annotations
from PySide6 import QtCore, QtGui, QtWidgets

class ZoomPanGraphicsView(QtWidgets.QGraphicsView):
    zoomChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self._pix_item: QtWidgets.QGraphicsPixmapItem | None = None
        self._min_scale = 0.05
        self._max_scale = 50.0
        self._is_panning = False
        self._last_pos = QtCore.QPoint()
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QtWidgets.QGraphicsView.NoDrag)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.SmartViewportUpdate)
        self.setBackgroundBrush(self.palette().brush(QtGui.QPalette.ColorRole.Dark))

    # --- public API ---
    def set_image(self, pixmap: QtGui.QPixmap):
        if self._pix_item is None:
            self._pix_item = self.scene().addPixmap(pixmap)
            self._pix_item.setTransformationMode(QtCore.Qt.SmoothTransformation)
        else:
            self._pix_item.setPixmap(pixmap)
        self.scene().setSceneRect(self._pix_item.boundingRect())
        self.reset_view()

    def reset_view(self):
        self.setTransform(QtGui.QTransform())  # identity
        self.centerOn(self.sceneRect().center())
        self.fit_in_view(padding=0.0)

    def fit_in_view(self, padding: float = 0.0):
        if not self._pix_item:
            return
        r = self._pix_item.boundingRect().adjusted(padding, padding, -padding, -padding)
        if r.isEmpty():
            return
        self.fitInView(r, QtCore.Qt.AspectRatioMode.KeepAspectRatio)
        self._clamp_scale()
        self.zoomChanged.emit(self._current_scale())

    # --- helpers ---
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

    # --- events ---
    def wheelEvent(self, event: QtGui.QWheelEvent):
        if not self._pix_item:
            return
        angle = event.angleDelta().y()
        if angle == 0:
            return
        # タッチパッドでも快適な係数
        step = 1.0015
        steps = angle
        factor = step ** steps
        # Ctrlで微調整、Shiftで大きめ
        if event.modifiers() & QtCore.Qt.KeyboardModifier.ControlModifier:
            factor = step ** (steps * 0.5)
        elif event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier:
            factor = step ** (steps * 2.0)

        before = self._current_scale()
        self._set_scale(factor)
        self._clamp_scale()
        after = self._current_scale()
        if before != after:
            self.zoomChanged.emit(after)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton:
            self._is_panning = True
            self._last_pos = event.pos()
            self.setCursor(QtCore.Qt.CursorShape.ClosedHandCursor)
            self.setDragMode(QtWidgets.QGraphicsView.NoDrag)  # 自前パン
            event.accept()
            return
        if event.button() == QtCore.Qt.MouseButton.RightButton:
            self.reset_view()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self._is_panning:
            delta = self.mapToScene(self._last_pos) - self.mapToScene(event.pos())
            self._last_pos = event.pos()
            self.translate(delta.x(), delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == QtCore.Qt.MouseButton.LeftButton and self._is_panning:
            self._is_panning = False
            self.setCursor(QtCore.Qt.CursorShape.ArrowCursor)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        # ダブルクリックでfit
        self.fit_in_view()
        event.accept()

    def resizeEvent(self, event: QtGui.QResizeEvent):
        super().resizeEvent(event)
        # 画像が入っていて、縮小しすぎでなければ軽くfit
        if self._pix_item:
            old = self._current_scale()
            self.fit_in_view()
            self._set_scale(old / self._current_scale())  # 既存ズームを維持
            self._clamp_scale()

class ImageViewerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = ZoomPanGraphicsView(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def set_pixmap(self, pixmap, path=None):
        
        self.view.set_image(pixmap)

    def load_image(self, path: str):
        pm = QtGui.QPixmap(path)
        self.view.set_image(pm)

# --- demo ---
if __name__ == "__main__":
    import sys
    app = QtWidgets.QApplication(sys.argv)
    w = ImageViewerWidget()
    if len(sys.argv) > 1:
        w.load_image(sys.argv[1])
    w.resize(1000, 700)
    w.show()
    sys.exit(app.exec())

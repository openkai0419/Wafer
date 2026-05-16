from __future__ import annotations

from typing import Literal

from PySide6 import QtCore, QtGui, QtWidgets

from ...core.commands.bridge import ActionKit
from ...plugin.viewer.base import viewer_context_values

FitMode = Literal["contain", "cover"]

_HUGE = 1_000_000_000.0


class ZoomPanImageView(QtWidgets.QGraphicsView, ActionKit.UIMixin):
    zoomChanged = QtCore.Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.scene().setSceneRect(-_HUGE, -_HUGE, _HUGE * 2, _HUGE * 2)
        self._pix_items: list[QtWidgets.QGraphicsPixmapItem] = []
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
        self.init_command_binding("ImageView", enable_drops=True)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        viewer = ctx.get_instance("FileViewerController")
        return viewer_context_values(viewer.current_viewer_contexts() if viewer is not None else ())

    def set_pixmaps(self, pixmaps: list[QtGui.QPixmap], direction: str = "right-to-left"):
        scene = self.scene()
        for item in self._pix_items:
            scene.removeItem(item)
        self._pix_items = []
        pixmaps = [pixmap for pixmap in pixmaps if pixmap is not None and not pixmap.isNull()]
        if direction in ("right-to-left", "bottom-to-top"):
            pixmaps = list(reversed(pixmaps))
        horizontal = direction in ("left-to-right", "right-to-left")
        max_width = max((pixmap.width() for pixmap in pixmaps), default=0)
        max_height = max((pixmap.height() for pixmap in pixmaps), default=0)
        offset = 0.0
        for pixmap in pixmaps:
            item = scene.addPixmap(pixmap)
            item.setTransformationMode(QtCore.Qt.SmoothTransformation)
            if horizontal:
                item.setPos(offset, (max_height - pixmap.height()) / 2.0)
                offset += pixmap.width()
            else:
                item.setPos((max_width - pixmap.width()) / 2.0, offset)
                offset += pixmap.height()
            self._pix_items.append(item)
        self.viewport().update()
        self.fit_in_view(padding=0.0)

    def has_content(self) -> bool:
        return any(not item.pixmap().isNull() for item in self._pix_items)

    def clear_pixmaps(self):
        scene = self.scene()
        for item in self._pix_items:
            scene.removeItem(item)
        self._pix_items = []
        self.viewport().update()

    def set_fit_mode(self, mode: FitMode):
        self._fit_mode = mode

    def toggle_fit_mode(self):
        self._fit_mode = "cover" if self._fit_mode == "contain" else "contain"

    def _image_rect(self) -> QtCore.QRectF | None:
        if not self._pix_items:
            return None
        rect = self._pix_items[0].sceneBoundingRect()
        for item in self._pix_items[1:]:
            rect = rect.united(item.sceneBoundingRect())
        return rect

    def fit_in_view(self, padding: float = 0.0, mode: FitMode | None = None):
        rect = self._image_rect()
        if rect is None or rect.isEmpty():
            return
        rect = rect.adjusted(padding, padding, -padding, -padding)
        mode = mode or self._fit_mode
        viewport = self.viewport().rect()
        if viewport.isEmpty():
            return
        view_width = max(1, viewport.width())
        view_height = max(1, viewport.height())
        rect_width = max(1.0, rect.width())
        rect_height = max(1.0, rect.height())
        scale_x = view_width / rect_width
        scale_y = view_height / rect_height
        scale = min(scale_x, scale_y) if mode == "contain" else max(scale_x, scale_y)
        scale = max(self._min_scale, min(scale, self._max_scale))
        transform = QtGui.QTransform()
        transform.scale(scale, scale)
        self.setTransform(transform)
        self.centerOn(rect.center())
        self.zoomChanged.emit(scale)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.fit_in_view(padding=0.0)

    def _current_scale(self) -> float:
        transform = self.transform()
        return (transform.m11() + transform.m22()) / 2.0

    def _clamp_scale(self):
        scale = self._current_scale()
        if scale < self._min_scale:
            self.scale(self._min_scale / scale, self._min_scale / scale)
        elif scale > self._max_scale:
            self.scale(self._max_scale / scale, self._max_scale / scale)

    def _clamp_center(self, margin_px: float = 50.0):
        rect = self._image_rect()
        if rect is None or rect.isEmpty():
            return
        viewport = self.viewport().rect()
        if viewport.isEmpty():
            return
        scale = self._current_scale()
        if scale <= 0:
            return
        center = self.mapToScene(viewport.center())
        margin = margin_px / scale
        half_width = viewport.width() / (2.0 * scale) - margin
        half_height = viewport.height() / (2.0 * scale) - margin
        center_x = max(rect.left() - half_width, min(center.x(), rect.right() + half_width))
        center_y = max(rect.top() - half_height, min(center.y(), rect.bottom() + half_height))
        if abs(center_x - center.x()) > 0.01 or abs(center_y - center.y()) > 0.01:
            self.centerOn(QtCore.QPointF(center_x, center_y))

    def zoom_at(self, factor: float, pos: QtCore.QPoint | None = None):
        if not self._pix_items:
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
        scale = self._current_scale()
        if scale <= 0:
            return
        center = self.mapToScene(self.viewport().rect().center())
        self.centerOn(QtCore.QPointF(center.x() - dx / scale, center.y() - dy / scale))
        self._clamp_center()


class ImageDisplayWidget(QtWidgets.QWidget):
    resized = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = ZoomPanImageView(self)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)

    def resizeEvent(self, event):
        self.resized.emit()
        return super().resizeEvent(event)

    def set_images(self, images, direction: str = "right-to-left"):
        images = [image for image in images if image is not None and not image.isNull()]
        if not images:
            self.clear()
            return
        self.view.set_pixmaps([QtGui.QPixmap.fromImage(image) for image in images], direction=direction)

    def clear(self):
        self.view.clear_pixmaps()

    def set_contain_mode(self, state):
        self.view.set_fit_mode("contain" if state else "cover")

    def is_contain_mode(self):
        return self.view._fit_mode == "contain"

from __future__ import annotations

from collections.abc import Iterable

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.qt.commands.bridge import ActionKit
from wafer.qt.commands.command.payload import CommandPayload
from wafer.qt.common.dpi import dpix
from wafer.qt.theme import ThemeManager

from .session import MapResult

SCENE_SIZE = 1000.0
UNSET_TOP = SCENE_SIZE * 1.08
UNSET_SPACING = 20.0
UNSET_PER_ROW = 50
POINT_SIZE = 8
THUMB_SIZE = 64
ZOOM_STEP = 1.25


class MapPointItem(QtWidgets.QGraphicsItem):
    def __init__(self, view: MapView, row: int):
        super().__init__()
        self.view = view
        self.row = row
        self.setFlags(QtWidgets.QGraphicsItem.ItemIsSelectable | QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.setAcceptedMouseButtons(Qt.NoButton)

    def boundingRect(self) -> QtCore.QRectF:
        half = self.view.item_extent() / 2
        return QtCore.QRectF(-half, -half, half * 2, half * 2)

    def paint(self, painter, option, widget=None):
        self.view.paint_point(painter, self)


class GroupLabelItem(QtWidgets.QGraphicsItem):
    def __init__(self, view: MapView, group: int, text: str):
        super().__init__()
        self.view = view
        self.group = group
        self.text = text
        self.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.setZValue(10)
        metrics = QtGui.QFontMetrics(view.font())
        pad = dpix(4)
        width = metrics.horizontalAdvance(text) + pad * 2
        height = metrics.height() + pad
        self.rect = QtCore.QRectF(-width / 2, -height / 2, width, height)

    def boundingRect(self) -> QtCore.QRectF:
        return self.rect

    def paint(self, painter, option, widget=None):
        palette = ThemeManager.instance().palette
        painter.setPen(QtGui.QPen(QtGui.QColor(palette.border_default)))
        painter.setBrush(QtGui.QColor(palette.bg_elevated))
        painter.drawRoundedRect(self.rect, dpix(4), dpix(4))
        painter.setPen(QtGui.QColor(palette.text_primary))
        painter.drawText(self.rect, Qt.AlignCenter, self.text)

    def mousePressEvent(self, event):
        self.view.select_group(self.group)
        event.accept()


class MapView(QtWidgets.QGraphicsView, ActionKit.UIMixin):
    selection_changed = QtCore.Signal()

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setRubberBandSelectionMode(Qt.IntersectsItemShape)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setAcceptDrops(True)
        self.init_command_binding("MappingView", use_existing_events=True)
        self.items_by_row: list[MapPointItem] = []
        self.labels: list[GroupLabelItem] = []
        self.paths: list[str] = []
        self.rows_by_path: dict[str, int] = {}
        self.colors: list[QtGui.QColor] = []
        self.outliers = np.zeros(0, dtype=bool)
        self.group_of = np.zeros(0, dtype=np.int32)
        self.fit_scale = 1.0
        self.thumbnail_zoom = 2.0
        self.thumbnails = False
        self.syncing = False
        self.pan_origin: QtCore.QPoint | None = None
        self.press_pos: QtCore.QPoint | None = None
        self.press_rows: list[int] = []
        self.scene().selectionChanged.connect(self.on_scene_selection)

    @property
    def zoom(self) -> float:
        return self.transform().m11() / self.fit_scale if self.fit_scale else 1.0

    def point_items(self) -> list[MapPointItem]:
        return list(self.items_by_row)

    def label_items(self) -> list[GroupLabelItem]:
        return list(self.labels)

    def item_extent(self) -> float:
        return dpix(THUMB_SIZE) if self.thumbnails else dpix(POINT_SIZE + 4)

    def clear_map(self):
        self.syncing = True
        try:
            self.scene().clear()
        finally:
            self.syncing = False
        self.items_by_row, self.labels, self.paths, self.rows_by_path = [], [], [], {}

    def show_result(self, result: MapResult, colors: list[QtGui.QColor], show_groups: bool, keep_view: bool):
        self.clear_map()
        self.paths = list(result.paths)
        self.rows_by_path = {path: row for row, path in enumerate(self.paths)}
        self.colors = colors
        self.outliers = result.outliers
        self.group_of = result.labels if result.labels is not None else np.full(len(self.paths), -1, dtype=np.int32)
        unset_slot = {row: slot for slot, row in enumerate(np.flatnonzero(result.unset).tolist())}
        scene = self.scene()
        for row in range(len(self.paths)):
            item = MapPointItem(self, row)
            if row in unset_slot:
                slot = unset_slot[row]
                item.setPos((slot % UNSET_PER_ROW) * UNSET_SPACING, UNSET_TOP + (slot // UNSET_PER_ROW) * UNSET_SPACING)
            else:
                x, y = result.positions[row]
                item.setPos(float(x) * SCENE_SIZE, float(y) * SCENE_SIZE)
            scene.addItem(item)
            self.items_by_row.append(item)
        if show_groups:
            for group, words in result.group_terms.items():
                members = np.flatnonzero(self.group_of == group)
                if not words or members.size == 0:
                    continue
                label = GroupLabelItem(self, group, ", ".join(words))
                center = np.median(result.positions[members], axis=0)
                label.setPos(float(center[0]) * SCENE_SIZE, float(center[1]) * SCENE_SIZE)
                scene.addItem(label)
                self.labels.append(label)
        rect = scene.itemsBoundingRect()
        margin = SCENE_SIZE * 0.05
        scene.setSceneRect(rect.adjusted(-margin, -margin, margin, margin))
        if not keep_view:
            self.fitInView(scene.sceneRect(), Qt.KeepAspectRatio)
            self.fit_scale = self.transform().m11()
        self.sync_thumbnail_mode()

    def set_thumbnail_zoom(self, zoom: float):
        self.thumbnail_zoom = zoom
        self.sync_thumbnail_mode()

    def sync_thumbnail_mode(self):
        enabled = self.zoom >= self.thumbnail_zoom
        if enabled == self.thumbnails:
            return
        for item in self.items_by_row:
            item.prepareGeometryChange()
        self.thumbnails = enabled
        self.viewport().update()

    def paint_point(self, painter: QtGui.QPainter, item: MapPointItem):
        palette = ThemeManager.instance().palette
        color = self.colors[item.row] if item.row < len(self.colors) else QtGui.QColor(palette.text_secondary)
        rect = item.boundingRect()
        pixmap = self.owner.thumbnail(self.paths[item.row]) if self.thumbnails else None
        if pixmap is not None and not pixmap.isNull():
            scaled = pixmap.scaled(rect.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            target = QtCore.QRectF(QtCore.QPointF(0, 0), QtCore.QSizeF(scaled.size()))
            target.moveCenter(rect.center())
            painter.drawPixmap(target.toRect(), scaled)
            frame = target
        else:
            size = dpix(POINT_SIZE)
            frame = QtCore.QRectF(-size / 2, -size / 2, size, size)
            painter.setPen(Qt.NoPen)
            painter.setBrush(color)
            painter.drawEllipse(frame)
        outlier = self.outliers.size > item.row and bool(self.outliers[item.row])
        if not (item.isSelected() or self.thumbnails or outlier):
            return
        pen = QtGui.QPen(QtGui.QColor(palette.accent) if item.isSelected() else color, dpix(2))
        if outlier:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        if self.thumbnails:
            painter.drawRect(frame)
        else:
            painter.drawEllipse(frame.adjusted(-2, -2, 2, 2))

    def selected_rows(self) -> list[int]:
        return sorted(item.row for item in self.scene().selectedItems() if isinstance(item, MapPointItem))

    def select_rows(self, rows: Iterable[int]):
        wanted = set(rows)
        self.syncing = True
        try:
            for item in self.items_by_row:
                item.setSelected(item.row in wanted)
        finally:
            self.syncing = False

    def select_group(self, group: int):
        self.select_rows(np.flatnonzero(self.group_of == group).tolist())
        self.selection_changed.emit()

    def reveal(self, row: int):
        if 0 <= row < len(self.items_by_row):
            self.ensureVisible(self.items_by_row[row])

    def update_path(self, path: str):
        row = self.rows_by_path.get(path)
        if row is not None and self.thumbnails:
            self.items_by_row[row].update()

    def on_scene_selection(self):
        if not self.syncing:
            self.press_rows = self.selected_rows()
            self.selection_changed.emit()

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        return self.owner.context_for_selection()

    def wheelEvent(self, event: QtGui.QWheelEvent):
        steps = event.angleDelta().y() / 120
        if steps:
            factor = ZOOM_STEP**steps
            self.scale(factor, factor)
            self.sync_thumbnail_mode()
        event.accept()

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        if event.button() == Qt.MiddleButton:
            self.pan_origin = event.position().toPoint()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        position = event.position().toPoint()
        on_label = isinstance(self.itemAt(position), GroupLabelItem)
        tracking = event.button() == Qt.LeftButton and not on_label
        self.press_pos = position if tracking else None
        self.press_rows = self.selected_rows()
        self.syncing = tracking
        try:
            super().mousePressEvent(event)
        finally:
            self.syncing = False

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self.pan_origin is not None:
            position = event.position().toPoint()
            delta = position - self.pan_origin
            self.pan_origin = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == Qt.MiddleButton and self.pan_origin is not None:
            self.pan_origin = None
            self.viewport().unsetCursor()
            event.accept()
            return
        press_pos, self.press_pos = self.press_pos, None
        super().mouseReleaseEvent(event)
        if press_pos is None or event.button() != Qt.LeftButton:
            return
        position = event.position().toPoint()
        if (position - press_pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
            self.apply_click(position, event.modifiers())
        rows = self.selected_rows()
        if rows != self.press_rows:
            self.press_rows = rows
            self.selection_changed.emit()

    def apply_click(self, position: QtCore.QPoint, modifiers: Qt.KeyboardModifier):
        item = self.itemAt(position)
        row = item.row if isinstance(item, MapPointItem) else None
        selected = set(self.selected_rows())
        if modifiers & Qt.ControlModifier:
            if row is None:
                return
            selected ^= {row}
        else:
            selected = set() if row is None else {row}
        self.select_rows(selected)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        item = self.itemAt(event.position().toPoint())
        if isinstance(item, MapPointItem):
            self.select_rows([item.row])
            self.selection_changed.emit()
            self.exec_command(CommandPayload("file.open", {}), source="mouse")
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def dragEnterEvent(self, event):
        self.owner.handle_drag_enter(event)

    def dragMoveEvent(self, event):
        self.owner.handle_drag_enter(event)

    def dropEvent(self, event):
        self.owner.handle_drop(event)

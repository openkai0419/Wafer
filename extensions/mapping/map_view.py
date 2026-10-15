from __future__ import annotations

import math
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
UNSET_GAP = SCENE_SIZE * 0.08
UNSET_SPACING = 20.0
UNSET_PER_ROW = 50
POINT_SIZE = 8
MIN_POINT_SIZE = 1.0
ROUND_POINT_SIZE = 3.0
THUMB_SIZE = 64
RING = 2
ZOOM_STEP = 1.25
MIN_IMAGE_SCALE = 0.02
MAX_IMAGE_SCALE = 4.0
LABEL_GAP = 4
IMAGE_LIMIT = 300
IMAGE_SPACING = 0.01
IMAGE_REFRESH_MS = 50
PRIORITY_SEED = 0
NO_ROWS = np.zeros(0, dtype=np.int64)
NO_RECTS = np.zeros((0, 4), dtype=np.float64)


def scene_positions(result: MapResult) -> np.ndarray:
    positions = np.asarray(result.positions, dtype=np.float64).reshape(-1, 2) * SCENE_SIZE
    unset = np.flatnonzero(result.unset)
    placed = positions[~np.asarray(result.unset, dtype=bool)]
    bottom = max(SCENE_SIZE, float(np.nanmax(placed[:, 1]))) if np.isfinite(placed).any() else SCENE_SIZE
    slots = np.arange(unset.size)
    positions[unset, 0] = (slots % UNSET_PER_ROW) * UNSET_SPACING
    positions[unset, 1] = bottom + UNSET_GAP + (slots // UNSET_PER_ROW) * UNSET_SPACING
    return np.nan_to_num(positions)


class GroupLabelItem(QtWidgets.QGraphicsItem):
    def __init__(self, view: MapView, group: int, text: str, anchor: QtCore.QPointF):
        super().__init__()
        self.view = view
        self.group = group
        self.text = text
        self.setFlag(QtWidgets.QGraphicsItem.ItemIgnoresTransformations)
        self.setPos(anchor)
        self.setZValue(10)
        metrics = QtGui.QFontMetrics(view.font())
        pad = dpix(4)
        width = metrics.horizontalAdvance(text) + pad * 2
        height = metrics.height() + pad
        self.rect = QtCore.QRectF(-width / 2, -height / 2, width, height)

    def offset(self) -> float:
        return self.view.item_extent() / 2 + dpix(LABEL_GAP) + self.rect.height() / 2

    def placed_rect(self) -> QtCore.QRectF:
        return self.rect.translated(0, self.offset())

    def boundingRect(self) -> QtCore.QRectF:
        return self.placed_rect()

    def paint(self, painter, option, widget=None):
        palette = ThemeManager.instance().palette
        rect = self.placed_rect()
        painter.setPen(QtGui.QPen(QtGui.QColor(palette.border_default)))
        painter.setBrush(QtGui.QColor(palette.bg_elevated))
        painter.drawRoundedRect(rect, dpix(4), dpix(4))
        painter.setPen(QtGui.QColor(palette.text_primary))
        painter.drawText(rect, Qt.AlignCenter, self.text)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        self.view.select_group(self.group)
        event.accept()


class MapView(QtWidgets.QGraphicsView, ActionKit.UIMixin):
    selection_changed = QtCore.Signal()

    def __init__(self, owner, parent=None):
        super().__init__(parent)
        self.owner = owner
        self.setScene(QtWidgets.QGraphicsScene(self))
        self.setDragMode(QtWidgets.QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QtWidgets.QGraphicsView.AnchorUnderMouse)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.FullViewportUpdate)
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.setAcceptDrops(True)
        self.init_command_binding("MappingView", use_existing_events=True)
        self.labels: list[GroupLabelItem] = []
        self.paths: list[str] = []
        self.rows_by_path: dict[str, int] = {}
        self.colors: list[QtGui.QColor] = []
        self.positions = np.zeros((0, 2), dtype=np.float64)
        self.selected = np.zeros(0, dtype=bool)
        self.outliers = np.zeros(0, dtype=bool)
        self.group_of = np.zeros(0, dtype=np.int32)
        self.priority = NO_ROWS
        self.color_keys = NO_ROWS
        self.color_ids = NO_ROWS
        self.sprites: dict[int, QtGui.QPixmap] = {}
        self.sprite_size = 0.0
        self.layer: QtGui.QPixmap | None = None
        self.layer_key: tuple | None = None
        self.version = 0
        self.image_rows = NO_ROWS
        self.image_rects = NO_RECTS
        self.wanted_paths: set[str] = set()
        self.image_limit = IMAGE_LIMIT
        self.image_spacing = IMAGE_SPACING
        self.fit_scale = 1.0
        self.thumbnail_zoom = 2.0
        self.thumbnails = False
        self.image_scale = 1.0
        self.selection_mode = "single"
        self.hover_path: str | None = None
        self.pan_origin: QtCore.QPoint | None = None
        self.press_pos: QtCore.QPoint | None = None
        self.press_rows: list[int] = []
        self.band_base = np.zeros(0, dtype=bool)
        self.image_timer = QtCore.QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.setInterval(IMAGE_REFRESH_MS)
        self.image_timer.timeout.connect(self.invalidate)
        self.viewport().setMouseTracking(True)
        self.rubberBandChanged.connect(self.on_rubber_band)

    @property
    def zoom(self) -> float:
        return self.transform().m11() / self.fit_scale if self.fit_scale else 1.0

    def label_items(self) -> list[GroupLabelItem]:
        return list(self.labels)

    def item_extent(self) -> float:
        return dpix(self.display_size()) if self.thumbnails else self.dot_size()

    def point_size(self) -> float:
        return max(dpix(POINT_SIZE) * self.image_scale * self.zoom, MIN_POINT_SIZE)

    def dot_size(self) -> float:
        return self.point_size() + dpix(RING) * 2

    def sprite_side(self) -> float:
        return self.dot_size() + dpix(RING) * 2

    def display_size(self) -> float:
        return THUMB_SIZE * self.image_scale * self.zoom / max(self.thumbnail_zoom, 1e-6)

    def invalidate(self) -> None:
        self.version += 1
        self.viewport().update()

    def set_image_scale(self, scale: float):
        scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE)
        if scale == self.image_scale:
            return
        self.begin_geometry_change()
        self.image_scale = scale
        self.invalidate()

    def set_image_limit(self, limit: int) -> None:
        if limit != self.image_limit:
            self.image_limit = max(int(limit), 0)
            self.invalidate()

    def set_image_spacing(self, spacing: float) -> None:
        if spacing != self.image_spacing:
            self.image_spacing = max(float(spacing), 0.01)
            self.invalidate()

    def begin_geometry_change(self):
        for label in self.labels:
            label.prepareGeometryChange()

    def set_selection_mode(self, mode: str):
        self.selection_mode = "group" if mode == "group" else "single"

    def expand_to_groups(self, rows: Iterable[int]) -> list[int]:
        wanted = set(rows)
        if not wanted or not (self.group_of >= 0).any():
            return sorted(wanted)
        groups = {int(self.group_of[row]) for row in wanted if row < self.group_of.size} - {-1}
        members = np.flatnonzero(np.isin(self.group_of, list(groups)))
        return sorted(wanted | set(members.tolist()))

    def clear_map(self):
        self.scene().clear()
        self.labels, self.paths, self.rows_by_path, self.colors = [], [], {}, []
        self.positions = np.zeros((0, 2), dtype=np.float64)
        self.selected = np.zeros(0, dtype=bool)
        self.priority = self.color_keys = self.color_ids = NO_ROWS
        self.image_rows, self.image_rects, self.wanted_paths = NO_ROWS, NO_RECTS, set()
        self.sprites = {}
        self.invalidate()

    def show_result(self, result: MapResult, colors: list[QtGui.QColor], show_groups: bool, keep_view: bool):
        self.clear_map()
        count = len(result.paths)
        self.paths = list(result.paths)
        self.rows_by_path = {path: row for row, path in enumerate(self.paths)}
        self.colors = colors
        self.outliers = np.asarray(result.outliers, dtype=bool)
        self.group_of = result.labels if result.labels is not None else np.full(count, -1, dtype=np.int32)
        self.positions = scene_positions(result)
        self.selected = np.zeros(count, dtype=bool)
        self.priority = np.argsort(np.random.default_rng(PRIORITY_SEED).permutation(count))
        fallback = QtGui.QColor(ThemeManager.instance().palette.text_secondary).rgba()
        keys = np.array([colors[row].rgba() if row < len(colors) else fallback for row in range(count)], dtype=np.int64)
        self.color_keys, self.color_ids = np.unique(keys, return_inverse=True)
        if show_groups:
            self.add_labels(result)
        core = QtCore.QRectF(0, 0, SCENE_SIZE, SCENE_SIZE)
        rect = core
        if count:
            low, high = self.positions.min(axis=0), self.positions.max(axis=0)
            rect = rect.united(QtCore.QRectF(QtCore.QPointF(*low), QtCore.QPointF(*high)))
        margin = SCENE_SIZE * 0.05
        self.scene().setSceneRect(rect.adjusted(-margin, -margin, margin, margin))
        if not keep_view:
            self.begin_geometry_change()
            self.fitInView(core.adjusted(-margin, -margin, margin, margin), Qt.KeepAspectRatio)
            self.fit_scale = self.transform().m11()
        self.sync_thumbnail_mode()
        self.invalidate()

    def add_labels(self, result: MapResult) -> None:
        for group, words in result.group_terms.items():
            members = np.flatnonzero(self.group_of == group)
            if not words or members.size == 0:
                continue
            coords = result.positions[members]
            coords = coords[~np.isnan(coords).any(axis=1)]
            if coords.size == 0:
                continue
            anchor = QtCore.QPointF(float(np.median(coords[:, 0])) * SCENE_SIZE, float(np.max(coords[:, 1])) * SCENE_SIZE)
            label = GroupLabelItem(self, group, ", ".join(words), anchor)
            self.scene().addItem(label)
            self.labels.append(label)

    def set_thumbnail_zoom(self, zoom: float):
        if zoom != self.thumbnail_zoom:
            self.begin_geometry_change()
            self.thumbnail_zoom = zoom
            self.invalidate()
        self.sync_thumbnail_mode()

    def sync_thumbnail_mode(self):
        enabled = self.zoom >= self.thumbnail_zoom
        if enabled == self.thumbnails:
            return
        self.begin_geometry_change()
        self.thumbnails = enabled
        self.invalidate()

    def device_positions(self) -> np.ndarray:
        transform = self.viewportTransform()
        return self.positions * (transform.m11(), transform.m22()) + (transform.dx(), transform.dy())

    def current_layer(self) -> QtGui.QPixmap | None:
        if not self.paths:
            return None
        transform = self.viewportTransform()
        size = self.viewport().size()
        key = (self.version, transform.m11(), transform.m22(), transform.dx(), transform.dy(), size.width(), size.height(), self.devicePixelRatioF())
        if self.layer is None or key != self.layer_key:
            self.layer = self.render_layer(size)
            self.layer_key = key
        return self.layer

    def drawBackground(self, painter: QtGui.QPainter, rect: QtCore.QRectF):
        super().drawBackground(painter, rect)
        layer = self.current_layer()
        if layer is None:
            return
        painter.save()
        painter.resetTransform()
        painter.drawPixmap(0, 0, layer)
        painter.restore()

    def render_layer(self, size: QtCore.QSize) -> QtGui.QPixmap:
        ratio = self.devicePixelRatioF()
        layer = QtGui.QPixmap(max(1, math.ceil(size.width() * ratio)), max(1, math.ceil(size.height() * ratio)))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.transparent)
        device = self.device_positions()
        visible = self.visible_rows(device, size)
        chosen = self.choose_image_rows(device, visible, size) if self.thumbnails else NO_ROWS
        paths = [self.paths[row] for row in chosen.tolist()]
        self.wanted_paths = set(paths)
        pixmaps = self.owner.map_thumbnails(paths, self.display_size()) if paths else []
        loaded = [(row, pixmap) for row, pixmap in zip(chosen.tolist(), pixmaps) if pixmap is not None and not pixmap.isNull()]
        dots = np.setdiff1d(visible, np.array([row for row, _ in loaded], dtype=np.int64), assume_unique=True)
        painter = QtGui.QPainter(layer)
        self.paint_dots(painter, device, dots[np.argsort(self.selected[dots], kind="stable")])
        painter.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)
        self.image_rows, self.image_rects = self.paint_images(painter, device, loaded[::-1])
        painter.end()
        return layer

    def visible_rows(self, device: np.ndarray, size: QtCore.QSize) -> np.ndarray:
        margin = self.item_extent() / 2 + dpix(RING) * 2
        x, y = device[:, 0], device[:, 1]
        return np.flatnonzero((x >= -margin) & (x <= size.width() + margin) & (y >= -margin) & (y <= size.height() + margin))

    def choose_image_rows(self, device: np.ndarray, visible: np.ndarray, size: QtCore.QSize) -> np.ndarray:
        if self.image_limit <= 0 or visible.size == 0:
            return NO_ROWS
        ranked = visible[np.lexsort((self.priority[visible], ~self.selected[visible]))]
        cells = np.floor(device[ranked] / max(self.item_extent() * self.image_spacing, 1.0)).astype(np.int64)
        _, first = np.unique(cells, axis=0, return_index=True)
        chosen = ranked[np.sort(first)][: self.image_limit]
        center = np.array([size.width() / 2, size.height() / 2])
        return chosen[np.argsort(((device[chosen] - center) ** 2).sum(axis=1), kind="stable")]

    def sprite(self, index: int) -> QtGui.QPixmap:
        if self.sprite_size != self.point_size():
            self.sprites, self.sprite_size = {}, self.point_size()
        sprite = self.sprites.get(index)
        if sprite is None:
            sprite = self.sprites[index] = self.build_sprite(QtGui.QColor.fromRgba(int(self.color_keys[index >> 2])), bool(index & 1), bool(index & 2))
        return sprite

    def build_sprite(self, color: QtGui.QColor, selected: bool, outlier: bool) -> QtGui.QPixmap:
        side = self.sprite_side()
        ratio = self.devicePixelRatioF()
        sprite = QtGui.QPixmap(math.ceil(side * ratio), math.ceil(side * ratio))
        sprite.setDevicePixelRatio(ratio)
        sprite.fill(Qt.transparent)
        painter = QtGui.QPainter(sprite)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        size = self.point_size()
        frame = QtCore.QRectF((side - size) / 2, (side - size) / 2, size, size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        if size < ROUND_POINT_SIZE:
            painter.drawRect(frame)
        else:
            painter.drawEllipse(frame)
        if selected or outlier:
            self.set_ring_pen(painter, color, selected, outlier)
            painter.drawEllipse(frame.adjusted(-dpix(RING), -dpix(RING), dpix(RING), dpix(RING)))
        painter.end()
        return sprite

    def set_ring_pen(self, painter: QtGui.QPainter, color: QtGui.QColor, selected: bool, outlier: bool) -> None:
        pen = QtGui.QPen(QtGui.QColor(ThemeManager.instance().palette.accent) if selected else color, dpix(RING))
        if outlier:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

    def paint_dots(self, painter: QtGui.QPainter, device: np.ndarray, rows: np.ndarray) -> None:
        if rows.size == 0:
            return
        indexes = (self.color_ids[rows] << 2) | self.selected[rows].astype(np.int64) | (self.outliers[rows].astype(np.int64) << 1)
        sprites = {index: self.sprite(index) for index in np.unique(indexes).tolist()}
        corners = np.rint(device[rows] - self.sprite_side() / 2).astype(np.int64)
        draw = painter.drawPixmap
        for index, x, y in zip(indexes.tolist(), corners[:, 0].tolist(), corners[:, 1].tolist()):
            draw(x, y, sprites[index])

    def paint_images(self, painter: QtGui.QPainter, device: np.ndarray, images: list[tuple[int, QtGui.QPixmap]]) -> tuple[np.ndarray, np.ndarray]:
        extent = self.item_extent()
        rects = []
        for row, pixmap in images:
            factor = extent / max(pixmap.width(), pixmap.height(), 1)
            width, height = pixmap.width() * factor, pixmap.height() * factor
            x, y = device[row]
            target = QtCore.QRectF(x - width / 2, y - height / 2, width, height)
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            self.set_ring_pen(painter, self.colors[row] if row < len(self.colors) else QtGui.QColor(Qt.gray), bool(self.selected[row]), bool(self.outliers[row]))
            painter.drawRect(target)
            rects.append((target.left(), target.top(), target.right(), target.bottom()))
        rows = np.array([row for row, _ in images], dtype=np.int64)
        return rows, (np.array(rects, dtype=np.float64) if rects else NO_RECTS)

    def row_at(self, position: QtCore.QPoint) -> int | None:
        if not self.paths:
            return None
        if self.thumbnails:
            self.current_layer()
        x, y = position.x(), position.y()
        rects = self.image_rects
        if rects.size:
            inside = np.flatnonzero((rects[:, 0] <= x) & (x <= rects[:, 2]) & (rects[:, 1] <= y) & (y <= rects[:, 3]))
            if inside.size:
                return int(self.image_rows[inside[-1]])
        return self.point_at(position)

    def point_at(self, position: QtCore.QPoint) -> int | None:
        if not self.paths:
            return None
        distance = ((self.device_positions() - (position.x(), position.y())) ** 2).sum(axis=1)
        row = int(np.argmin(distance))
        radius = self.dot_size() / 2
        return row if distance[row] <= radius * radius else None

    def rows_in_rect(self, rect: QtCore.QRectF) -> np.ndarray:
        if not self.paths:
            return NO_ROWS
        device = self.device_positions()
        half = self.item_extent() / 2
        x, y = device[:, 0], device[:, 1]
        return np.flatnonzero((x >= rect.left() - half) & (x <= rect.right() + half) & (y >= rect.top() - half) & (y <= rect.bottom() + half))

    def selected_rows(self) -> list[int]:
        return np.flatnonzero(self.selected).tolist()

    def select_rows(self, rows: Iterable[int]):
        wanted = np.fromiter(rows, dtype=np.int64)
        mask = np.zeros(len(self.paths), dtype=bool)
        mask[wanted[(wanted >= 0) & (wanted < mask.size)]] = True
        self.set_selection(mask)

    def set_selection(self, mask: np.ndarray) -> None:
        self.selected = mask
        self.invalidate()

    def select_group(self, group: int):
        self.select_rows(np.flatnonzero(self.group_of == group).tolist())
        self.selection_changed.emit()

    def reveal(self, row: int):
        if 0 <= row < len(self.paths):
            x, y = self.positions[row]
            self.ensureVisible(QtCore.QRectF(x, y, 0.001, 0.001))

    def update_path(self, path: str):
        if path in self.wanted_paths and not self.image_timer.isActive():
            self.image_timer.start()

    def on_rubber_band(self, rect: QtCore.QRect, *_):
        if rect.isNull() or self.press_pos is None or self.band_base.size != len(self.paths):
            return
        mask = self.band_base.copy()
        mask[self.rows_in_rect(QtCore.QRectF(rect))] = True
        if np.array_equal(mask, self.selected):
            return
        self.set_selection(mask)
        self.press_rows = self.selected_rows()
        self.selection_changed.emit()

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        return self.owner.context_for_selection()

    def wheelEvent(self, event: QtGui.QWheelEvent):
        self.owner.hide_hover()
        if event.modifiers() & Qt.ControlModifier:
            event.accept()
            return
        steps = event.angleDelta().y() / 120
        if steps:
            factor = ZOOM_STEP**steps
            self.begin_geometry_change()
            self.scale(factor, factor)
            self.sync_thumbnail_mode()
        event.accept()

    def leaveEvent(self, event):
        self.hover_path = None
        self.owner.hide_hover()
        super().leaveEvent(event)

    def mousePressEvent(self, event: QtGui.QMouseEvent):
        self.hover_path = None
        self.owner.hide_hover()
        if event.button() == Qt.MiddleButton:
            self.pan_origin = event.position().toPoint()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            event.accept()
            return
        position = event.position().toPoint()
        if event.button() == Qt.RightButton:
            self.press_pos = None
            self.select_for_context(position)
            event.accept()
            return
        on_label = isinstance(self.itemAt(position), GroupLabelItem)
        tracking = event.button() == Qt.LeftButton and not on_label
        self.press_pos = position if tracking else None
        self.press_rows = self.selected_rows()
        additive = bool(event.modifiers() & Qt.ControlModifier)
        self.band_base = self.selected.copy() if additive else np.zeros(len(self.paths), dtype=bool)
        super().mousePressEvent(event)

    def select_for_context(self, position: QtCore.QPoint):
        row = self.row_at(position)
        if row is not None and not self.selected[row]:
            self.select_rows([row])
            self.press_rows = self.selected_rows()
            self.selection_changed.emit()

    def mouseMoveEvent(self, event: QtGui.QMouseEvent):
        if self.pan_origin is not None:
            position = event.position().toPoint()
            delta = position - self.pan_origin
            self.pan_origin = position
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - delta.x())
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - delta.y())
            event.accept()
            return
        if event.buttons() == Qt.NoButton:
            self.report_hover(event.position().toPoint())
        super().mouseMoveEvent(event)

    def report_hover(self, position: QtCore.QPoint):
        row = self.point_at(position)
        if row is not None:
            path = self.paths[row]
            self.hover_path = path
            self.owner.show_hover(path, self.viewport().mapToGlobal(position))
        elif self.hover_path is not None:
            self.hover_path = None
            self.owner.hide_hover()

    def mouseReleaseEvent(self, event: QtGui.QMouseEvent):
        if event.button() == Qt.MiddleButton and self.pan_origin is not None:
            self.pan_origin = None
            self.viewport().unsetCursor()
            event.accept()
            return
        super().mouseReleaseEvent(event)
        press_pos, self.press_pos = self.press_pos, None
        if press_pos is None or event.button() != Qt.LeftButton:
            return
        position = event.position().toPoint()
        if (position - press_pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
            self.apply_click(position, event.modifiers())
        if self.selection_mode == "group" and (self.group_of >= 0).any():
            self.select_rows(self.expand_to_groups(self.selected_rows()))
        rows = self.selected_rows()
        if rows != self.press_rows:
            self.press_rows = rows
            self.selection_changed.emit()

    def apply_click(self, position: QtCore.QPoint, modifiers: Qt.KeyboardModifier):
        row = self.row_at(position)
        selected = set(self.selected_rows())
        if modifiers & Qt.ControlModifier:
            if row is None:
                return
            target = set(self.expand_to_groups([row])) if self.selection_mode == "group" else {row}
            selected = selected - target if target <= selected else selected | target
        else:
            selected = set() if row is None else {row}
        self.select_rows(selected)

    def mouseDoubleClickEvent(self, event: QtGui.QMouseEvent):
        row = self.row_at(event.position().toPoint())
        if row is not None:
            self.select_rows([row])
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

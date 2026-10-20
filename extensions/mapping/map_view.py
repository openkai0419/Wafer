from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.qt.commands.bridge import ActionKit
from wafer.qt.commands.command.payload import CommandPayload
from wafer.qt.common.dpi import dpix
from wafer.qt.theme import ThemeManager

from .session import MapResult

SCENE_SIZE = 1000.0
CAPTION_MARGIN = 6
MIN_SIDE = 24
UNSET_GAP = SCENE_SIZE * 0.08
UNSET_SPACING = 20.0
UNSET_PER_ROW = 50
POINT_SIZE = 3.0
MIN_POINT_SIZE = 1.0
ROUND_POINT_SIZE = 3.0
THUMB_SIZE = 64
FIT_IMAGE_SIZE = 32
RING = 2
ZOOM_STEP = 1.25
MIN_IMAGE_SCALE = 0.02
MAX_IMAGE_SCALE = 4.0
FRAME_MARGIN = 0.05
FRAME_MIN_SPAN = SCENE_SIZE * 0.02
IMAGE_LIMIT = 300
IMAGE_SPACING = 0.01
IMAGE_REFRESH_MS = 50
IMAGE_SCAN_MIN = 4096
IMAGE_FILL_TARGET = 0.9
IMAGE_KEEP_SHARE = 0.8
INDEX_CELLS = 256
FULL_REPAINT_SHARE = 0.5
PRIORITY_SEED = 0
NO_ROWS = np.zeros(0, dtype=np.int64)
NO_RECTS = np.zeros((0, 4), dtype=np.float64)


def selection_operation(modifiers: Qt.KeyboardModifier) -> str:
    if modifiers & Qt.ControlModifier:
        return "remove"
    if modifiers & (Qt.ShiftModifier | Qt.AltModifier):
        return "add"
    return "replace"


def combine_selection(base: np.ndarray, target: np.ndarray, operation: str) -> np.ndarray:
    if operation == "add":
        return base | target
    if operation == "remove":
        return base & ~target
    return target.copy()


def cell_keys(points: np.ndarray, cell: float) -> np.ndarray:
    cells = np.floor(points / cell).astype(np.int64)
    return (cells[:, 0] << 32) ^ (cells[:, 1] & 0xFFFFFFFF)


def first_per_cell(points: np.ndarray, cell: float, limit: int) -> np.ndarray:
    scanned = min(len(points), max(limit * 4, IMAGE_SCAN_MIN))
    while True:
        _, first = np.unique(cell_keys(points[:scanned], cell), return_index=True)
        if first.size >= limit or scanned == len(points):
            return np.sort(first)[:limit]
        scanned = min(len(points), scanned * 4)


def inside(points: np.ndarray, box: tuple[float, float, float, float]) -> np.ndarray:
    left, top, right, bottom = box
    x, y = points[:, 0], points[:, 1]
    return (x >= left) & (x <= right) & (y >= top) & (y <= bottom)


class PointIndex:
    def __init__(self, positions: np.ndarray):
        self.positions = positions
        self.low = positions.min(axis=0) if len(positions) else np.zeros(2)
        span = positions.max(axis=0) - self.low if len(positions) else np.ones(2)
        self.cell = np.maximum(span, 1e-9) / INDEX_CELLS
        columns, rows = self.cells_of(positions)
        ids = (rows * INDEX_CELLS + columns).astype(np.uint16)
        self.order = np.argsort(ids, kind="stable")
        self.starts = np.zeros(INDEX_CELLS * INDEX_CELLS + 1, dtype=np.int64)
        np.cumsum(np.bincount(ids, minlength=INDEX_CELLS * INDEX_CELLS), out=self.starts[1:])

    def cells_of(self, points: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        cells = np.clip(((points - self.low) / self.cell).astype(np.int64), 0, INDEX_CELLS - 1)
        return cells[:, 0], cells[:, 1]

    def spans(self, box: tuple[float, float, float, float]) -> list[tuple[int, int]]:
        if box[2] < self.low[0] or box[3] < self.low[1]:
            return []
        (left, right), (top, bottom) = (cells.tolist() for cells in self.cells_of(np.array([box[:2], box[2:]])))
        return [(int(self.starts[row * INDEX_CELLS + left]), int(self.starts[row * INDEX_CELLS + right + 1])) for row in range(top, bottom + 1)]

    def count(self, box: tuple[float, float, float, float]) -> int:
        return sum(end - start for start, end in self.spans(box))

    def rows_near(self, boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
        slots = [np.arange(start, end) for box in boxes for start, end in self.spans(box) if end > start]
        if not slots:
            return NO_ROWS
        slots = np.concatenate(slots)
        return self.order[slots if len(boxes) == 1 else np.unique(slots)]

    def rows_in(self, box: tuple[float, float, float, float]) -> np.ndarray:
        rows = self.rows_near([box])
        return rows[inside(self.positions[rows], box)]


@dataclass(frozen=True)
class Projection:
    scale: tuple[float, float]
    offset: tuple[float, float]

    def pixels(self, points: np.ndarray) -> np.ndarray:
        return points * self.scale + self.offset

    def scene_box(self, left: float, top: float, right: float, bottom: float) -> tuple[float, float, float, float]:
        (sx, sy), (ox, oy) = self.scale, self.offset
        return ((left - ox) / sx, (top - oy) / sy, (right - ox) / sx, (bottom - oy) / sy)


def color_keys(colors: list[QtGui.QColor], count: int) -> np.ndarray:
    fallback = QtGui.QColor(ThemeManager.instance().palette.text_secondary).rgba()
    rgba = {id(color): color.rgba() for color in {id(color): color for color in colors}.values()}
    keys = np.full(count, fallback, dtype=np.int64)
    known = min(count, len(colors))
    keys[:known] = np.fromiter((rgba[id(color)] for color in colors[:known]), dtype=np.int64, count=known)
    return keys


def scene_positions(result: MapResult) -> np.ndarray:
    positions = np.asarray(result.positions, dtype=np.float64).reshape(-1, 2) * SCENE_SIZE
    unset = np.flatnonzero(result.unset)
    placed = positions[~np.asarray(result.unset, dtype=bool)]
    bottom = max(SCENE_SIZE, float(np.nanmax(placed[:, 1]))) if np.isfinite(placed).any() else SCENE_SIZE
    slots = np.arange(unset.size)
    positions[unset, 0] = (slots % UNSET_PER_ROW) * UNSET_SPACING
    positions[unset, 1] = bottom + UNSET_GAP + (slots // UNSET_PER_ROW) * UNSET_SPACING
    return np.nan_to_num(positions)


@dataclass(frozen=True)
class ImagePlan:
    images: list[tuple[int, QtGui.QPixmap]]
    rows: np.ndarray
    rects: np.ndarray
    keys: np.ndarray

    @classmethod
    def of(cls, images: list[tuple[int, QtGui.QPixmap]], positions: np.ndarray, projection: Projection, extent: float) -> ImagePlan:
        rows = np.fromiter((row for row, _ in images), dtype=np.int64, count=len(images))
        keys = np.fromiter((pixmap.cacheKey() for _, pixmap in images), dtype=np.int64, count=len(images))
        if not images:
            return cls(images, rows, NO_RECTS, keys)
        sizes = np.array([(pixmap.width(), pixmap.height()) for _, pixmap in images], dtype=np.float64)
        spans = np.rint(sizes * (extent / np.maximum(sizes.max(axis=1), 1.0))[:, None])
        corners = np.floor(projection.pixels(positions[rows]) - spans / 2 + 0.5)
        return cls(images, rows, np.hstack([corners, corners + spans]), keys)


def changed_images(rows: np.ndarray, keys: np.ndarray, rects: np.ndarray, plan: ImagePlan, raised: int | None) -> np.ndarray | None:
    kept, staying = np.isin(rows, plan.rows), np.isin(plan.rows, rows)
    if not np.array_equal(rows[kept & (rows != raised)], plan.rows[staying & (plan.rows != raised)]):
        return None
    before = dict(zip(rows.tolist(), keys.tolist()))
    after = dict(zip(plan.rows.tolist(), plan.keys.tolist()))
    gone = np.fromiter((after.get(row) != key for row, key in before.items()), dtype=bool, count=len(before))
    new = np.fromiter((before.get(row) != key or row == raised for row, key in after.items()), dtype=bool, count=len(after))
    return np.vstack([rects[gone].reshape(-1, 4), plan.rects[new].reshape(-1, 4)])


def touching(items: np.ndarray, boxes: np.ndarray) -> np.ndarray:
    hit = np.zeros(len(items), dtype=bool)
    if items.size == 0 or boxes.size == 0:
        return hit
    low, high = items[:, :2], items[:, -2:]
    near = np.flatnonzero((low[:, 0] < boxes[:, 2].max()) & (high[:, 0] > boxes[:, 0].min()) & (low[:, 1] < boxes[:, 3].max()) & (high[:, 1] > boxes[:, 1].min()))
    low, high = low[near], high[near]
    inside = np.zeros(near.size, dtype=bool)
    for left, top, right, bottom in boxes.tolist():
        inside |= (low[:, 0] < right) & (high[:, 0] > left) & (low[:, 1] < bottom) & (high[:, 1] > top)
    hit[near[inside]] = True
    return hit


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
        palette = ThemeManager.instance().palette
        self.caption = QtWidgets.QLabel(self.viewport())
        self.caption.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.caption.setStyleSheet(f"QLabel {{ color: {palette.text_secondary}; background: {palette.bg_elevated}; border-radius: {dpix(4)}px; padding: {dpix(2)}px {dpix(6)}px; }}")
        self.caption.hide()
        self.paths: list[str] = []
        self.rows_by_path: dict[str, int] = {}
        self.colors: list[QtGui.QColor] = []
        self.positions = np.zeros((0, 2), dtype=np.float64)
        self.selected = np.zeros(0, dtype=bool)
        self.outliers = np.zeros(0, dtype=bool)
        self.group_of = np.zeros(0, dtype=np.int32)
        self.index = PointIndex(self.positions)
        self.priority = NO_ROWS
        self.by_priority = NO_ROWS
        self.depth = NO_ROWS
        self.depth_top = 0
        self.image_choice = NO_ROWS
        self.image_cell = 0.0
        self.rank_hint = 0
        self.color_keys = NO_ROWS
        self.color_ids = NO_ROWS
        self.sprites: dict[int, QtGui.QPixmap] = {}
        self.sprite_size: tuple[float, float] = (0.0, 0.0)
        self.layer: QtGui.QPixmap | None = None
        self.layer_key: tuple | None = None
        self.layer_anchor = (0.0, 0.0)
        self.version = 0
        self.image_epoch = 0
        self.image_rows = NO_ROWS
        self.image_rects = NO_RECTS
        self.image_pixels = NO_RECTS
        self.image_keys = NO_ROWS
        self.wanted_paths: set[str] = set()
        self.image_limit = IMAGE_LIMIT
        self.image_spacing = IMAGE_SPACING
        self.image_cap = 0.0
        self.point_base = POINT_SIZE
        self.fit_scale = 1.0
        self.thumbnails = True
        self.image_scale = 1.0
        self.selection_mode = "single"
        self.hover_path: str | None = None
        self.pan_origin: QtCore.QPoint | None = None
        self.press_pos: QtCore.QPoint | None = None
        self.press_rows: list[int] = []
        self.band_base = np.zeros(0, dtype=bool)
        self.band_operation = "replace"
        self.image_timer = QtCore.QTimer(self)
        self.image_timer.setSingleShot(True)
        self.image_timer.setInterval(IMAGE_REFRESH_MS)
        self.image_timer.timeout.connect(self.refresh_images)
        self.viewport().setMouseTracking(True)
        self.rubberBandChanged.connect(self.on_rubber_band)

    @property
    def zoom(self) -> float:
        return self.transform().m11() / self.fit_scale if self.fit_scale else 1.0

    def item_extent(self) -> float:
        return dpix(self.display_size()) if self.thumbnails else self.dot_size()

    def point_size(self) -> float:
        return MIN_POINT_SIZE if self.point_base <= MIN_POINT_SIZE else float(dpix(self.point_base))

    def set_point_size(self, size: float) -> None:
        size = max(float(size), MIN_POINT_SIZE)
        if size != self.point_base:
            self.point_base = size
            self.invalidate()

    def dot_size(self) -> float:
        return self.point_size() + dpix(RING) * 2

    def sprite_side(self) -> float:
        return self.dot_size() + dpix(RING) * 2

    def display_size(self) -> float:
        size = FIT_IMAGE_SIZE * self.image_scale * self.zoom
        return min(size, self.image_cap) if self.image_cap > 0 else size

    def set_image_cap(self, cap: float) -> None:
        if cap != self.image_cap:
            self.image_cap = max(float(cap), 0.0)
            self.invalidate()

    def invalidate(self) -> None:
        self.version += 1
        self.viewport().update()

    def refresh_images(self) -> None:
        self.image_epoch += 1
        self.viewport().update()

    def set_image_scale(self, scale: float):
        scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE)
        if scale == self.image_scale:
            return
        self.image_scale = scale
        self.invalidate()

    def set_image_limit(self, limit: int) -> None:
        if limit != self.image_limit:
            self.image_limit = max(int(limit), 0)
            self.forget_image_choice()
            self.invalidate()

    def minimumSizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(dpix(MIN_SIDE), dpix(MIN_SIDE))

    def set_caption(self, text: str) -> None:
        self.caption.setText(text)
        self.caption.setVisible(bool(text))
        self.place_caption()

    def place_caption(self) -> None:
        self.caption.adjustSize()
        margin = dpix(CAPTION_MARGIN)
        self.caption.move(margin, self.viewport().height() - self.caption.height() - margin)

    def resizeEvent(self, event: QtGui.QResizeEvent) -> None:
        super().resizeEvent(event)
        self.place_caption()

    def set_image_spacing(self, spacing: float) -> None:
        if spacing != self.image_spacing:
            self.image_spacing = max(float(spacing), 0.01)
            self.forget_image_choice()
            self.invalidate()

    def forget_image_choice(self) -> None:
        self.image_choice, self.image_cell, self.rank_hint = NO_ROWS, 0.0, 0

    def set_selection_mode(self, mode: str):
        self.selection_mode = "group" if mode == "group" else "single"

    def row_mask(self, rows: Iterable[int]) -> np.ndarray:
        wanted = np.fromiter(rows, dtype=np.int64)
        mask = np.zeros(len(self.paths), dtype=bool)
        mask[wanted[(wanted >= 0) & (wanted < mask.size)]] = True
        return mask

    def with_groups(self, mask: np.ndarray) -> np.ndarray:
        if self.selection_mode != "group" or self.group_of.size != mask.size:
            return mask
        groups = np.unique(self.group_of[mask])
        groups = groups[groups >= 0]
        return mask | np.isin(self.group_of, groups) if groups.size else mask

    def expand_to_groups(self, rows: Iterable[int]) -> list[int]:
        return np.flatnonzero(self.with_groups(self.row_mask(rows))).tolist()

    def clear_map(self):
        self.scene().clear()
        self.paths, self.rows_by_path, self.colors = [], {}, []
        self.positions = np.zeros((0, 2), dtype=np.float64)
        self.index = PointIndex(self.positions)
        self.selected = np.zeros(0, dtype=bool)
        self.priority = self.by_priority = self.depth = self.color_keys = self.color_ids = NO_ROWS
        self.image_rows, self.image_rects, self.image_pixels, self.image_keys, self.wanted_paths = NO_ROWS, NO_RECTS, NO_RECTS, NO_ROWS, set()
        self.forget_image_choice()
        self.sprites = {}
        self.invalidate()

    def raised_paths(self) -> list[tuple[str, int]]:
        return [(self.paths[row], int(self.depth[row])) for row in np.flatnonzero(self.depth > 0).tolist()]

    def show_result(self, result: MapResult, colors: list[QtGui.QColor], keep_view: bool):
        raised = self.raised_paths()
        self.clear_map()
        count = len(result.paths)
        self.paths = list(result.paths)
        self.rows_by_path = {path: row for row, path in enumerate(self.paths)}
        self.outliers = np.asarray(result.outliers, dtype=bool)
        self.positions = scene_positions(result)
        self.index = PointIndex(self.positions)
        self.selected = np.zeros(count, dtype=bool)
        self.by_priority = np.random.default_rng(PRIORITY_SEED).permutation(count)
        self.priority = np.empty(count, dtype=np.int64)
        self.priority[self.by_priority] = np.arange(count)
        self.depth = -self.priority
        for path, depth in raised:
            row = self.rows_by_path.get(path)
            if row is not None:
                self.depth[row] = depth
        self.set_groups(result, colors)
        core = QtCore.QRectF(0, 0, SCENE_SIZE, SCENE_SIZE)
        rect = core
        if count:
            low, high = self.positions.min(axis=0), self.positions.max(axis=0)
            rect = rect.united(QtCore.QRectF(QtCore.QPointF(*low), QtCore.QPointF(*high)))
        margin = SCENE_SIZE * 0.05
        self.scene().setSceneRect(rect.adjusted(-margin, -margin, margin, margin))
        if not keep_view:
            self.fitInView(core.adjusted(-margin, -margin, margin, margin), Qt.KeepAspectRatio)
            self.fit_scale = self.transform().m11()
        self.invalidate()

    def set_groups(self, result: MapResult, colors: list[QtGui.QColor]) -> None:
        count = len(self.paths)
        self.colors = colors
        self.group_of = result.labels if result.labels is not None else np.full(count, -1, dtype=np.int32)
        self.color_keys, self.color_ids = np.unique(color_keys(colors, count), return_inverse=True)
        self.sprites = {}
        self.invalidate()

    def set_thumbnails_visible(self, visible: bool) -> None:
        if bool(visible) == self.thumbnails:
            return
        self.thumbnails = bool(visible)
        self.invalidate()

    def device_positions(self, rows: np.ndarray | None = None) -> np.ndarray:
        transform = self.viewportTransform()
        points = self.positions if rows is None else self.positions[rows]
        return points * (transform.m11(), transform.m22()) + (transform.dx(), transform.dy())

    def device_projection(self) -> Projection:
        transform = self.viewportTransform()
        return Projection((transform.m11(), transform.m22()), (transform.dx(), transform.dy()))

    def view_box(self, share: float = 1.0) -> tuple[float, float, float, float]:
        size = self.viewport().size()
        margin_x, margin_y = (np.array([size.width(), size.height()]) * (1 - share) / 2).tolist()
        if share >= 1.0:
            margin_x = margin_y = -(self.item_extent() / 2 + dpix(RING) * 2)
        return self.device_projection().scene_box(margin_x, margin_y, size.width() - margin_x, size.height() - margin_y)

    def current_layer(self) -> QtGui.QPixmap | None:
        if not self.paths:
            return None
        transform = self.viewportTransform()
        size = self.viewport().size()
        ratio = self.devicePixelRatioF()
        frame = (self.version, transform.m11(), transform.m22(), size.width(), size.height(), ratio)
        origin = (transform.dx(), transform.dy())
        key = (frame, origin, self.image_epoch)
        if self.layer is not None and key == self.layer_key:
            return self.layer
        view = self.view_box()
        chosen = self.choose_image_rows(view) if self.thumbnails else NO_ROWS
        paths = [self.paths[row] for row in chosen.tolist()]
        self.wanted_paths = set(paths)
        pixmaps = self.owner.map_thumbnails(paths, self.display_size()) if paths else []
        loaded = [(row, pixmap) for row, pixmap in zip(chosen.tolist(), pixmaps) if pixmap is not None and not pixmap.isNull()]
        images, raised = self.stack_images(loaded, size)
        reusable = self.layer is not None and self.layer_key is not None and self.layer_key[0] == frame
        shift = (round(origin[0] * ratio - self.layer_anchor[0]), round(origin[1] * ratio - self.layer_anchor[1])) if reusable else None
        anchor = (self.layer_anchor[0] + shift[0], self.layer_anchor[1] + shift[1]) if shift else (origin[0] * ratio, origin[1] * ratio)
        projection = Projection((transform.m11() * ratio, transform.m22() * ratio), anchor)
        plan = ImagePlan.of(images, self.positions, projection, self.item_extent() * ratio)
        if shift is None or not self.update_layer(shift, projection, view, plan, raised):
            self.layer = self.render_layer(size, ratio, projection, view, plan)
        self.layer_key, self.layer_anchor = key, anchor
        self.image_rows, self.image_pixels, self.image_keys = plan.rows, plan.rects, plan.keys
        self.image_rects = plan.rects / ratio
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

    def render_layer(self, size: QtCore.QSize, ratio: float, projection: Projection, view: tuple[float, float, float, float], plan: ImagePlan) -> QtGui.QPixmap:
        layer = QtGui.QPixmap(max(1, math.ceil(size.width() * ratio)), max(1, math.ceil(size.height() * ratio)))
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.transparent)
        self.paint_layer(layer, projection, self.index.rows_in(view), plan)
        return layer

    def update_layer(self, shift: tuple[int, int], projection: Projection, view: tuple[float, float, float, float], plan: ImagePlan, raised: int | None) -> bool:
        layer = self.layer
        bounds = layer.rect()
        if abs(shift[0]) >= bounds.width() or abs(shift[1]) >= bounds.height():
            return False
        damage = changed_images(self.image_rows, self.image_keys, self.image_pixels + np.tile(shift, 2), plan, raised)
        if damage is None:
            return False
        region = QtGui.QRegion(bounds) - QtGui.QRegion(bounds.translated(*shift)) if any(shift) else QtGui.QRegion()
        margin = math.ceil(self.ring_pixels()) + 1
        for left, top, right, bottom in damage.astype(np.int64).tolist():
            region += QtCore.QRect(left - margin, top - margin, right - left + margin * 2, bottom - top + margin * 2)
        region &= QtGui.QRegion(bounds)
        if sum(rect.width() * rect.height() for rect in region) > bounds.width() * bounds.height() * FULL_REPAINT_SHARE:
            return False
        if any(shift):
            layer.scroll(shift[0], shift[1], bounds)
        if not region.isEmpty():
            boxes = np.array([(rect.left(), rect.top(), rect.right() + 1, rect.bottom() + 1) for rect in region], dtype=np.float64)
            half = self.sprite_pixels() / 2
            reach = boxes + (-half, -half, half, half)
            near = self.index.rows_near([projection.scene_box(*box) for box in reach.tolist()])
            near = near[inside(self.positions[near], view)]
            dots = near[touching(projection.pixels(self.positions[near]), reach)]
            self.paint_layer(layer, projection, dots, plan, region, boxes)
        return True

    def paint_layer(self, layer: QtGui.QPixmap, projection: Projection, dots: np.ndarray, plan: ImagePlan, region: QtGui.QRegion | None = None, boxes: np.ndarray | None = None) -> None:
        dots = dots[~np.isin(dots, plan.rows)]
        images = np.arange(len(plan.images))
        ratio = layer.devicePixelRatio()
        layer.setDevicePixelRatio(1.0)
        painter = QtGui.QPainter(layer)
        if region is not None:
            ring = self.ring_pixels()
            images = images[touching(plan.rects, boxes + (-ring, -ring, ring, ring))]
            painter.setClipRegion(region)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
            painter.fillRect(region.boundingRect(), Qt.transparent)
            painter.setCompositionMode(QtGui.QPainter.CompositionMode_SourceOver)
        self.paint_dots(painter, projection, dots[np.argsort(self.selected[dots], kind="stable")])
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        self.paint_images(painter, [plan.images[index] for index in images.tolist()], plan.rects[images])
        painter.end()
        layer.setDevicePixelRatio(ratio)

    def choose_image_rows(self, view: tuple[float, float, float, float]) -> np.ndarray:
        target = max(1, round(self.image_limit * IMAGE_FILL_TARGET))
        if self.image_limit <= 0 or not self.index.count(view):
            self.forget_image_choice()
            return NO_ROWS
        cell = max(self.item_extent() * self.image_spacing, 1.0) / self.viewportTransform().m11()
        middle = self.view_box(IMAGE_KEEP_SHARE)
        kept = self.image_choice[inside(self.positions[self.image_choice], middle)] if self.image_cell == cell else NO_ROWS
        chosen = kept
        if kept.size < target:
            chosen = np.concatenate([kept, self.rows_by_rank(view, cell, kept, middle, target - kept.size)])
        self.image_choice, self.image_cell = chosen, cell
        return chosen

    def rows_by_rank(self, view: tuple[float, float, float, float], cell: float, kept: np.ndarray, middle: tuple[float, float, float, float], count: int) -> np.ndarray:
        kept_cells = cell_keys(self.positions[kept], cell)
        visible = self.index.count(view)
        scanned = min(len(self.paths), max(self.rank_hint * 2, IMAGE_SCAN_MIN))
        while True:
            exhaustive = scanned >= visible or scanned >= len(self.paths)
            if exhaustive:
                ranked = self.index.rows_in(view)
                ranked = ranked[np.argsort(self.priority[ranked], kind="stable")]
            else:
                ranked = self.by_priority[:scanned]
                ranked = ranked[inside(self.positions[ranked], view)]
            chosen = ranked[first_per_cell(self.positions[ranked], cell, len(ranked))]
            if kept.size:
                chosen = chosen[~inside(self.positions[chosen], middle) & ~np.isin(cell_keys(self.positions[chosen], cell), kept_cells)]
            chosen = chosen[:count]
            if chosen.size >= count or exhaustive:
                self.rank_hint = int(self.priority[chosen[-1]]) + 1 if chosen.size >= count else len(self.paths)
                return chosen
            scanned = min(len(self.paths), scanned * 4)

    def stack_images(self, images: list[tuple[int, QtGui.QPixmap]], size: QtCore.QSize) -> tuple[list[tuple[int, QtGui.QPixmap]], int | None]:
        if not images:
            return images, None
        rows = np.fromiter((row for row, _ in images), dtype=np.int64, count=len(images))
        center = np.array([size.width() / 2, size.height() / 2])
        front = int(rows[np.argmin(((self.device_positions(rows) - center) ** 2).sum(axis=1))])
        raised = None
        if not (self.depth_top and self.depth[front] == self.depth_top):
            self.depth_top += 1
            self.depth[front] = self.depth_top
            raised = front
        return [images[index] for index in np.argsort(self.depth[rows], kind="stable").tolist()], raised

    def sprite(self, index: int) -> QtGui.QPixmap:
        if self.sprite_size != (self.point_size(), self.devicePixelRatioF()):
            self.sprites, self.sprite_size = {}, (self.point_size(), self.devicePixelRatioF())
        sprite = self.sprites.get(index)
        if sprite is None:
            sprite = self.sprites[index] = self.build_sprite(QtGui.QColor.fromRgba(int(self.color_keys[index >> 2])), bool(index & 1), bool(index & 2))
        return sprite

    def sprite_pixels(self) -> int:
        return math.ceil(self.sprite_side() * self.devicePixelRatioF())

    def ring_pixels(self) -> float:
        return dpix(RING) * self.devicePixelRatioF()

    def build_sprite(self, color: QtGui.QColor, selected: bool, outlier: bool) -> QtGui.QPixmap:
        side = self.sprite_side()
        ratio = self.devicePixelRatioF()
        sprite = QtGui.QPixmap(self.sprite_pixels(), self.sprite_pixels())
        sprite.setDevicePixelRatio(ratio)
        sprite.fill(Qt.transparent)
        painter = QtGui.QPainter(sprite)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        size = self.point_size()
        frame = QtCore.QRectF((side - size) / 2, (side - size) / 2, size, size)
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        if outlier or size < ROUND_POINT_SIZE:
            painter.drawRect(frame)
        else:
            painter.drawEllipse(frame)
        if selected:
            self.set_ring_pen(painter, color, selected, width=dpix(RING))
            painter.drawEllipse(frame.adjusted(-dpix(RING), -dpix(RING), dpix(RING), dpix(RING)))
        painter.end()
        sprite.setDevicePixelRatio(1.0)
        return sprite

    def set_ring_pen(self, painter: QtGui.QPainter, color: QtGui.QColor, selected: bool, dashed: bool = False, width: float = 0.0) -> None:
        pen = QtGui.QPen(QtGui.QColor(ThemeManager.instance().palette.accent) if selected else color, width or self.ring_pixels())
        if dashed:
            pen.setStyle(Qt.DashLine)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)

    def paint_dots(self, painter: QtGui.QPainter, projection: Projection, rows: np.ndarray) -> None:
        if rows.size == 0:
            return
        indexes = (self.color_ids[rows] << 2) | self.selected[rows].astype(np.int64) | (self.outliers[rows].astype(np.int64) << 1)
        sprites = {index: self.sprite(index) for index in np.unique(indexes).tolist()}
        corners = np.floor(projection.pixels(self.positions[rows]) - self.sprite_pixels() / 2 + 0.5).astype(np.int64)
        draw = painter.drawPixmap
        for index, x, y in zip(indexes.tolist(), corners[:, 0].tolist(), corners[:, 1].tolist()):
            draw(x, y, sprites[index])

    def paint_images(self, painter: QtGui.QPainter, images: list[tuple[int, QtGui.QPixmap]], rects: np.ndarray) -> None:
        for (row, pixmap), (left, top, right, bottom) in zip(images, rects.tolist()):
            target = QtCore.QRectF(left, top, right - left, bottom - top)
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
            self.set_ring_pen(painter, self.colors[row] if row < len(self.colors) else QtGui.QColor(Qt.gray), bool(self.selected[row]), bool(self.outliers[row]))
            painter.drawRect(target)

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
        radius = self.dot_size() / 2
        x, y = position.x(), position.y()
        rows = self.index.rows_near([self.device_projection().scene_box(x - radius, y - radius, x + radius, y + radius)])
        if rows.size == 0:
            return None
        distance = ((self.device_positions(rows) - (x, y)) ** 2).sum(axis=1)
        nearest = int(np.argmin(distance))
        return int(rows[nearest]) if distance[nearest] <= radius * radius else None

    def rows_in_rect(self, rect: QtCore.QRectF) -> np.ndarray:
        half = self.item_extent() / 2
        box = (rect.left() - half, rect.top() - half, rect.right() + half, rect.bottom() + half)
        rows = self.index.rows_near([self.device_projection().scene_box(*box)])
        return rows[inside(self.device_positions(rows), box)]

    def selected_rows(self) -> list[int]:
        return np.flatnonzero(self.selected).tolist()

    def select_rows(self, rows: Iterable[int]):
        self.set_selection(self.row_mask(rows))

    def set_selection(self, mask: np.ndarray) -> None:
        self.selected = mask
        self.invalidate()

    def frame_selection(self) -> None:
        if not self.paths:
            return
        points = self.positions[self.selected] if self.selected.any() else self.positions
        low, high = points.min(axis=0), points.max(axis=0)
        center, span = (low + high) / 2, np.maximum(high - low, FRAME_MIN_SPAN) * (1 + FRAME_MARGIN * 2)
        self.fitInView(QtCore.QRectF(center[0] - span[0] / 2, center[1] - span[1] / 2, span[0], span[1]), Qt.KeepAspectRatio)
        self.invalidate()

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
        mask = combine_selection(self.band_base, self.with_groups(self.row_mask(self.rows_in_rect(QtCore.QRectF(rect)).tolist())), self.band_operation)
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
            self.scale(factor, factor)
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
        tracking = event.button() == Qt.LeftButton
        self.press_pos = position if tracking else None
        self.press_rows = self.selected_rows()
        self.band_operation = selection_operation(event.modifiers())
        self.band_base = self.selected.copy()
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
        rows = self.selected_rows()
        if rows != self.press_rows:
            self.press_rows = rows
            self.selection_changed.emit()

    def apply_click(self, position: QtCore.QPoint, modifiers: Qt.KeyboardModifier):
        row = self.row_at(position)
        operation = selection_operation(modifiers)
        if row is None:
            if operation == "replace":
                self.set_selection(np.zeros(len(self.paths), dtype=bool))
            return
        target = self.with_groups(self.row_mask([row]))
        if operation == "remove":
            operation = "remove" if self.selected[target].all() else "add"
        self.set_selection(combine_selection(self.selected, target, operation))

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

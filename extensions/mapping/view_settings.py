from __future__ import annotations

import math
import threading
from typing import Any

from PySide6 import QtCore

from wafer.core.logs import AppLogger
from wafer.qt.common.dispatcher import Dispatcher
from wafer.qt.common.thread import utility_pool

from .map_view import MAX_IMAGE_SCALE, MIN_IMAGE_SCALE
from .params import DEFAULT_SUBGROUP_SIZE, SUBGROUP_SIZE, Grouping, TrainParams, ViewParams, fitted, param_specs
from .space import load_grouping, save_grouping

VIEW_PARAMS = tuple(name for name, _spec, _default in param_specs(ViewParams))
RELAYOUT_PARAMS = frozenset({"outlier_percent"})
SELECTION_MODES = ("single", "group")
DEFAULT_IMAGE_CAP = ViewParams().hover_size
DEFAULT_SPACING = TrainParams().min_dist
SPACING_RANGE = (0.0, 1.0)
SAVE_DELAY_MS = 500


def clamped_scale(scale) -> float:
    return min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE) if isinstance(scale, (int, float)) and math.isfinite(scale) else 1.0


class ViewSettings(QtCore.QObject):
    changed = QtCore.Signal(frozenset)
    _instance: ViewSettings | None = None

    @classmethod
    def instance(cls) -> ViewSettings:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.params = ViewParams()

    def set_params(self, params: ViewParams) -> None:
        changed = frozenset(name for name in VIEW_PARAMS if getattr(params, name) != getattr(self.params, name))
        if changed:
            self.params = params
            self.changed.emit(changed)

    def to_dict(self) -> dict[str, Any]:
        return {"params": self.params.to_dict()}

    def load(self, state: dict[str, Any]) -> None:
        params = state.get("params")
        self.set_params(ViewParams.from_dict(params) if isinstance(params, dict) else ViewParams())

    def apply(self, view, host) -> None:
        params = self.params
        host.set_cache_limit(params.thumbnail_cache)
        host.set_hover_size(params.hover_size)
        view.set_image_limit(params.max_images)
        view.set_image_spacing(params.image_spacing)
        view.set_image_cap(params.hover_size or DEFAULT_IMAGE_CAP)
        view.set_point_size(params.point_size)


class TabSettings(QtCore.QObject):
    changed = QtCore.Signal(frozenset)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.thumbnails_shown = True
        self.selection_mode = "group"
        self.spacing = DEFAULT_SPACING
        self.subgroup_size = DEFAULT_SUBGROUP_SIZE
        self.image_scale = 1.0

    def set_thumbnails_shown(self, shown: bool) -> None:
        if bool(shown) != self.thumbnails_shown:
            self.thumbnails_shown = bool(shown)
            self.changed.emit(frozenset({"thumbnails"}))

    def set_selection_mode(self, mode: str) -> None:
        mode = mode if mode in SELECTION_MODES else "single"
        if mode != self.selection_mode:
            self.selection_mode = mode
            self.changed.emit(frozenset({"selection_mode"}))

    def set_spacing(self, spacing: float) -> None:
        low, high = SPACING_RANGE
        spacing = round(min(max(float(spacing), low), high), 2) if isinstance(spacing, (int, float)) and math.isfinite(spacing) else DEFAULT_SPACING
        if spacing != self.spacing:
            self.spacing = spacing
            self.changed.emit(frozenset({"spacing"}))

    def set_subgroup_size(self, size: float) -> None:
        size = fitted(size, SUBGROUP_SIZE, DEFAULT_SUBGROUP_SIZE)
        if size != self.subgroup_size:
            self.subgroup_size = size
            self.changed.emit(frozenset({"subgroup_size"}))

    def set_image_scale(self, scale: float) -> None:
        scale = clamped_scale(scale)
        if scale != self.image_scale:
            self.image_scale = scale
            self.changed.emit(frozenset({"image_scale"}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "thumbnails": self.thumbnails_shown,
            "selection_mode": self.selection_mode,
            "spacing": self.spacing,
            "subgroup_size": self.subgroup_size,
            "image_scale": self.image_scale,
        }

    def load(self, state: dict[str, Any]) -> None:
        self.set_thumbnails_shown(state.get("thumbnails", True) is not False)
        self.set_selection_mode(state.get("selection_mode", "group"))
        self.set_spacing(state.get("spacing", DEFAULT_SPACING))
        self.set_subgroup_size(state.get("subgroup_size", DEFAULT_SUBGROUP_SIZE))
        self.set_image_scale(state.get("image_scale", 1.0))

    def apply(self, view) -> None:
        view.set_thumbnails_visible(self.thumbnails_shown)
        view.set_selection_mode(self.selection_mode)
        view.set_image_scale(self.image_scale)


class GroupingStore(QtCore.QObject):
    changed = QtCore.Signal(str)
    _instance: GroupingStore | None = None

    @classmethod
    def instance(cls) -> GroupingStore:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.lock = threading.Lock()
        self.save_lock = threading.Lock()
        self.by_db: dict[str, Grouping] = {}
        self.unsaved: set[str] = set()
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        self.save_timer = QtCore.QTimer(self)
        self.save_timer.setSingleShot(True)
        self.save_timer.setInterval(SAVE_DELAY_MS)
        self.save_timer.timeout.connect(self.save_later)
        QtCore.QCoreApplication.instance().aboutToQuit.connect(self.save_pending)

    def get(self, db_name: str) -> Grouping:
        with self.lock:
            cached = self.by_db.get(db_name)
        if cached is not None:
            return cached
        loaded = load_grouping(db_name) if db_name else Grouping()
        with self.lock:
            return self.by_db.setdefault(db_name, loaded)

    def set(self, db_name: str, grouping: Grouping) -> None:
        grouping = grouping.normalized()
        if not db_name or grouping == self.get(db_name):
            return
        with self.lock:
            self.by_db[db_name] = grouping
        self.unsaved.add(db_name)
        self.save_timer.start()
        self.changed.emit(db_name)

    def take_unsaved(self) -> list[str]:
        db_names, self.unsaved = sorted(self.unsaved), set()
        return db_names

    def save_later(self) -> None:
        db_names = self.take_unsaved()
        self.dispatcher.post(lambda: self.save(db_names))

    def save_pending(self) -> None:
        self.save_timer.stop()
        self.save(self.take_unsaved())

    def save(self, db_names: list[str]) -> None:
        with self.save_lock:
            for db_name in db_names:
                try:
                    save_grouping(db_name, self.get(db_name))
                except Exception as e:
                    AppLogger.warning(f"[Mapping] Saving the groups of {db_name} failed; they are kept until the app closes", exc=e)

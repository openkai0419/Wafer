from __future__ import annotations

import math
import threading
from typing import Any

from PySide6 import QtCore

from .map_view import MAX_IMAGE_SCALE, MIN_IMAGE_SCALE
from .params import Grouping, ViewParams, param_specs
from .space import load_grouping, save_grouping

VIEW_PARAMS = tuple(name for name, _spec, _default in param_specs(ViewParams))
TOOLBAR_PARAMS = frozenset({"subgroup_size"})
RELAYOUT_PARAMS = frozenset({"outlier_percent", "label_terms"})
SELECTION_MODES = ("single", "group")
DEFAULT_IMAGE_CAP = ViewParams().hover_size


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
        self.labels_shown = True
        self.thumbnails_shown = True
        self.image_scale = 1.0
        self.selection_mode = "single"

    def set_params(self, params: ViewParams) -> None:
        changed = frozenset(name for name in VIEW_PARAMS if getattr(params, name) != getattr(self.params, name))
        if changed:
            self.params = params
            self.changed.emit(changed)

    def set_labels_shown(self, shown: bool) -> None:
        if bool(shown) != self.labels_shown:
            self.labels_shown = bool(shown)
            self.changed.emit(frozenset({"labels"}))

    def set_thumbnails_shown(self, shown: bool) -> None:
        if bool(shown) != self.thumbnails_shown:
            self.thumbnails_shown = bool(shown)
            self.changed.emit(frozenset({"thumbnails"}))

    def set_image_scale(self, scale: float) -> None:
        scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE) if math.isfinite(scale) else 1.0
        if scale != self.image_scale:
            self.image_scale = scale
            self.changed.emit(frozenset({"image_scale"}))

    def set_selection_mode(self, mode: str) -> None:
        mode = mode if mode in SELECTION_MODES else "single"
        if mode != self.selection_mode:
            self.selection_mode = mode
            self.changed.emit(frozenset({"selection_mode"}))

    def to_dict(self) -> dict[str, Any]:
        return {
            "params": {name: getattr(self.params, name) for name in VIEW_PARAMS},
            "labels": self.labels_shown,
            "thumbnails": self.thumbnails_shown,
            "image_scale": self.image_scale,
            "selection_mode": self.selection_mode,
        }

    def load(self, state: dict[str, Any]) -> None:
        before = self.to_dict()
        params = state.get("params")
        self.params = ViewParams.from_dict(params) if isinstance(params, dict) else ViewParams()
        self.labels_shown = state.get("labels", True) is not False
        self.thumbnails_shown = state.get("thumbnails", True) is not False
        scale = state.get("image_scale", 1.0)
        self.image_scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE) if isinstance(scale, (int, float)) and math.isfinite(scale) else 1.0
        mode = state.get("selection_mode")
        self.selection_mode = mode if mode in SELECTION_MODES else "single"
        after = self.to_dict()
        changed = {name for name in VIEW_PARAMS if before["params"][name] != after["params"][name]}
        changed |= {name for name in ("labels", "thumbnails", "image_scale", "selection_mode") if before[name] != after[name]}
        if changed:
            self.changed.emit(frozenset(changed))

    def apply(self, view, host) -> None:
        params = self.params
        host.set_hover_size(params.hover_size)
        view.set_image_limit(params.max_images)
        view.set_image_spacing(params.image_spacing)
        view.set_image_cap(params.hover_size or DEFAULT_IMAGE_CAP)
        view.set_point_size(params.point_size)
        view.set_image_scale(self.image_scale)
        view.set_labels_visible(self.labels_shown)
        view.set_thumbnails_visible(self.thumbnails_shown)
        view.set_selection_mode(self.selection_mode)


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
        self.by_db: dict[str, Grouping] = {}

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
        save_grouping(db_name, grouping)
        self.changed.emit(db_name)

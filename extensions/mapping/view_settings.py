from __future__ import annotations

import math
from dataclasses import replace
from typing import Any

from PySide6 import QtCore

from .map_view import MAX_IMAGE_SCALE, MIN_IMAGE_SCALE
from .params import MapParams, param_specs

VIEW_STAGES = ("view",)
VIEW_PARAMS = tuple(name for name, spec, _ in param_specs() if spec.stage in VIEW_STAGES)
RELAYOUT_PARAMS = frozenset({"outlier_percent", "label_terms"})
SELECTION_MODES = ("single", "group")
DEFAULT_IMAGE_CAP = MapParams().hover_size


class ViewSettings(QtCore.QObject):
    changed = QtCore.Signal(bool)
    _instance: ViewSettings | None = None

    @classmethod
    def instance(cls) -> ViewSettings:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.params = MapParams()
        self.labels_shown = True
        self.thumbnails_shown = True
        self.image_scale = 1.0
        self.selection_mode = "single"

    def merged(self, params: MapParams) -> MapParams:
        return replace(params, **{name: getattr(self.params, name) for name in VIEW_PARAMS})

    def set_params(self, params: MapParams) -> None:
        params = replace(self.params, **{name: getattr(params, name) for name in VIEW_PARAMS})
        changed = {name for name in VIEW_PARAMS if getattr(params, name) != getattr(self.params, name)}
        if not changed:
            return
        self.params = params
        self.changed.emit(bool(changed & RELAYOUT_PARAMS))

    def set_labels_shown(self, shown: bool) -> None:
        if bool(shown) != self.labels_shown:
            self.labels_shown = bool(shown)
            self.changed.emit(False)

    def set_thumbnails_shown(self, shown: bool) -> None:
        if bool(shown) != self.thumbnails_shown:
            self.thumbnails_shown = bool(shown)
            self.changed.emit(False)

    def set_image_scale(self, scale: float) -> None:
        scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE) if math.isfinite(scale) else 1.0
        if scale != self.image_scale:
            self.image_scale = scale
            self.changed.emit(False)

    def set_selection_mode(self, mode: str) -> None:
        mode = mode if mode in SELECTION_MODES else "single"
        if mode != self.selection_mode:
            self.selection_mode = mode
            self.changed.emit(False)

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
        self.params = MapParams.from_dict(params) if isinstance(params, dict) else MapParams()
        self.labels_shown = state.get("labels", True) is not False
        self.thumbnails_shown = state.get("thumbnails", True) is not False
        scale = state.get("image_scale", 1.0)
        self.image_scale = min(max(float(scale), MIN_IMAGE_SCALE), MAX_IMAGE_SCALE) if isinstance(scale, (int, float)) and math.isfinite(scale) else 1.0
        mode = state.get("selection_mode")
        self.selection_mode = mode if mode in SELECTION_MODES else "single"
        after = self.to_dict()
        if after != before:
            self.changed.emit(any(before["params"][name] != after["params"][name] for name in RELAYOUT_PARAMS))

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

from __future__ import annotations

import json
import math
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import numpy as np

from wafer.core.db.path_values import PathValue
from wafer.core.logs import AppLogger

from . import projection
from .encoders import ENCODERS, BaseEncoder, feature_input
from .params import MapParams

if TYPE_CHECKING:
    from .space import Preset

OUTPUT_PREFIX = "mapping"
KEY_X, KEY_Y, KEY_GROUP_X, KEY_GROUP_Y, KEY_MODEL = (f"{OUTPUT_PREFIX}.{name}" for name in ("x", "y", "gx", "gy", "model"))
SPACE_KEYS = (KEY_X, KEY_Y, KEY_GROUP_X, KEY_GROUP_Y, KEY_MODEL)


class MapError(Exception):
    pass


@dataclass
class FeatureSpec:
    key: str
    encoder: str
    weight: float = 1.0
    options: dict[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> str:
        return json.dumps([self.key, self.encoder, sorted(self.options.items())])

    def label(self) -> str:
        return self.key

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "encoder": self.encoder, "weight": self.weight, "options": dict(self.options)}

    @classmethod
    def from_dict(cls, data: Any) -> FeatureSpec | None:
        if not isinstance(data, dict):
            return None
        encoder = ENCODERS.get(str(data.get("encoder")))
        key = data.get("key")
        if encoder is None or key is None:
            return None
        try:
            weight = float(data.get("weight", 1.0))
        except (TypeError, ValueError, OverflowError):
            weight = 1.0
        weight = min(max(weight, 0.0), 3.0) if math.isfinite(weight) else 1.0
        raw_options = data.get("options") or {}
        if not isinstance(raw_options, dict):
            AppLogger.warning(f"[Mapping] Ignored invalid saved options {raw_options!r}")
            raw_options = {}
        options = {str(k): str(v) for k, v in raw_options.items()}
        return cls(str(key), encoder.NAME, weight, options)


@dataclass
class MapRequest:
    paths: list[str]
    values: dict[str, dict[str, PathValue]]
    features: list[FeatureSpec]
    params: MapParams


@dataclass
class MapDiagnostics:
    timings: dict[str, float] = field(default_factory=dict)
    blocks: list[projection.BlockStats] = field(default_factory=list)
    groups: int = 0
    noise_ratio: float = 0.0
    largest: int = 0
    smallest: int = 0
    outliers: int = 0
    unset: int = 0

    def summary(self) -> str:
        times = " ".join(f"{name}={seconds:.2f}s" for name, seconds in self.timings.items())
        blocks = " ".join(f"{b.label}[dims={b.dims} median={b.median_distance:.3g} missing={b.missing} share={b.contribution:.0%}]" for b in self.blocks)
        return f"[Mapping] {times} | {blocks} | groups={self.groups} noise={self.noise_ratio:.0%} size={self.smallest}-{self.largest} outliers={self.outliers} unset={self.unset}"


@dataclass
class MapResult:
    paths: list[str]
    positions: np.ndarray
    outliers: np.ndarray
    unset: np.ndarray
    labels: np.ndarray | None
    group_terms: dict[int, list[str]]
    order: np.ndarray
    diagnostics: MapDiagnostics


@dataclass
class _Block:
    feature: FeatureSpec
    encoder: BaseEncoder
    raw: Any
    present: np.ndarray
    reduced: np.ndarray | None = None
    reduced_key: tuple | None = None


class MapPipeline:
    def __init__(self):
        self._lock = threading.Lock()
        self._blocks: dict[str, _Block] = {}
        self._encode_key: tuple | None = None
        self._combine_key: tuple | None = None
        self._layout_key: tuple | None = None
        self._group_key: tuple | None = None
        self._active = np.zeros(0, dtype=np.int64)
        self._points = np.zeros((0, 2), dtype=np.float32)
        self._group_points = np.zeros((0, 2), dtype=np.float32)
        self._combined: np.ndarray | None = None
        self._stats: list[projection.BlockStats] = []
        self._cluster_key: tuple | None = None
        self._labels: np.ndarray | None = None

    def run(self, request: MapRequest, *, cancelled: Callable[[], bool] = lambda: False, progress: Callable[[str, float], None] = lambda stage, fraction: None) -> MapResult | None:
        if len(request.paths) < 3:
            raise MapError("Select at least 3 files.")
        if not request.features:
            raise MapError("Add a key to map.")
        with self._lock:
            return self._run(request, request.params.normalized(), cancelled, progress)

    def _run(self, request, params, cancelled, progress) -> MapResult | None:
        if cancelled():
            return None
        diagnostics = MapDiagnostics()
        count = len(request.paths)
        blocks = self._encode(request, params, cancelled, progress, diagnostics)
        if blocks is None or cancelled():
            return None
        with timed(diagnostics, "reduce"):
            for block in blocks:
                key = (block.encoder.summary_dims(), params.seed)
                if block.reduced_key != key:
                    block.reduced = projection.BlockReducer(block.encoder.summary_dims(), params.seed).fit_transform(block.raw)
                    block.reduced_key = key
        if cancelled():
            return None
        has_value = np.zeros(count, dtype=bool)
        for block in blocks:
            has_value |= block.present
        active = np.flatnonzero(has_value)
        if active.size < 3:
            raise MapError("Not enough files have values for the selected keys.")
        combine_key = (self._encode_key, tuple((f.cache_key, f.weight) for f in request.features), params.seed)
        if combine_key != self._combine_key:
            with timed(diagnostics, "combine"):
                self._combined, self._stats, _scales = projection.combine_blocks([(b.feature.label(), b.reduced[active], b.present[active], b.feature.weight) for b in blocks], params.seed)
            self._active, self._combine_key, self._layout_key, self._group_key = active, combine_key, None, None
        layout_key = (combine_key, params.values_for("layout"))
        if layout_key != self._layout_key:
            progress("layout", 0.0)
            with timed(diagnostics, "layout"):
                self._points = projection.embed(self._combined, 2, params.n_neighbors, params.min_dist, params.seed)
            self._layout_key = layout_key
        if cancelled():
            return None
        group_key = (combine_key, params.n_neighbors)
        if group_key != self._group_key:
            progress("cluster", 0.0)
            with timed(diagnostics, "group_layout"):
                self._group_points = projection.embed(self._combined, 2, params.n_neighbors, projection.GROUPING_MIN_DIST, params.seed)
            self._group_key, self._cluster_key, self._labels = group_key, None, None
        if cancelled():
            return None
        diagnostics.blocks = self._stats
        labels = self._group(params, group_key, count, progress, diagnostics)
        if cancelled():
            return None
        group_terms = self._describe(labels, blocks, params)
        unit, active_outliers = projection.normalize_to_core(self._points, params.outlier_percent)
        positions = np.full((count, 2), np.nan, dtype=np.float32)
        positions[self._active] = unit
        outliers = np.zeros(count, dtype=bool)
        outliers[self._active] = active_outliers
        active_labels = self._labels
        order = np.concatenate([self._active[projection.order_rows(unit, active_labels)], np.flatnonzero(~has_value)])
        diagnostics.outliers = int(active_outliers.sum())
        diagnostics.unset = int((~has_value).sum())
        AppLogger.info(diagnostics.summary())
        return MapResult(list(request.paths), positions, outliers, ~has_value, labels, group_terms, order, diagnostics)

    def _encode(self, request, params, cancelled, progress, diagnostics) -> list[_Block] | None:
        encode_key = tuple(request.paths)
        if encode_key != self._encode_key:
            self._blocks.clear()
            self._encode_key = encode_key
        wanted = {feature.cache_key for feature in request.features}
        for key in [key for key in self._blocks if key not in wanted]:
            del self._blocks[key]
        for feature in request.features:
            if cancelled():
                return None
            if feature.cache_key in self._blocks:
                continue
            encoder = ENCODERS[feature.encoder](feature.options)
            inputs = self.inputs(feature, request)
            progress("encode", 0.0)
            with timed(diagnostics, "encode"):
                raw = encoder.fit_transform(inputs, params)
            self._blocks[feature.cache_key] = _Block(feature, encoder, raw, encoder.present(inputs))
        for feature in request.features:
            self._blocks[feature.cache_key].feature = feature
        return [self._blocks[feature.cache_key] for feature in request.features]

    def inputs(self, feature, request) -> list:
        return [feature_input(request.values.get(path, {}), feature.key, ENCODERS[feature.encoder]) for path in request.paths]

    def _group(self, params, group_key, count, progress, diagnostics) -> np.ndarray:
        cluster_key = (group_key, params.values_for("cluster"))
        if cluster_key != self._cluster_key:
            with timed(diagnostics, "cluster"):
                size = self._active.size
                self._labels = projection.cluster(self._group_points, params.resolved_min_cluster_size(size), params.resolved_min_samples(size))
            self._cluster_key = cluster_key
        labels = np.full(count, -1, dtype=np.int32)
        labels[self._active] = self._labels
        sizes = np.bincount(self._labels[self._labels >= 0]) if (self._labels >= 0).any() else np.zeros(0, dtype=np.int64)
        diagnostics.groups = int(sizes.size)
        diagnostics.noise_ratio = float((self._labels < 0).mean()) if self._labels.size else 0.0
        diagnostics.largest = int(sizes.max()) if sizes.size else 0
        diagnostics.smallest = int(sizes.min()) if sizes.size else 0
        return labels

    def _describe(self, labels, blocks, params) -> dict[int, list[str]]:
        ranked = [block for block, _ in sorted(zip(blocks, self._stats), key=lambda pair: -pair[1].contribution)]
        terms: dict[int, list[str]] = {}
        for group in sorted(set(labels.tolist()) - {-1}):
            members = np.flatnonzero(labels == group)
            words: list[str] = []
            for block in ranked:
                for word in block.encoder.describe(members[block.present[members]], params):
                    if word not in words:
                        words.append(word)
            terms[group] = words[: params.label_terms]
        return terms


def layout_from_space(paths: list[str], values: dict[str, dict[str, PathValue]], preset: Preset, params: MapParams) -> MapResult:
    params = params.normalized()
    diagnostics = MapDiagnostics()
    count = len(paths)
    raw = np.full((count, 4), np.nan, dtype=np.float64)
    version = str(preset.version)
    for row, path in enumerate(paths):
        entry = values.get(path, {})
        model = entry.get(KEY_MODEL)
        if model is None or model.text != version:
            continue
        numbers = [entry[key].number if key in entry else None for key in (KEY_X, KEY_Y, KEY_GROUP_X, KEY_GROUP_Y)]
        if None not in numbers:
            raw[row] = numbers
    placed = np.isfinite(raw).all(axis=1)
    active = np.flatnonzero(placed)
    if active.size == 0:
        raise MapError("No files have been placed yet. Wait for the Mapping parser or retrain in Mapping Space.")
    unit, active_outliers = projection.normalize_to_core(raw[active, :2], params.outlier_percent)
    positions = np.full((count, 2), np.nan, dtype=np.float32)
    positions[active] = unit
    outliers = np.zeros(count, dtype=bool)
    outliers[active] = active_outliers
    labels = None
    terms: dict[int, list[str]] = {}
    active_labels = np.zeros(active.size, dtype=np.int32)
    if active.size >= 3:
        with timed(diagnostics, "cluster"):
            active_labels = projection.cluster(raw[active, 2:], params.resolved_min_cluster_size(active.size), params.resolved_min_samples(active.size))
        labels = np.full(count, -1, dtype=np.int32)
        labels[active] = active_labels
        with timed(diagnostics, "describe"):
            terms = describe_space_groups([paths[i] for i in active], values, preset, active_labels, params)
        sizes = np.bincount(active_labels[active_labels >= 0]) if (active_labels >= 0).any() else np.zeros(0, dtype=np.int64)
        diagnostics.groups = int(sizes.size)
        diagnostics.noise_ratio = float((active_labels < 0).mean())
        diagnostics.largest = int(sizes.max()) if sizes.size else 0
        diagnostics.smallest = int(sizes.min()) if sizes.size else 0
    order = np.concatenate([active[projection.order_rows(unit, active_labels)], np.flatnonzero(~placed)])
    diagnostics.outliers = int(active_outliers.sum())
    diagnostics.unset = int((~placed).sum())
    AppLogger.info(diagnostics.summary())
    return MapResult(list(paths), positions, outliers, ~placed, labels, terms, order, diagnostics)


def describe_space_groups(paths: list[str], values: dict[str, dict[str, PathValue]], preset: Preset, labels: np.ndarray, params: MapParams) -> dict[int, list[str]]:
    described = []
    for feature in preset.features:
        encoder_cls = ENCODERS[feature.encoder]
        encoder = encoder_cls(feature.options)
        inputs = [feature_input(values.get(path, {}), feature.key, encoder_cls) for path in paths]
        encoder.fit_describe(inputs, params)
        described.append((encoder, encoder.present(inputs)))
    terms: dict[int, list[str]] = {}
    for group in sorted(set(labels.tolist()) - {-1}):
        members = np.flatnonzero(labels == group)
        words: list[str] = []
        for encoder, present in described:
            for word in encoder.describe(members[present[members]], params):
                if word not in words:
                    words.append(word)
        terms[group] = words[: params.label_terms]
    return terms


@contextmanager
def timed(diagnostics: MapDiagnostics, name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        diagnostics.timings[name] = diagnostics.timings.get(name, 0.0) + time.perf_counter() - started

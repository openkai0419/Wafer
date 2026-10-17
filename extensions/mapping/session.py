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
from .encoders import ENCODERS, SUMMARY_OPTION, BaseEncoder, feature_input
from .params import MapParams

if TYPE_CHECKING:
    from .space import Preset

OUTPUT_PREFIX = "mapping"
KEY_X, KEY_Y, KEY_GROUP, KEY_MODEL = (f"{OUTPUT_PREFIX}.{name}" for name in ("x", "y", "group", "model"))
SPACE_KEYS = (KEY_X, KEY_Y, KEY_GROUP, KEY_MODEL)
SPACE_COLUMNS = 2 + projection.GROUPING_DIMS
GROUPING_SEPARATOR = ","


def grouping_text(numbers) -> str:
    return GROUPING_SEPARATOR.join(f"{float(value):.6g}" for value in numbers)


def grouping_values(text: str) -> np.ndarray | None:
    parts = text.split(GROUPING_SEPARATOR) if text else []
    if len(parts) != projection.GROUPING_DIMS:
        return None
    try:
        numbers = np.array([float(part) for part in parts], dtype=np.float64)
    except ValueError:
        return None
    return numbers if np.isfinite(numbers).all() else None


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
        return json.dumps([self.key, self.encoder, sorted((name, value) for name, value in self.options.items() if name != SUMMARY_OPTION.name)])

    def summary_dims(self) -> int:
        return ENCODERS[self.encoder].summary_dims(self.options)

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
        self._sample_key: tuple | None = None
        self._train = np.zeros(0, dtype=np.int64)
        self._training: np.ndarray | None = None
        self._placement: tuple[np.ndarray, projection.Placement] | None = None
        self._neighbors_key: tuple | None = None
        self._neighbors: projection.Neighbors | None = None
        self._active = np.zeros(0, dtype=np.int64)
        self._points = np.zeros((0, 2), dtype=np.float32)
        self._group_points = np.zeros((0, projection.GROUPING_DIMS), dtype=np.float32)
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
                key = (block.feature.summary_dims(), params.seed)
                if block.reduced_key != key:
                    block.reduced = projection.BlockReducer(key[0], params.seed).fit_transform(block.raw)
                    block.reduced_key = key
        if cancelled():
            return None
        has_value = np.zeros(count, dtype=bool)
        for block in blocks:
            has_value |= block.present
        active = np.flatnonzero(has_value)
        if active.size < 3:
            raise MapError("Not enough files have values for the selected keys.")
        combine_key = (self._encode_key, tuple((b.feature.cache_key, b.feature.weight, b.reduced_key) for b in blocks), params.seed)
        if combine_key != self._combine_key:
            with timed(diagnostics, "combine"):
                self._combined, self._stats, _scales = projection.combine_blocks([(b.feature.label(), b.reduced[active], b.present[active], b.feature.weight) for b in blocks], params.seed)
            self._active, self._combine_key, self._layout_key, self._group_key = active, combine_key, None, None
        sample_key = (combine_key, params.train_limit)
        if sample_key != self._sample_key:
            self._train = projection.sample_rows(self._active.size, params.train_limit, params.seed)
            self._training = self._combined if self._train.size == self._active.size else self._combined[self._train]
            self._sample_key, self._placement = sample_key, None
        neighbor_count = params.resolved_neighbors(self._train.size)
        neighbors_key = (sample_key, neighbor_count)
        layout_key = (neighbors_key, params.min_dist)
        if layout_key != self._layout_key:
            progress("layout", 0.0)
            neighbors = self._neighbors_for(neighbors_key, neighbor_count, params.seed, diagnostics)
            with timed(diagnostics, "layout"):
                self._points = self._spread(projection.embed(self._training, neighbors, params.min_dist, params.seed), diagnostics)
            self._layout_key = layout_key
        if cancelled():
            return None
        group_key = neighbors_key
        if group_key != self._group_key:
            progress("cluster", 0.0)
            neighbors = self._neighbors_for(neighbors_key, neighbor_count, params.seed, diagnostics)
            with timed(diagnostics, "group_layout"):
                self._group_points = self._spread(projection.embed(self._training, neighbors, projection.GROUPING_MIN_DIST, params.seed, projection.GROUPING_DIMS), diagnostics)
            self._group_key, self._cluster_key, self._labels = group_key, None, None
        if cancelled():
            return None
        diagnostics.blocks = self._stats
        labels = self._group((group_key, params.cluster_options(self._active.size)), count, diagnostics)
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

    def _neighbors_for(self, key, count, seed, diagnostics) -> projection.Neighbors | None:
        if key != self._neighbors_key:
            with timed(diagnostics, "neighbors"):
                self._neighbors = projection.nearest_neighbors(self._training, count, seed)
            self._neighbors_key = key
        return self._neighbors

    def _spread(self, trained: np.ndarray, diagnostics) -> np.ndarray:
        if self._train.size == self._active.size:
            return trained
        if self._placement is None:
            with timed(diagnostics, "place"):
                rest = np.setdiff1d(np.arange(self._active.size), self._train, assume_unique=True)
                self._placement = (rest, projection.NeighborIndex(self._training).placement(self._combined[rest]))
        rest, placement = self._placement
        points = np.empty((self._active.size, trained.shape[1]), dtype=np.float32)
        points[self._train] = trained
        points[rest] = placement.apply(trained)
        return points

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

    def _group(self, cluster_key, count, diagnostics) -> np.ndarray:
        if cluster_key != self._cluster_key:
            with timed(diagnostics, "cluster"):
                self._labels = projection.cluster(self._group_points, *cluster_key[1])
            self._cluster_key = cluster_key
        labels = np.full(count, -1, dtype=np.int32)
        labels[self._active] = self._labels
        record_groups(diagnostics, self._labels)
        return labels

    def _describe(self, labels, blocks, params) -> dict[int, list[str]]:
        ranked = [block for block, _ in sorted(zip(blocks, self._stats), key=lambda pair: -pair[1].contribution)]
        return describe_groups([(block.encoder, block.present) for block in ranked], labels, params)


class SpaceLayout:
    def __init__(self, paths: list[str], values: dict[str, dict[str, PathValue]], preset: Preset):
        self.paths = paths
        self.values = values
        self.preset = preset
        self.lock = threading.Lock()
        self.coords: np.ndarray | None = None
        self.describers: list[tuple[BaseEncoder, np.ndarray]] | None = None
        self.labels_by_options: dict[tuple[int, int, str], np.ndarray] = {}

    def run(self, params: MapParams, *, grouped: bool = True) -> MapResult:
        with self.lock:
            return self._run(params.normalized(), grouped)

    def _run(self, params: MapParams, grouped: bool) -> MapResult:
        diagnostics = MapDiagnostics()
        count = len(self.paths)
        raw = self.space_coords()
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
        if grouped and active.size >= 3:
            active_labels = self.group(raw[active, 2:], params, diagnostics)
            labels = np.full(count, -1, dtype=np.int32)
            labels[active] = active_labels
            with timed(diagnostics, "describe"):
                terms = describe_groups(self.space_describers(active, params), active_labels, params)
            record_groups(diagnostics, active_labels)
        order = np.concatenate([active[projection.order_rows(unit, active_labels)], np.flatnonzero(~placed)])
        diagnostics.outliers = int(active_outliers.sum())
        diagnostics.unset = int((~placed).sum())
        AppLogger.info(diagnostics.summary())
        return MapResult(list(self.paths), positions, outliers, ~placed, labels, terms, order, diagnostics)

    def is_grouped(self) -> bool:
        return bool(self.labels_by_options)

    def space_coords(self) -> np.ndarray:
        if self.coords is None:
            raw = np.full((len(self.paths), SPACE_COLUMNS), np.nan, dtype=np.float64)
            version = str(self.preset.version)
            for row, path in enumerate(self.paths):
                entry = self.values.get(path, {})
                model = entry.get(KEY_MODEL)
                if model is None or model.text != version or KEY_GROUP not in entry:
                    continue
                x, y = (entry[key].number if key in entry else None for key in (KEY_X, KEY_Y))
                grouping = grouping_values(entry[KEY_GROUP].text)
                if x is not None and y is not None and grouping is not None:
                    raw[row, :2] = x, y
                    raw[row, 2:] = grouping
            self.coords = raw
        return self.coords

    def group(self, grouping: np.ndarray, params: MapParams, diagnostics: MapDiagnostics) -> np.ndarray:
        options = params.cluster_options(len(grouping))
        if options not in self.labels_by_options:
            with timed(diagnostics, "cluster"):
                self.labels_by_options[options] = projection.cluster(grouping, *options)
        return self.labels_by_options[options]

    def space_describers(self, active: np.ndarray, params: MapParams) -> list[tuple[BaseEncoder, np.ndarray]]:
        if self.describers is None:
            paths = [self.paths[i] for i in active]
            self.describers = []
            for feature in self.preset.features:
                encoder_cls = ENCODERS[feature.encoder]
                encoder = encoder_cls(feature.options)
                inputs = [feature_input(self.values.get(path, {}), feature.key, encoder_cls) for path in paths]
                encoder.fit_describe(inputs, params)
                self.describers.append((encoder, encoder.present(inputs)))
        return self.describers


def describe_groups(describers: list[tuple[BaseEncoder, np.ndarray]], labels: np.ndarray, params: MapParams) -> dict[int, list[str]]:
    terms: dict[int, list[str]] = {}
    for group in sorted(set(labels.tolist()) - {-1}):
        members = np.flatnonzero(labels == group)
        words: list[str] = []
        for encoder, present in describers:
            for word in encoder.describe(members[present[members]], params):
                if word not in words:
                    words.append(word)
        terms[group] = words[: params.label_terms]
    return terms


def record_groups(diagnostics: MapDiagnostics, labels: np.ndarray) -> None:
    sizes = np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.zeros(0, dtype=np.int64)
    diagnostics.groups = int(sizes.size)
    diagnostics.noise_ratio = float((labels < 0).mean()) if labels.size else 0.0
    diagnostics.largest = int(sizes.max()) if sizes.size else 0
    diagnostics.smallest = int(sizes.min()) if sizes.size else 0


@contextmanager
def timed(diagnostics: MapDiagnostics, name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        diagnostics.timings[name] = diagnostics.timings.get(name, 0.0) + time.perf_counter() - started

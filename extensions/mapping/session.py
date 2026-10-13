from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from wafer.core.db.path_values import PathValue
from wafer.core.logs import AppLogger

from . import projection
from .encoders import ENCODERS, BaseEncoder
from .params import MapParams

PixelLoader = Callable[[str], "np.ndarray | None"]
IMAGE_PROGRESS_STEP = 50


class MapError(Exception):
    pass


@dataclass
class FeatureSpec:
    key: str | None
    encoder: str
    weight: float = 1.0
    options: dict[str, str] = field(default_factory=dict)

    @property
    def cache_key(self) -> str:
        return json.dumps([self.key, self.encoder, sorted(self.options.items())])

    def label(self) -> str:
        return self.key if self.key is not None else ENCODERS[self.encoder].DISPLAY_NAME

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "encoder": self.encoder, "weight": self.weight, "options": dict(self.options)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> FeatureSpec | None:
        encoder = ENCODERS.get(str(data.get("encoder")))
        key = data.get("key")
        if encoder is None or (encoder.INPUT == "image") != (key is None):
            return None
        try:
            weight = float(data.get("weight", 1.0))
        except (TypeError, ValueError):
            weight = 1.0
        options = {str(k): str(v) for k, v in dict(data.get("options") or {}).items()}
        return cls(None if key is None else str(key), encoder.NAME, weight, options)


@dataclass
class MapRequest:
    paths: list[str]
    values: dict[str, dict[str, PathValue]]
    features: list[FeatureSpec]
    params: MapParams
    grouping: bool


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


def value_input(value: PathValue | None) -> PathValue | None:
    if value is None or (not value.text.strip() and value.number is None):
        return None
    return value


class MapPipeline:
    def __init__(self, load_pixels: PixelLoader, pixel_cache: dict[str, np.ndarray | None] | None = None):
        self._load_pixels = load_pixels
        self._pixels = pixel_cache if pixel_cache is not None else {}
        self._lock = threading.Lock()
        self._blocks: dict[str, _Block] = {}
        self._encode_key: tuple | None = None
        self._layout_key: tuple | None = None
        self._active = np.zeros(0, dtype=np.int64)
        self._points = np.zeros((0, 2), dtype=np.float32)
        self._combined: np.ndarray | None = None
        self._stats: list[projection.BlockStats] = []
        self._cluster_space: np.ndarray | None = None
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
        diagnostics = MapDiagnostics()
        count = len(request.paths)
        blocks = self._encode(request, params, cancelled, progress, diagnostics)
        if blocks is None or cancelled():
            return None
        with timed(diagnostics, "reduce"):
            for block in blocks:
                key = params.values_for("reduce") + (params.seed,)
                if block.reduced_key != key:
                    block.reduced = projection.reduce_block(block.raw, params.svd_dims, params.seed)
                    block.reduced_key = key
        if cancelled():
            return None
        has_value = np.zeros(count, dtype=bool)
        for block in blocks:
            has_value |= block.present
        active = np.flatnonzero(has_value)
        if active.size < 3:
            raise MapError("Not enough files have values for the selected keys.")
        layout_key = (
            self._encode_key,
            tuple((f.cache_key, f.weight) for f in request.features),
            params.values_for("reduce"),
            params.values_for("layout"),
        )
        if layout_key != self._layout_key:
            progress("layout", 0.0)
            with timed(diagnostics, "layout"):
                self._combined, self._stats = projection.combine_blocks([(b.feature.label(), b.reduced[active], b.present[active], b.feature.weight) for b in blocks], params.seed)
                self._points = projection.embed(self._combined, 2, params.n_neighbors, params.min_dist, params.seed)
            self._active, self._layout_key = active, layout_key
            self._cluster_space, self._cluster_key, self._labels = None, None, None
        if cancelled():
            return None
        diagnostics.blocks = self._stats
        labels = None
        group_terms: dict[int, list[str]] = {}
        if request.grouping:
            labels = self._group(params, layout_key, count, progress, diagnostics)
            if cancelled():
                return None
            group_terms = self._describe(labels, blocks, params)
        unit, active_outliers = projection.clip_to_unit(self._points, params.clip_percent)
        positions = np.full((count, 2), np.nan, dtype=np.float32)
        positions[self._active] = unit
        outliers = np.zeros(count, dtype=bool)
        outliers[self._active] = active_outliers
        active_labels = self._labels if labels is not None else np.zeros(self._active.size, dtype=np.int32)
        order = np.concatenate([self._active[projection.order_rows(unit, active_labels)], np.flatnonzero(~has_value)])
        diagnostics.outliers = int(active_outliers.sum())
        diagnostics.unset = int((~has_value).sum())
        AppLogger.info(diagnostics.summary())
        return MapResult(list(request.paths), positions, outliers, ~has_value, labels, group_terms, order, diagnostics)

    def _encode(self, request, params, cancelled, progress, diagnostics) -> list[_Block] | None:
        encode_key = (tuple(request.paths), params.values_for("encode"))
        if encode_key != self._encode_key:
            self._blocks.clear()
            self._encode_key = encode_key
        wanted = {feature.cache_key for feature in request.features}
        for key in [key for key in self._blocks if key not in wanted]:
            del self._blocks[key]
        for feature in request.features:
            if feature.cache_key in self._blocks:
                continue
            encoder = ENCODERS[feature.encoder](feature.options)
            inputs = self._inputs(feature, encoder, request, cancelled, progress, diagnostics)
            if inputs is None:
                return None
            progress("encode", 0.0)
            with timed(diagnostics, "encode"):
                raw = encoder.encode(inputs, params)
            self._blocks[feature.cache_key] = _Block(feature, encoder, raw, encoder.present(inputs))
            if cancelled():
                return None
        for feature in request.features:
            self._blocks[feature.cache_key].feature = feature
        return [self._blocks[feature.cache_key] for feature in request.features]

    def _inputs(self, feature, encoder, request, cancelled, progress, diagnostics) -> list | None:
        if encoder.INPUT != "image":
            return [value_input(request.values.get(path, {}).get(feature.key)) for path in request.paths]
        images = []
        with timed(diagnostics, "images"):
            for i, path in enumerate(request.paths):
                if cancelled():
                    return None
                if path not in self._pixels:
                    self._pixels[path] = self._load_pixels(path)
                images.append(self._pixels[path])
                if i % IMAGE_PROGRESS_STEP == 0:
                    progress("images", i / len(request.paths))
        return images

    def _group(self, params, layout_key, count, progress, diagnostics) -> np.ndarray:
        if self._cluster_space is None:
            progress("cluster", 0.0)
            with timed(diagnostics, "cluster_layout"):
                self._cluster_space = projection.embed(self._combined, params.cluster_dims, params.n_neighbors, 0.0, params.seed)
        cluster_key = (layout_key, params.values_for("cluster"))
        if cluster_key != self._cluster_key:
            with timed(diagnostics, "cluster"):
                size = self._active.size
                self._labels = projection.cluster(self._cluster_space, params.resolved_min_cluster_size(size), params.resolved_min_samples(size))
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


@contextmanager
def timed(diagnostics: MapDiagnostics, name: str):
    started = time.perf_counter()
    try:
        yield
    finally:
        diagnostics.timings[name] = diagnostics.timings.get(name, 0.0) + time.perf_counter() - started

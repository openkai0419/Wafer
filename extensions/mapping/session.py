from __future__ import annotations

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
from .params import Grouping, ViewParams

if TYPE_CHECKING:
    from .space import Preset, SpaceModel

OUTPUT_PREFIX = "mapping"
KEY_X, KEY_Y, KEY_GROUP, KEY_MODEL = (f"{OUTPUT_PREFIX}.{name}" for name in ("x", "y", "group", "model"))
SPACE_KEYS = (KEY_X, KEY_Y, KEY_GROUP, KEY_MODEL)
SPACE_COLUMNS = 2 + projection.GROUPING_DIMS
GROUPING_SEPARATOR = ","
MIN_LAYOUT_FILES = 3


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
class MapDiagnostics:
    timings: dict[str, float] = field(default_factory=dict)
    groups: int = 0
    noise_ratio: float = 0.0
    largest: int = 0
    smallest: int = 0
    outliers: int = 0
    unset: int = 0

    def summary(self) -> str:
        times = " ".join(f"{name}={seconds:.2f}s" for name, seconds in self.timings.items())
        return f"[Mapping] {times} | groups={self.groups} noise={self.noise_ratio:.0%} size={self.smallest}-{self.largest} outliers={self.outliers} unset={self.unset}"


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


class TreeCache:
    def __init__(self, points: np.ndarray, keep: int = 2):
        self.points = points
        self.keep = keep
        self.trees: dict[int, projection.ClusterTree] = {}

    def __call__(self, samples: int) -> projection.ClusterTree:
        tree = self.trees.pop(samples, None) or projection.ClusterTree(self.points, samples)
        self.trees[samples] = tree
        while len(self.trees) > self.keep:
            self.trees.pop(next(iter(self.trees)))
        return tree


def group_labels(trees: Callable[[int], projection.ClusterTree], grouping: Grouping, count: int, share: float = 1.0) -> np.ndarray:
    size, samples, method = grouping.cluster_options(count)
    return finer_labels(trees(samples).labels(size, method), trees, grouping, count, share)


def finer_labels(base: np.ndarray, trees: Callable[[int], projection.ClusterTree], grouping: Grouping, count: int, share: float) -> np.ndarray:
    size, _samples, method = grouping.cluster_options(count)
    smaller, smaller_samples, _ = grouping.cluster_options(count, share)
    return base if smaller >= size else nested_labels(base, trees(smaller_samples).labels(smaller, method))


def nested_labels(base: np.ndarray, finer: np.ndarray) -> np.ndarray:
    grouped = base >= 0
    rest = int(finer.max()) + 1
    codes = np.full(base.size, -1, dtype=np.int64)
    codes[grouped] = base[grouped].astype(np.int64) * (rest + 1) + np.where(finer[grouped] >= 0, finer[grouped], rest)
    return projection.relabel_by_size(codes)


class WholeSpace:
    def __init__(self, paths: list[str], coords: np.ndarray):
        self.paths = paths
        self.coords = coords
        self.points = np.ascontiguousarray(coords[:, 2:], dtype=np.float32)
        self.index = {path: row for row, path in enumerate(paths)}
        self.lock = threading.Lock()
        self.trees = TreeCache(self.points)
        self.nearest = None
        self.labels_by_options: dict[tuple[Grouping, float], np.ndarray] = {}

    @property
    def size(self) -> int:
        return len(self.paths)

    def rows(self, paths: list[str]) -> np.ndarray:
        return np.fromiter((self.index.get(path, -1) for path in paths), dtype=np.int64, count=len(paths))

    def labels(self, grouping: Grouping, share: float = 1.0) -> np.ndarray:
        with self.lock:
            if (grouping, share) not in self.labels_by_options:
                self.labels_by_options[(grouping, share)] = group_labels(self.trees, grouping, self.size, share)
            return self.labels_by_options[(grouping, share)]

    def labels_for(self, paths: list[str], points: np.ndarray, grouping: Grouping, share: float = 1.0) -> np.ndarray:
        rows = self.rows(paths)
        missing = np.flatnonzero(rows < 0)
        if missing.size:
            rows[missing] = self.nearest_rows(points[missing])
        return self.labels(grouping, share)[rows].astype(np.int32)

    def nearest_rows(self, points: np.ndarray) -> np.ndarray:
        if self.nearest is None:
            from sklearn.neighbors import NearestNeighbors

            self.nearest = NearestNeighbors(n_neighbors=1).fit(self.points)
        return self.nearest.kneighbors(np.asarray(points, dtype=np.float32), return_distance=False)[:, 0]


class SpaceLayout:
    def __init__(
        self,
        paths: list[str],
        values: dict[str, dict[str, PathValue]],
        preset: Preset,
        model: SpaceModel | None = None,
        load_model: Callable[[], SpaceModel | None] | None = None,
    ):
        self.paths = paths
        self.values = values
        self.preset = preset
        self.model = model
        self.load_model = load_model
        self.local_trees: TreeCache | None = None
        self.lock = threading.Lock()
        self.coords: np.ndarray | None = None
        self.local: np.ndarray | None = None
        self.describers: list[tuple[BaseEncoder, np.ndarray]] | None = None
        self.labels_by_options: dict[tuple[Grouping, float], np.ndarray] = {}

    def run(self, params: ViewParams, *, grouping: Grouping | None = None, share: float = 1.0, grouped: bool = True, cancelled: Callable[[], bool] = lambda: False) -> MapResult | None:
        with self.lock:
            return None if cancelled() else self._run(params.normalized(), (grouping or Grouping()).normalized(), share, grouped)

    def _run(self, params: ViewParams, grouping: Grouping, share: float, grouped: bool) -> MapResult:
        diagnostics = MapDiagnostics()
        count = len(self.paths)
        raw = self.shown_coords(diagnostics)
        placed = np.isfinite(raw).all(axis=1)
        active = np.flatnonzero(placed)
        if active.size == 0:
            raise MapError("No files have been placed yet. Wait for the Mapping parser or retrain in Settings.")
        unit, active_outliers = projection.normalize_to_core(raw[active, :2], params.outlier_percent)
        positions = np.full((count, 2), np.nan, dtype=np.float32)
        positions[active] = unit
        outliers = np.zeros(count, dtype=bool)
        outliers[active] = active_outliers
        labels = None
        terms: dict[int, list[str]] = {}
        active_labels = np.zeros(active.size, dtype=np.int32)
        if grouped and active.size >= 3:
            active_labels = self.group(active, grouping, share, diagnostics)
            labels = np.full(count, -1, dtype=np.int32)
            labels[active] = active_labels
            with timed(diagnostics, "describe"):
                terms = describe_groups(self.space_describers(active), active_labels, params.label_terms)
            record_groups(diagnostics, active_labels)
        order = np.concatenate([active[projection.order_rows(unit, active_labels)], np.flatnonzero(~placed)])
        diagnostics.outliers = int(active_outliers.sum())
        diagnostics.unset = int((~placed).sum())
        AppLogger.info(diagnostics.summary())
        return MapResult(list(self.paths), positions, outliers, ~placed, labels, terms, order, diagnostics)

    def is_grouped(self) -> bool:
        return bool(self.labels_by_options)

    def is_local(self) -> bool:
        return self.local is not None

    def space_model(self, diagnostics: MapDiagnostics | None = None) -> SpaceModel | None:
        if self.model is None and self.load_model is not None:
            with timed(diagnostics or MapDiagnostics(), "space"):
                self.model, self.load_model = self.load_model(), None
        return self.model

    def whole_space(self, diagnostics: MapDiagnostics | None = None) -> WholeSpace | None:
        model = self.space_model(diagnostics)
        return None if model is None else model.whole_space()

    def shown_coords(self, diagnostics: MapDiagnostics | None = None) -> np.ndarray:
        return self.local if self.local is not None else self.space_coords(diagnostics)

    def space_coords(self, diagnostics: MapDiagnostics | None = None) -> np.ndarray:
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
            missing = np.flatnonzero(~np.isfinite(raw).all(axis=1))
            model = self.space_model(diagnostics) if missing.size else None
            if model is not None:
                space = model.whole_space()
                rows = space.rows([self.paths[row] for row in missing])
                found = rows >= 0
                raw[missing[found]] = space.coords[rows[found]]
                new = missing[~found]
                if new.size:
                    raw[new] = model.place([self.values.get(self.paths[row], {}) for row in new])
            self.coords = raw
        return self.coords

    def refine(self, cancelled: Callable[[], bool] = lambda: False, progress: Callable[[str], None] = lambda stage: None) -> bool:
        with self.lock:
            if self.local is not None:
                return False
            active = np.flatnonzero(np.isfinite(self.space_coords()).all(axis=1))
            model = self.space_model()
            if model is None or active.size < MIN_LAYOUT_FILES:
                return False
            start = self.space_coords()[active]
        coords = model.relayout([self.values.get(self.paths[row], {}) for row in active], start, cancelled=cancelled, progress=progress)
        with self.lock:
            local = np.array(self.space_coords(), copy=True)
            found = np.isfinite(coords).all(axis=1)
            local[active[found]] = coords[found]
            self.local, self.local_trees = local, None
            self.labels_by_options.clear()
        return True

    def group(self, active: np.ndarray, grouping: Grouping, share: float, diagnostics: MapDiagnostics) -> np.ndarray:
        key = (grouping, share)
        if key not in self.labels_by_options:
            space = self.whole_space(diagnostics)
            shown = self.shown_coords()[active, 2:]
            with timed(diagnostics, "cluster"):
                if space is None:
                    if self.local_trees is None:
                        self.local_trees = TreeCache(shown)
                    labels = group_labels(self.local_trees, grouping, len(shown), share)
                elif self.local is None:
                    labels = space.labels_for([self.paths[row] for row in active], shown, grouping, share)
                else:
                    if self.local_trees is None:
                        self.local_trees = TreeCache(shown)
                    base = space.labels_for([self.paths[row] for row in active], self.space_coords()[active, 2:], grouping)
                    labels = finer_labels(base, self.local_trees, grouping, space.size, share)
            self.labels_by_options[key] = labels
        return self.labels_by_options[key]

    def space_describers(self, active: np.ndarray) -> list[tuple[BaseEncoder, np.ndarray]]:
        if self.describers is None:
            paths = [self.paths[i] for i in active]
            self.describers = []
            for feature in self.preset.features:
                encoder_cls = ENCODERS[feature.encoder]
                encoder = encoder_cls(feature.options)
                inputs = [feature_input(self.values.get(path, {}), feature.key, encoder_cls) for path in paths]
                encoder.fit_describe(inputs)
                self.describers.append((encoder, encoder.present(inputs)))
        return self.describers


def describe_groups(describers: list[tuple[BaseEncoder, np.ndarray]], labels: np.ndarray, terms: int) -> dict[int, list[str]]:
    grouped = labels >= 0
    order = np.flatnonzero(grouped)[np.argsort(labels[grouped], kind="stable")]
    ids, starts = np.unique(labels[order], return_index=True)
    members_by_group = np.split(order, starts[1:]) if ids.size else []
    words_by_group: list[list[str]] = [[] for _ in members_by_group]
    for encoder, present in describers:
        described = encoder.describe_groups([members[present[members]] for members in members_by_group], terms)
        for words, found in zip(words_by_group, described):
            words.extend(word for word in found if word not in words)
    return {int(group): words[:terms] for group, words in zip(ids.tolist(), words_by_group)}


def record_groups(diagnostics: MapDiagnostics, labels: np.ndarray) -> None:
    sizes = np.unique(labels[labels >= 0], return_counts=True)[1]
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

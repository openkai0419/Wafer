from __future__ import annotations

import threading
import time
import warnings
from dataclasses import dataclass

import numpy as np

from wafer.core.logs import AppLogger

SMALL_LAYOUT_LIMIT = 3
SPECTRAL_INIT_MIN = 20
GROUPING_MIN_DIST = 0.0
GROUPING_DIMS = 10
WARM_UP_ROWS = 300
EXACT_NEIGHBORS_LIMIT = 200_000
PLACE_NEIGHBORS = 3
LAYOUT_EPOCHS = 200
_warm_up_lock = threading.Lock()
_warmed_up = False


@dataclass
class BlockStats:
    label: str
    dims: int
    median_distance: float
    missing: int
    contribution: float = 0.0


def median_pair_distance(matrix, *, samples: int = 2000, seed: int = 0) -> float:
    count = matrix.shape[0]
    if count < 2:
        return 1.0
    rng = np.random.default_rng(seed)
    left = rng.integers(0, count, samples)
    right = rng.integers(0, count, samples)
    keep = left != right
    diff = matrix[left[keep]] - matrix[right[keep]]
    if hasattr(diff, "multiply"):
        distances = np.sqrt(np.asarray(diff.multiply(diff).sum(axis=1)).ravel())
    else:
        distances = np.linalg.norm(np.asarray(diff, dtype=np.float64), axis=1)
    nonzero = distances[distances > 1e-12]
    return float(np.median(nonzero)) if nonzero.size else 1.0


@dataclass
class BlockScale:
    mean: np.ndarray
    scale: float
    weight: float


class BlockReducer:
    def __init__(self, svd_dims: int, seed: int):
        self.svd_dims = svd_dims
        self.seed = seed
        self.sparse = False
        self.svd = None

    def fit_transform(self, matrix) -> np.ndarray:
        self.sparse = hasattr(matrix, "tocsr")
        if not self.sparse:
            return np.asarray(matrix, dtype=np.float32)
        from sklearn.preprocessing import normalize

        normalized = normalize(matrix.tocsr())
        components = min(self.svd_dims, normalized.shape[1] - 1, normalized.shape[0] - 1)
        if normalized.shape[1] <= self.svd_dims or components < 2:
            self.svd = None
            return normalized.toarray().astype(np.float32)
        from sklearn.decomposition import TruncatedSVD

        self.svd = TruncatedSVD(n_components=components, random_state=self.seed).fit(normalized)
        return self.svd.transform(normalized).astype(np.float32)

    def transform(self, matrix) -> np.ndarray:
        if not self.sparse:
            return np.asarray(matrix, dtype=np.float32)
        from sklearn.preprocessing import normalize

        normalized = normalize(matrix.tocsr())
        if self.svd is None:
            return normalized.toarray().astype(np.float32)
        return self.svd.transform(normalized).astype(np.float32)


def combine_blocks(blocks: list[tuple[str, np.ndarray, np.ndarray, float]], seed: int) -> tuple[np.ndarray, list[BlockStats], list[BlockScale]]:
    parts: list[np.ndarray] = []
    stats: list[BlockStats] = []
    scales: list[BlockScale] = []
    for label, dense, present, weight in blocks:
        mean = dense[present].mean(axis=0) if present.any() else np.zeros(dense.shape[1], dtype=np.float32)
        filled = dense
        if not present.all():
            filled = dense.copy()
            filled[~present] = mean
        scale = median_pair_distance(filled[present], seed=seed)
        parts.append(filled / scale * weight)
        stats.append(BlockStats(label, dense.shape[1], scale, int((~present).sum())))
        scales.append(BlockScale(np.asarray(mean, dtype=np.float32), scale, weight))
    variances = [float(part.var(axis=0).sum()) for part in parts]
    total = sum(variances)
    for stat, variance in zip(stats, variances):
        stat.contribution = variance / total if total > 0 else 0.0
    return np.hstack(parts).astype(np.float32), stats, scales


def apply_block_scales(parts: list[tuple[np.ndarray, np.ndarray]], scales: list[BlockScale]) -> np.ndarray:
    columns = []
    for (dense, present), block in zip(parts, scales):
        filled = np.array(dense, dtype=np.float32, copy=True)
        if not present.all():
            filled[~present] = block.mean
        columns.append(filled / block.scale * block.weight)
    return np.hstack(columns).astype(np.float32)


@dataclass
class Neighbors:
    indices: np.ndarray
    distances: np.ndarray


def nearest_neighbors(matrix: np.ndarray, n_neighbors: int, seed: int) -> Neighbors | None:
    count = matrix.shape[0]
    if count <= SMALL_LAYOUT_LIMIT:
        return None
    k = max(2, min(n_neighbors, count - 1))
    if count > EXACT_NEIGHBORS_LIMIT:
        from pynndescent import NNDescent

        indices, distances = NNDescent(matrix, n_neighbors=k, metric="euclidean", random_state=seed, n_jobs=1, low_memory=True).neighbor_graph
        return Neighbors(indices, distances)
    return exact_neighbors(matrix, k)


def exact_neighbors(matrix: np.ndarray, k: int) -> Neighbors:
    from sklearn.neighbors import NearestNeighbors

    data = np.ascontiguousarray(matrix, dtype=np.float32)
    distances, indices = NearestNeighbors(n_neighbors=k, algorithm="brute").fit(data).kneighbors(data)
    return own_first(indices.astype(np.int32), distances.astype(np.float32))


def own_first(indices: np.ndarray, distances: np.ndarray) -> Neighbors:
    rows = np.flatnonzero(indices[:, 0] != np.arange(len(indices)))
    if rows.size:
        own = indices[rows] == rows[:, None]
        order = np.argsort(~own, axis=1, kind="stable")
        moved, gaps = np.take_along_axis(indices[rows], order, axis=1), np.take_along_axis(distances[rows], order, axis=1)
        missing = ~own.any(axis=1)
        moved[missing] = np.hstack([rows[missing, None], moved[missing, :-1]])
        gaps[missing] = np.hstack([np.zeros((int(missing.sum()), 1), dtype=gaps.dtype), gaps[missing, :-1]])
        gaps[:, 0] = 0.0
        indices[rows], distances[rows] = moved, gaps
    return Neighbors(indices, distances)


def sample_rows(count: int, limit: int, seed: int) -> np.ndarray:
    if not limit or count <= limit:
        return np.arange(count)
    return np.sort(np.random.default_rng(seed).choice(count, limit, replace=False))


@dataclass
class Placement:
    indices: np.ndarray
    weights: np.ndarray

    def apply(self, coords: np.ndarray) -> np.ndarray:
        return (coords[self.indices] * self.weights[..., None]).sum(axis=1)


class NeighborIndex:
    def __init__(self, matrix: np.ndarray):
        from sklearn.neighbors import NearestNeighbors

        self.search = NearestNeighbors(n_neighbors=min(PLACE_NEIGHBORS, len(matrix))).fit(np.asarray(matrix, dtype=np.float32))

    def placement(self, query: np.ndarray) -> Placement:
        distances, indices = self.search.kneighbors(np.asarray(query, dtype=np.float32))
        weights = 1.0 / (distances + 1e-6)
        return Placement(indices, weights / weights.sum(axis=1, keepdims=True))


def embed(matrix: np.ndarray, neighbors: Neighbors | None, min_dist: float, seed: int, dims: int = 2) -> np.ndarray:
    count = matrix.shape[0]
    output = np.zeros((count, dims), dtype=np.float32)
    if count == 0 or not np.any(np.ptp(matrix, axis=0) > 1e-9):
        return output
    if neighbors is None:
        centered = matrix - matrix.mean(axis=0)
        u, s, _ = np.linalg.svd(centered, full_matrices=False)
        width = min(dims, s.size)
        output[:, :width] = u[:, :width] * s[:width]
        return output
    import umap

    components = max(1, min(dims, count - 2))
    reducer = umap.UMAP(
        n_components=components,
        n_neighbors=neighbors.indices.shape[1],
        min_dist=min_dist,
        metric="euclidean",
        random_state=seed,
        n_jobs=1,
        force_approximation_algorithm=True,
        init="spectral" if count >= SPECTRAL_INIT_MIN else "random",
        n_epochs=LAYOUT_EPOCHS,
        precomputed_knn=(neighbors.indices, neighbors.distances, None),
    )
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=r"precomputed_knn\[2\]")
        output[:, :components] = reducer.fit_transform(matrix)
    return output


def warm_up() -> None:
    global _warmed_up
    with _warm_up_lock:
        if _warmed_up:
            return
        started = time.perf_counter()
        try:
            matrix = np.random.default_rng(0).normal(size=(WARM_UP_ROWS, 8)).astype(np.float32)
            embed(matrix, nearest_neighbors(matrix, 15, 0), 0.1, 0)
        except Exception as e:
            AppLogger.warning("[Mapping] Preparing the layout engine failed; the first map will take longer", exc=e)
            return
        _warmed_up = True
        AppLogger.info(f"[Mapping] Prepared the layout engine in {time.perf_counter() - started:.1f}s")


def relabel_by_size(labels: np.ndarray) -> np.ndarray:
    ids, counts = np.unique(labels[labels >= 0], return_counts=True)
    mapping = {old: new for new, old in enumerate(ids[np.argsort(-counts, kind="stable")])}
    return np.array([mapping.get(label, -1) for label in labels.tolist()], dtype=np.int32)


def cluster(space: np.ndarray, min_cluster_size: int, min_samples: int) -> np.ndarray:
    count = space.shape[0]
    if count < 3:
        return np.full(count, -1, dtype=np.int32)
    from sklearn.cluster import HDBSCAN

    size = max(2, min(min_cluster_size, count))
    samples = max(1, min(min_samples, count - 1))
    return relabel_by_size(HDBSCAN(min_cluster_size=size, min_samples=samples, copy=True).fit_predict(space))


def normalize_to_core(points: np.ndarray, percent: float) -> tuple[np.ndarray, np.ndarray]:
    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float32), np.zeros(0, dtype=bool)
    low = np.percentile(points, percent, axis=0)
    high = np.percentile(points, 100 - percent, axis=0)
    span = high - low
    flat = span <= 1e-12
    unit = np.where(flat, 0.5, (points - low) / np.where(flat, 1.0, span))
    outliers = ((unit < 0) | (unit > 1)).any(axis=1)
    return unit.astype(np.float32), outliers


def order_rows(points: np.ndarray, labels: np.ndarray) -> np.ndarray:
    order: list[int] = []
    for group in sorted(set(labels.tolist()), key=lambda g: (g < 0, g)):
        members = np.flatnonzero(labels == group)
        centered = points[members] - points[members].mean(axis=0)
        if len(members) > 2:
            axis = np.linalg.svd(centered, full_matrices=False)[2][0]
            keys = centered @ axis
        else:
            keys = centered[:, 0]
        order.extend(members[np.argsort(keys, kind="stable")].tolist())
    return np.array(order, dtype=np.int64)

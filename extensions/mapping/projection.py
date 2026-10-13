from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SMALL_LAYOUT_LIMIT = 3
SPECTRAL_INIT_MIN = 20


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


def reduce_block(matrix, svd_dims: int, seed: int) -> np.ndarray:
    if not hasattr(matrix, "tocsr"):
        return np.asarray(matrix, dtype=np.float32)
    from sklearn.preprocessing import normalize

    matrix = normalize(matrix.tocsr())
    components = min(svd_dims, matrix.shape[1] - 1, matrix.shape[0] - 1)
    if matrix.shape[1] <= svd_dims or components < 2:
        return matrix.toarray().astype(np.float32)
    from sklearn.decomposition import TruncatedSVD

    return TruncatedSVD(n_components=components, random_state=seed).fit_transform(matrix).astype(np.float32)


def fill_missing(dense: np.ndarray, present: np.ndarray) -> np.ndarray:
    if present.all():
        return dense
    filled = dense.copy()
    filled[~present] = dense[present].mean(axis=0) if present.any() else 0.0
    return filled


def combine_blocks(blocks: list[tuple[str, np.ndarray, np.ndarray, float]], seed: int) -> tuple[np.ndarray, list[BlockStats]]:
    parts: list[np.ndarray] = []
    stats: list[BlockStats] = []
    for label, dense, present, weight in blocks:
        filled = fill_missing(dense, present)
        scale = median_pair_distance(filled[present], seed=seed)
        parts.append(filled / scale * weight)
        stats.append(BlockStats(label, dense.shape[1], scale, int((~present).sum())))
    variances = [float(part.var(axis=0).sum()) for part in parts]
    total = sum(variances)
    for stat, variance in zip(stats, variances):
        stat.contribution = variance / total if total > 0 else 0.0
    return np.hstack(parts).astype(np.float32), stats


def embed(matrix: np.ndarray, n_components: int, n_neighbors: int, min_dist: float, seed: int) -> np.ndarray:
    count = matrix.shape[0]
    output = np.zeros((count, n_components), dtype=np.float32)
    if count == 0 or not np.any(np.ptp(matrix, axis=0) > 1e-9):
        return output
    if count <= SMALL_LAYOUT_LIMIT:
        centered = matrix - matrix.mean(axis=0)
        u, s, _ = np.linalg.svd(centered, full_matrices=False)
        width = min(n_components, s.size)
        output[:, :width] = u[:, :width] * s[:width]
        return output
    import umap

    components = max(1, min(n_components, count - 2))
    reducer = umap.UMAP(
        n_components=components,
        n_neighbors=max(2, min(n_neighbors, count - 1)),
        min_dist=min_dist,
        metric="euclidean",
        random_state=seed,
        n_jobs=1,
        init="spectral" if count >= SPECTRAL_INIT_MIN else "random",
    )
    output[:, :components] = reducer.fit_transform(matrix)
    return output


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


def clip_to_unit(points: np.ndarray, percent: float) -> tuple[np.ndarray, np.ndarray]:
    if len(points) == 0:
        return np.zeros((0, 2), dtype=np.float32), np.zeros(0, dtype=bool)
    low = np.percentile(points, percent, axis=0)
    high = np.percentile(points, 100 - percent, axis=0)
    span = high - low
    flat = span <= 1e-12
    unit = np.where(flat, 0.5, (points - low) / np.where(flat, 1.0, span))
    outliers = ((unit < 0) | (unit > 1)).any(axis=1)
    return np.clip(unit, 0.0, 1.0).astype(np.float32), outliers


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

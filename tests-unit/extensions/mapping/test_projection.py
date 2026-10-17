import pickle

import numpy as np
import pytest
from scipy import sparse

from extensions.mapping import projection


def test_median_pair_distance_known_value():
    assert projection.median_pair_distance(np.array([[0.0, 0.0], [3.0, 4.0]])) == pytest.approx(5.0)


def test_median_pair_distance_degenerate():
    assert projection.median_pair_distance(np.zeros((10, 3))) == 1.0
    assert projection.median_pair_distance(np.zeros((1, 3))) == 1.0


def test_median_pair_distance_sparse_matches_dense():
    rng = np.random.default_rng(0)
    dense = rng.random((30, 5))
    assert projection.median_pair_distance(sparse.csr_matrix(dense)) == pytest.approx(projection.median_pair_distance(dense))


def test_block_reducer_sparse_svd_and_small_vocab():
    rng = np.random.default_rng(0)
    wide = sparse.random(40, 200, density=0.05, random_state=0, format="csr")
    assert projection.BlockReducer(10, 0).fit_transform(wide).shape == (40, 10)
    narrow = sparse.csr_matrix(rng.random((40, 3)))
    assert projection.BlockReducer(10, 0).fit_transform(narrow).shape == (40, 3)
    assert projection.BlockReducer(10, 0).fit_transform(np.ones((4, 2))).dtype == np.float32


def test_block_reducer_transform_matches_fit():
    wide = sparse.random(40, 200, density=0.05, random_state=0, format="csr")
    reducer = projection.BlockReducer(10, 0)
    fitted = reducer.fit_transform(wide)
    assert np.allclose(fitted, reducer.transform(wide), atol=1e-5)
    assert reducer.transform(wide[:3]).shape == (3, 10)


def test_block_reducer_transform_without_svd_and_dense():
    rng = np.random.default_rng(0)
    narrow = sparse.csr_matrix(rng.random((40, 3)))
    reducer = projection.BlockReducer(10, 0)
    assert np.allclose(reducer.fit_transform(narrow), reducer.transform(narrow))
    dense = np.ones((4, 2))
    dense_reducer = projection.BlockReducer(10, 0)
    assert np.allclose(dense_reducer.fit_transform(dense), dense_reducer.transform(dense))


def test_block_reducer_is_picklable():
    wide = sparse.random(40, 200, density=0.05, random_state=0, format="csr")
    reducer = projection.BlockReducer(10, 0)
    fitted = reducer.fit_transform(wide)
    assert np.allclose(pickle.loads(pickle.dumps(reducer)).transform(wide), fitted, atol=1e-5)


def test_combine_blocks_scales_each_block_to_unit_median():
    rng = np.random.default_rng(0)
    big = rng.random((50, 4)) * 1000
    small = rng.random((50, 2)) * 0.001
    present = np.ones(50, dtype=bool)
    combined, stats, _scales = projection.combine_blocks([("big", big, present, 1.0), ("small", small, present, 1.0)], seed=0)
    assert projection.median_pair_distance(combined[:, :4]) == pytest.approx(1.0, rel=0.05)
    assert projection.median_pair_distance(combined[:, 4:]) == pytest.approx(1.0, rel=0.05)
    assert 0.2 < stats[0].contribution < 0.8
    assert stats[1].missing == 0


def test_combine_blocks_missing_rows_use_column_mean_and_all_missing_block():
    dense = np.array([[0.0], [2.0], [9.0]])
    present = np.array([True, True, False])
    combined, stats, _scales = projection.combine_blocks([("a", dense, present, 1.0), ("b", np.zeros((3, 2)), np.zeros(3, dtype=bool), 1.0)], seed=0)
    assert combined[2, 0] == pytest.approx(combined[:2, 0].mean())
    assert stats[0].missing == 1 and stats[1].missing == 3
    assert np.isfinite(combined).all()


def test_apply_block_scales_reproduces_combined_rows():
    rng = np.random.default_rng(0)
    dense = rng.random((30, 3))
    present = np.ones(30, dtype=bool)
    present[0] = False
    combined, _stats, scales = projection.combine_blocks([("a", dense, present, 2.0)], seed=0)
    again = projection.apply_block_scales([(dense, present)], scales)
    assert np.allclose(combined, again)
    assert len(scales) == 1 and scales[0].weight == 2.0


def test_apply_block_scales_fills_new_missing_rows_with_fit_mean():
    dense = np.array([[0.0], [2.0], [4.0]])
    present = np.ones(3, dtype=bool)
    _combined, _stats, scales = projection.combine_blocks([("a", dense, present, 1.0)], seed=0)
    out = projection.apply_block_scales([(np.array([[9.0], [0.0]]), np.array([False, True]))], scales)
    assert out[0, 0] == pytest.approx(scales[0].mean[0] / scales[0].scale)


@pytest.mark.parametrize("count", [1, 2, 3, pytest.param(5, marks=pytest.mark.slow), pytest.param(8, marks=pytest.mark.slow)])
def test_embed_small_counts_do_not_fail(count):
    rng = np.random.default_rng(0)
    matrix = rng.random((count, 6))
    points = projection.embed(matrix, projection.nearest_neighbors(matrix, 15, 0), 0.1, 0)
    assert points.shape == (count, 2)
    assert np.isfinite(points).all()


def test_embed_identical_rows_returns_zeros():
    matrix = np.ones((30, 4))
    assert np.allclose(projection.embed(matrix, projection.nearest_neighbors(matrix, 15, 0), 0.1, 0), 0.0)


def test_cluster_separates_blobs_and_noise():
    rng = np.random.default_rng(0)
    blobs = [rng.normal(center, 0.05, size=(40, 2)) for center in ((0, 0), (5, 5), (0, 5))]
    outlier = np.array([[20.0, -20.0]])
    labels = projection.cluster(np.vstack(blobs + [outlier]), 10, 5)
    assert set(labels.tolist()) - {-1} == {0, 1, 2}
    assert (labels[:120] == -1).mean() < 0.1
    assert labels[-1] == -1


def test_cluster_tiny_input():
    assert projection.cluster(np.zeros((2, 2)), 5, 5).tolist() == [-1, -1]


def test_relabel_by_size_largest_first():
    assert projection.relabel_by_size(np.array([3, 3, 7, 7, 7, -1])).tolist() == [1, 1, 0, 0, 0, -1]


def test_normalize_to_core_marks_outliers_and_keeps_their_distance():
    points = np.vstack([np.linspace(0, 1, 98)[:, None].repeat(2, axis=1), [[100.0, 100.0], [-100.0, -100.0]]])
    unit, outliers = projection.normalize_to_core(points, 1.0)
    assert unit[:-2].min() >= -0.05 and unit[:-2].max() <= 1.05
    assert unit[-2, 0] > 10 and unit[-1, 0] < -10
    assert outliers[-1] and outliers[-2]
    assert outliers.sum() == 2


def test_normalize_to_core_degenerate_centers():
    unit, outliers = projection.normalize_to_core(np.zeros((5, 2)), 1.0)
    assert np.allclose(unit, 0.5) and not outliers.any()


def test_order_rows_groups_then_noise():
    points = np.array([[0.9, 0.0], [0.1, 0.0], [0.5, 0.5], [0.2, 0.9], [0.8, 0.9]])
    labels = np.array([0, 0, -1, 1, 1])
    order = projection.order_rows(points, labels).tolist()
    assert sorted(order) == [0, 1, 2, 3, 4]
    assert set(order[:2]) == {0, 1} and set(order[2:4]) == {3, 4} and order[4] == 2


@pytest.mark.slow
def test_embed_real_umap_keeps_blobs_apart():
    rng = np.random.default_rng(0)
    data = np.vstack([rng.normal(0, 0.1, (60, 8)), rng.normal(5, 0.1, (60, 8))])
    points = projection.embed(data, projection.nearest_neighbors(data, 15, 0), 0.1, 0)
    gap = np.linalg.norm(points[:60].mean(axis=0) - points[60:].mean(axis=0))
    spread = points[:60].std(axis=0).mean()
    assert gap > spread * 3


def test_warm_up_runs_the_layout_once(monkeypatch):
    monkeypatch.setattr(projection, "_warmed_up", False)
    calls = []
    monkeypatch.setattr(projection, "embed", lambda *args: calls.append(args[0].shape))
    projection.warm_up()
    projection.warm_up()
    assert calls == [(projection.WARM_UP_ROWS, 8)]


def test_failed_warm_up_is_logged_and_retried_later(monkeypatch):
    monkeypatch.setattr(projection, "_warmed_up", False)
    warnings = []
    monkeypatch.setattr(projection.AppLogger, "warning", lambda message, exc=None: warnings.append(message))
    monkeypatch.setattr(projection, "embed", lambda *args: (_ for _ in ()).throw(RuntimeError("boom")))
    projection.warm_up()
    assert warnings and not projection._warmed_up


def brute_neighbors(matrix, k):
    from sklearn.neighbors import NearestNeighbors

    return NearestNeighbors(n_neighbors=k, algorithm="brute").fit(matrix).kneighbors(matrix)


def test_exact_neighbors_match_brute_force_with_each_point_first():
    matrix = np.random.default_rng(0).normal(size=(200, 12)).astype(np.float32)
    found = projection.nearest_neighbors(matrix, 10, 0)
    distances, indices = brute_neighbors(matrix, 10)
    assert found.indices.shape == (200, 10)
    assert (found.indices[:, 0] == np.arange(200)).all() and np.allclose(found.distances[:, 0], 0.0)
    assert all(set(a) == set(b) for a, b in zip(found.indices.tolist(), indices.tolist()))
    assert np.allclose(found.distances, distances, atol=1e-3)


def test_duplicate_rows_still_list_themselves_first():
    matrix = np.vstack([np.ones((10, 3)), np.random.default_rng(2).normal(size=(10, 3))])
    found = projection.nearest_neighbors(matrix, 5, 0)
    assert (found.indices[:, 0] == np.arange(20)).all()


def test_neighbor_count_is_clamped_and_tiny_inputs_need_no_search():
    matrix = np.random.default_rng(3).normal(size=(6, 3))
    assert projection.nearest_neighbors(matrix, 50, 0).indices.shape == (6, 5)
    assert projection.nearest_neighbors(matrix[:3], 15, 0) is None


@pytest.mark.slow
def test_large_inputs_use_the_approximate_search(monkeypatch):
    monkeypatch.setattr(projection, "EXACT_NEIGHBORS_LIMIT", 50)
    matrix = np.random.default_rng(4).normal(size=(120, 5)).astype(np.float32)
    found = projection.nearest_neighbors(matrix, 10, 0)
    _, indices = brute_neighbors(matrix, 10)
    recall = np.mean([len(set(a) & set(b)) / 10 for a, b in zip(found.indices.tolist(), indices.tolist())])
    assert recall > 0.9


def test_layout_reuses_the_given_neighbors_with_fixed_epochs(monkeypatch):
    import umap

    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def fit_transform(self, matrix):
            return np.zeros((matrix.shape[0], 2), dtype=np.float32)

    monkeypatch.setattr(umap, "UMAP", Recorder)
    matrix = np.random.default_rng(5).normal(size=(40, 4))
    neighbors = projection.nearest_neighbors(matrix, 9, 0)
    projection.embed(matrix, neighbors, 0.2, 3)
    assert seen["n_neighbors"] == 9 and seen["n_epochs"] == projection.LAYOUT_EPOCHS
    assert seen["precomputed_knn"][0] is neighbors.indices and seen["random_state"] == 3


def test_more_duplicates_than_neighbors_still_list_themselves_first():
    matrix = np.vstack([np.ones((12, 3)), np.random.default_rng(6).normal(size=(8, 3))])
    found = projection.nearest_neighbors(matrix, 4, 0)
    assert (found.indices[:, 0] == np.arange(20)).all() and np.allclose(found.distances[:12], 0.0)
    assert all(len(set(row)) == 4 for row in found.indices.tolist())


def test_sample_rows_is_sorted_seeded_and_keeps_everything_under_the_limit():
    assert np.array_equal(projection.sample_rows(5, 10, 0), np.arange(5))
    assert np.array_equal(projection.sample_rows(5, 0, 0), np.arange(5))
    rows = projection.sample_rows(100, 10, 3)
    assert rows.size == 10 and np.array_equal(rows, np.sort(rows))
    assert np.array_equal(rows, projection.sample_rows(100, 10, 3))
    assert not np.array_equal(rows, projection.sample_rows(100, 10, 4))


def test_placement_averages_the_nearest_trained_points():
    trained = np.array([[0.0, 0.0], [10.0, 0.0], [0.0, 10.0], [10.0, 10.0]], dtype=np.float32)
    coords = trained * 2
    placement = projection.NeighborIndex(trained).placement(np.array([[0.0, 0.0], [9.0, 9.0]]))
    placed = placement.apply(coords)
    assert np.allclose(placed[0], coords[0], atol=1e-3)
    assert np.linalg.norm(placed[1] - coords[3]) < np.linalg.norm(placed[1] - coords[0])
    assert np.allclose(placement.weights.sum(axis=1), 1.0)


def test_embed_can_return_more_dimensions(monkeypatch):
    import umap

    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def fit_transform(self, matrix):
            return np.ones((matrix.shape[0], seen["n_components"]), dtype=np.float32)

    monkeypatch.setattr(umap, "UMAP", Recorder)
    matrix = np.random.default_rng(6).normal(size=(40, 12))
    points = projection.embed(matrix, projection.nearest_neighbors(matrix, 9, 0), 0.0, 1, projection.GROUPING_DIMS)
    assert points.shape == (40, projection.GROUPING_DIMS) and seen["n_components"] == projection.GROUPING_DIMS
    tiny = projection.embed(matrix[:3], None, 0.0, 1, projection.GROUPING_DIMS)
    assert tiny.shape == (3, projection.GROUPING_DIMS) and np.isfinite(tiny).all()


def test_cluster_passes_the_selection_method(monkeypatch):
    import sklearn.cluster

    seen = {}

    class Recorder:
        def __init__(self, **kwargs):
            seen.update(kwargs)

        def fit_predict(self, space):
            return np.zeros(len(space), dtype=np.int32)

    monkeypatch.setattr(sklearn.cluster, "HDBSCAN", Recorder)
    projection.cluster(np.random.default_rng(0).normal(size=(20, 2)), 5, 3, "leaf")
    assert (seen["min_cluster_size"], seen["min_samples"], seen["cluster_selection_method"]) == (5, 3, "leaf")

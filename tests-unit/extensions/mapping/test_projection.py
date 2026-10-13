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


def test_reduce_block_sparse_svd_and_small_vocab():
    rng = np.random.default_rng(0)
    wide = sparse.random(40, 200, density=0.05, random_state=0, format="csr")
    assert projection.reduce_block(wide, 10, 0).shape == (40, 10)
    narrow = sparse.csr_matrix(rng.random((40, 3)))
    assert projection.reduce_block(narrow, 10, 0).shape == (40, 3)
    assert projection.reduce_block(np.ones((4, 2)), 10, 0).dtype == np.float32


def test_combine_blocks_scales_each_block_to_unit_median():
    rng = np.random.default_rng(0)
    big = rng.random((50, 4)) * 1000
    small = rng.random((50, 2)) * 0.001
    present = np.ones(50, dtype=bool)
    combined, stats = projection.combine_blocks([("big", big, present, 1.0), ("small", small, present, 1.0)], seed=0)
    assert projection.median_pair_distance(combined[:, :4]) == pytest.approx(1.0, rel=0.05)
    assert projection.median_pair_distance(combined[:, 4:]) == pytest.approx(1.0, rel=0.05)
    assert 0.2 < stats[0].contribution < 0.8
    assert stats[1].missing == 0


def test_combine_blocks_missing_rows_use_column_mean_and_all_missing_block():
    dense = np.array([[0.0], [2.0], [9.0]])
    present = np.array([True, True, False])
    combined, stats = projection.combine_blocks(
        [("a", dense, present, 1.0), ("b", np.zeros((3, 2)), np.zeros(3, dtype=bool), 1.0)], seed=0
    )
    assert combined[2, 0] == pytest.approx(combined[:2, 0].mean())
    assert stats[0].missing == 1 and stats[1].missing == 3
    assert np.isfinite(combined).all()


@pytest.mark.parametrize("count", [1, 2, 3, pytest.param(5, marks=pytest.mark.slow), pytest.param(8, marks=pytest.mark.slow)])
def test_embed_small_counts_do_not_fail(count):
    rng = np.random.default_rng(0)
    points = projection.embed(rng.random((count, 6)), 2, 15, 0.1, 0)
    assert points.shape == (count, 2)
    assert np.isfinite(points).all()


def test_embed_identical_rows_returns_zeros():
    assert np.allclose(projection.embed(np.ones((30, 4)), 2, 15, 0.1, 0), 0.0)


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


def test_clip_to_unit_marks_outliers():
    points = np.vstack([np.linspace(0, 1, 98)[:, None].repeat(2, axis=1), [[100.0, 100.0], [-100.0, -100.0]]])
    unit, outliers = projection.clip_to_unit(points, 1.0)
    assert unit.min() >= 0.0 and unit.max() <= 1.0
    assert outliers[-1] and outliers[-2]
    assert outliers.sum() == 2


def test_clip_to_unit_degenerate_centers():
    unit, outliers = projection.clip_to_unit(np.zeros((5, 2)), 1.0)
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
    points = projection.embed(data, 2, 15, 0.1, 0)
    gap = np.linalg.norm(points[:60].mean(axis=0) - points[60:].mean(axis=0))
    spread = points[:60].std(axis=0).mean()
    assert gap > spread * 3

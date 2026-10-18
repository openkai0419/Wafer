import pytest

from extensions.mapping.params import MAX_NEIGHBORS, STAGES, MapParams, changed_stage, param_specs


def test_every_param_has_stage_and_description():
    specs = param_specs()
    assert specs
    for name, spec, default in specs:
        assert spec.stage in STAGES, name
        assert spec.label and spec.description, name
        assert spec.minimum <= default <= spec.maximum, name


def test_values_for_groups_by_stage():
    params = MapParams()
    assert MapParams(label_terms=5).values_for("layout") == params.values_for("layout")
    assert MapParams(min_dist=0.5).values_for("layout") != params.values_for("layout")


def test_key_settings_are_not_params():
    names = {name for name, _spec, _default in param_specs()}
    assert not names & {"ngram_min", "ngram_max", "svd_dims", "min_cluster_size", "min_samples"}
    assert STAGES == ("layout", "view")


def test_changed_stage_returns_earliest():
    base = MapParams()
    assert changed_stage(base, base) is None
    assert changed_stage(base, MapParams(min_dist=0.3)) == "layout"
    assert changed_stage(base, MapParams(min_dist=0.3, label_terms=5)) == "layout"
    assert changed_stage(base, MapParams(label_terms=5)) == "view"


def test_normalized_clamps():
    assert MapParams(min_dist=9.0).normalized().min_dist == 1.0


def test_dict_roundtrip_ignores_unknown_and_bad_values():
    data = MapParams(seed=7).to_dict() | {"unknown": 1, "min_dist": "bad"}
    params = MapParams.from_dict(data)
    assert params.seed == 7
    assert params.min_dist == MapParams().min_dist


def test_cluster_options_follow_the_number_of_files():
    params = MapParams()
    assert params.cluster_options(100) == (5, 5, "eom")
    assert params.cluster_options(5000) == (10, 10, "eom")
    assert params.cluster_options(20000) == params.cluster_options(1_000_000) == (30, 10, "eom")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 10**400, "inf", "nan"])
def test_from_dict_ignores_non_finite_values(bad):
    params = MapParams.from_dict({"seed": bad, "min_dist": bad, "neighbors": bad, "train_limit": bad})
    assert params.seed == MapParams().seed
    assert params.min_dist == MapParams().min_dist
    assert params.neighbors == MapParams().neighbors
    assert params.train_limit == MapParams().train_limit


def test_normalized_resets_non_finite_fields_to_default():
    params = MapParams(seed=float("nan"), min_dist=float("inf"), neighbors=float("-inf")).normalized()
    defaults = MapParams()
    assert (params.seed, params.min_dist, params.neighbors) == (defaults.seed, defaults.min_dist, defaults.neighbors)


def test_hover_size_is_a_view_param_clamped_to_range():
    spec = next(spec for name, spec, _ in param_specs() if name == "hover_size")
    assert (spec.stage, spec.minimum, spec.maximum, spec.step) == ("view", 0, 1024, 32)
    assert MapParams().hover_size == 256
    assert MapParams(hover_size=5000).normalized().hover_size == 1024
    assert MapParams(hover_size=-3).normalized().hover_size == 0
    assert changed_stage(MapParams(), MapParams(hover_size=0)) == "view"


def test_neighbors_keep_the_same_share_of_the_trained_files():
    params = MapParams()
    assert params.neighbors == 1.0
    assert params.resolved_neighbors(3000) == 15
    assert params.resolved_neighbors(20000) == 100
    assert params.resolved_neighbors(110000) == 550
    assert params.resolved_neighbors(150_000) == 750


def test_neighbors_setting_scales_the_automatic_count():
    assert MapParams(neighbors=2.0).resolved_neighbors(20000) == 200
    assert MapParams(neighbors=0.5).resolved_neighbors(20000) == 50
    assert MapParams(neighbors=0.5).resolved_neighbors(100) == 8
    assert MapParams(neighbors=0.25).resolved_neighbors(100) >= 2


def test_old_fixed_neighbor_count_is_dropped():
    assert MapParams.from_dict({"n_neighbors": 15}).neighbors == 1.0


def test_training_limit_is_a_layout_setting_where_zero_means_all():
    spec = next(spec for name, spec, _ in param_specs() if name == "train_limit")
    assert spec.stage == "layout" and spec.minimum == 0
    assert MapParams().train_limit == 10000
    assert MapParams(train_limit=-5).normalized().train_limit == 0
    assert changed_stage(MapParams(), MapParams(train_limit=5000)) == "layout"


def test_neighbors_never_exceed_the_cap():
    assert MapParams().resolved_neighbors(1_000_000) == MAX_NEIGHBORS == 1000
    assert MapParams(neighbors=4.0).resolved_neighbors(100_000) == MAX_NEIGHBORS


def test_group_size_setting_scales_the_automatic_size():
    spec = next(spec for name, spec, _ in param_specs() if name == "group_size")
    assert spec.stage == "view" and MapParams().group_size == 1.0
    assert MapParams(group_size=2.0).cluster_options(5000) == (20, 10, "eom")
    assert MapParams(group_size=0.5).cluster_options(5000) == (5, 5, "eom")
    assert MapParams(group_size=0.25).cluster_options(100) == (2, 2, "eom")
    assert changed_stage(MapParams(), MapParams(group_size=2.0)) == "view"


def test_strictness_scales_how_dense_a_group_must_be():
    assert MapParams(group_strictness=0.5).cluster_options(5000) == (10, 5, "eom")
    assert MapParams(group_strictness=2.0).cluster_options(5000) == (10, 20, "eom")
    assert MapParams(group_strictness=0.25).cluster_options(100) == (5, 1, "eom")


def test_fine_groups_pick_the_leaf_clusters():
    assert MapParams(fine_groups=1).cluster_options(5000)[2] == "leaf"
    assert MapParams(fine_groups=5).normalized().fine_groups == 1
    for name in ("group_strictness", "fine_groups"):
        spec = next(spec for key, spec, _ in param_specs() if key == name)
        assert spec.stage == "view"


def test_group_factors_reach_sixteen():
    for name in ("group_size", "group_strictness"):
        spec = next(spec for key, spec, _ in param_specs() if key == name)
        assert (spec.minimum, spec.maximum) == (0.25, 16.0)
    assert MapParams(group_size=99, group_strictness=99).normalized().group_size == 16.0
    assert MapParams(group_size=16.0).cluster_options(5000) == (160, 10, "eom")

import pytest

from extensions.mapping.params import STAGES, MapParams, changed_stage, min_group_size, noise_strictness, param_specs


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


def test_group_sizes_follow_the_number_of_files():
    assert min_group_size(100) == 5
    assert min_group_size(5000) == 10
    assert min_group_size(20000) == min_group_size(1_000_000) == 30
    assert noise_strictness(100) == 5
    assert noise_strictness(20000) == 10


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 10**400, "inf", "nan"])
def test_from_dict_ignores_non_finite_values(bad):
    params = MapParams.from_dict({"seed": bad, "min_dist": bad, "n_neighbors": bad})
    assert params.seed == MapParams().seed
    assert params.min_dist == MapParams().min_dist
    assert params.n_neighbors == MapParams().n_neighbors


def test_normalized_resets_non_finite_fields_to_default():
    params = MapParams(seed=float("nan"), min_dist=float("inf"), n_neighbors=float("-inf")).normalized()
    defaults = MapParams()
    assert (params.seed, params.min_dist, params.n_neighbors) == (defaults.seed, defaults.min_dist, defaults.n_neighbors)


def test_hover_size_is_a_view_param_clamped_to_range():
    spec = next(spec for name, spec, _ in param_specs() if name == "hover_size")
    assert (spec.stage, spec.minimum, spec.maximum, spec.step) == ("view", 0, 1024, 32)
    assert MapParams().hover_size == 256
    assert MapParams(hover_size=5000).normalized().hover_size == 1024
    assert MapParams(hover_size=-3).normalized().hover_size == 0
    assert changed_stage(MapParams(), MapParams(hover_size=0)) == "view"


def test_auto_neighbors_follow_the_file_count():
    params = MapParams()
    assert params.n_neighbors == 0
    assert params.resolved_neighbors(3000) == 15
    assert params.resolved_neighbors(20000) == 100
    assert params.resolved_neighbors(110000) == params.resolved_neighbors(5_000_000) == 200
    assert MapParams(n_neighbors=30).resolved_neighbors(110000) == 30

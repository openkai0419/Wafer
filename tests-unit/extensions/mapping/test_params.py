import pytest

from extensions.mapping.params import MAX_NEIGHBORS, Grouping, TrainParams, ViewParams, param_specs


@pytest.mark.parametrize("params_class", [TrainParams, ViewParams, Grouping])
def test_every_param_has_a_description_and_a_default_in_range(params_class):
    specs = param_specs(params_class)
    assert specs
    for name, spec, default in specs:
        assert spec.label and spec.description, name
        assert spec.minimum <= default <= spec.maximum, name


def test_training_and_view_settings_are_separate():
    train = {name for name, _spec, _default in param_specs(TrainParams)}
    view = {name for name, _spec, _default in param_specs(ViewParams)}
    assert train == {"neighbors", "train_limit", "min_dist", "seed"}
    assert view == {"outlier_percent", "subgroup_size", "point_size", "image_spacing", "max_images", "hover_size"}
    assert not train & {"ngram_min", "ngram_max", "svd_dims", "min_cluster_size", "min_samples"}


def test_normalized_clamps():
    assert TrainParams(min_dist=9.0).normalized().min_dist == 1.0


def test_normalized_drops_float_step_residue():
    assert TrainParams(min_dist=1.3877787807814457e-17).normalized().min_dist == 0.0
    assert TrainParams.from_dict({"min_dist": 0.30000000000000004}).min_dist == 0.3


def test_dict_roundtrip_ignores_unknown_and_bad_values():
    data = TrainParams(seed=7).to_dict() | {"unknown": 1, "min_dist": "bad"}
    params = TrainParams.from_dict(data)
    assert params.seed == 7
    assert params.min_dist == TrainParams().min_dist


def test_saved_view_values_in_a_training_preset_are_ignored():
    saved = TrainParams(seed=3).to_dict() | ViewParams(point_size=9).to_dict()
    assert TrainParams.from_dict(saved) == TrainParams(seed=3)


def test_cluster_options_follow_the_number_of_files():
    grouping = Grouping()
    assert grouping.cluster_options(100) == (5, 5, "eom")
    assert grouping.cluster_options(5000) == (10, 10, "eom")
    assert grouping.cluster_options(20000) == (40, 10, "eom")
    assert grouping.cluster_options(111_500) == (223, 10, "eom")
    assert grouping.cluster_options(1_000_000) == (2000, 10, "eom")


@pytest.mark.parametrize("bad", [float("inf"), float("-inf"), float("nan"), 10**400, "inf", "nan"])
def test_from_dict_ignores_non_finite_values(bad):
    params = TrainParams.from_dict({"seed": bad, "min_dist": bad, "neighbors": bad, "train_limit": bad})
    assert params.seed == TrainParams().seed
    assert params.min_dist == TrainParams().min_dist
    assert params.neighbors == TrainParams().neighbors
    assert params.train_limit == TrainParams().train_limit


def test_normalized_resets_non_finite_fields_to_default():
    params = TrainParams(seed=float("nan"), min_dist=float("inf"), neighbors=float("-inf")).normalized()
    defaults = TrainParams()
    assert (params.seed, params.min_dist, params.neighbors) == (defaults.seed, defaults.min_dist, defaults.neighbors)


def test_hover_size_is_clamped_to_range():
    spec = next(spec for name, spec, _ in param_specs(ViewParams) if name == "hover_size")
    assert (spec.minimum, spec.maximum, spec.step) == (0, 1024, 32)
    assert ViewParams().hover_size == 256
    assert ViewParams(hover_size=5000).normalized().hover_size == 1024
    assert ViewParams(hover_size=-3).normalized().hover_size == 0


def test_neighbors_keep_the_same_share_of_the_trained_files():
    params = TrainParams()
    assert params.neighbors == 1.0
    assert params.resolved_neighbors(3000) == 15
    assert params.resolved_neighbors(20000) == 100
    assert params.resolved_neighbors(110000) == 550
    assert params.resolved_neighbors(150_000) == 750


def test_neighbors_setting_scales_the_automatic_count():
    assert TrainParams(neighbors=2.0).resolved_neighbors(20000) == 200
    assert TrainParams(neighbors=0.5).resolved_neighbors(20000) == 50
    assert TrainParams(neighbors=0.5).resolved_neighbors(100) == 8
    assert TrainParams(neighbors=0.25).resolved_neighbors(100) >= 2


def test_old_fixed_neighbor_count_is_dropped():
    assert TrainParams.from_dict({"n_neighbors": 15}).neighbors == 1.0


def test_training_limit_where_zero_means_all():
    spec = next(spec for name, spec, _ in param_specs(TrainParams) if name == "train_limit")
    assert spec.minimum == 0
    assert TrainParams().train_limit == 10000
    assert TrainParams(train_limit=-5).normalized().train_limit == 0


def test_neighbors_never_exceed_the_cap():
    assert TrainParams().resolved_neighbors(1_000_000) == MAX_NEIGHBORS == 1000
    assert TrainParams(neighbors=4.0).resolved_neighbors(100_000) == MAX_NEIGHBORS


def test_group_size_setting_scales_the_automatic_size():
    spec = next(spec for name, spec, _ in param_specs(Grouping) if name == "size")
    assert (spec.minimum, spec.maximum) == (0.25, 16.0) and Grouping().size == 1.0
    assert Grouping(size=0.5).cluster_options(5000) == (5, 5, "eom")
    assert Grouping(size=0.25).cluster_options(100) == (2, 2, "eom")
    assert Grouping(size=4.0).cluster_options(5000) == (40, 10, "eom")


def test_strictness_follows_the_final_group_size_up_to_ten():
    assert Grouping(size=0.5, strictness=2.0).cluster_options(3000) == (3, 6, "eom")
    assert Grouping(size=0.25).cluster_options(111_500) == (56, 10, "eom")
    assert Grouping().cluster_options(111_500, share=0.0625) == (14, 10, "eom")
    assert Grouping(size=99.0).normalized().size == 16.0


def test_mapping_share_shrinks_the_base_group_size():
    assert Grouping().cluster_options(1_000_000, share=0.5) == (1000, 10, "eom")
    assert Grouping(size=0.5).cluster_options(1_000_000, share=0.25) == (250, 10, "eom")
    assert Grouping().cluster_options(100, share=0.0625) == (2, 2, "eom")
    spec = next(spec for name, spec, _ in param_specs(ViewParams) if name == "subgroup_size")
    assert (spec.minimum, spec.maximum) == (0.03125, 1.0) and ViewParams().subgroup_size == 0.05


def test_strictness_scales_how_dense_a_group_must_be():
    assert Grouping(strictness=0.5).cluster_options(5000) == (10, 5, "eom")
    assert Grouping(strictness=2.0).cluster_options(5000) == (10, 20, "eom")
    assert Grouping(strictness=0.25).cluster_options(100) == (5, 1, "eom")


def test_fine_groups_pick_the_leaf_clusters():
    assert Grouping(fine=1).cluster_options(5000)[2] == "leaf"
    assert Grouping(fine=5).normalized().fine == 1
    assert Grouping.from_dict({"size": "x", "strictness": 2, "fine": 1}) == Grouping(strictness=2.0, fine=1)


def test_group_factors_reach_sixteen():
    spec = next(spec for key, spec, _ in param_specs(Grouping) if key == "strictness")
    assert (spec.minimum, spec.maximum) == (0.25, 16.0)
    assert Grouping(strictness=99).normalized().strictness == 16.0


def test_there_is_no_label_word_setting():
    assert "label_terms" not in {name for name, _spec, _default in param_specs(ViewParams)}


def test_map_group_size_starts_small():
    assert ViewParams().subgroup_size == 0.05
    spec = next(spec for name, spec, _ in param_specs(ViewParams) if name == "subgroup_size")
    assert spec.minimum <= 0.05

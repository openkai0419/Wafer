from extensions.mapping.params import STAGES, MapParams, changed_stage, param_specs


def test_every_param_has_stage_and_description():
    specs = param_specs()
    assert specs
    for name, spec, default in specs:
        assert spec.stage in STAGES, name
        assert spec.label and spec.description, name
        assert spec.minimum <= default <= spec.maximum, name


def test_values_for_groups_by_stage():
    params = MapParams()
    assert params.values_for("reduce") == (50,)
    assert MapParams(min_dist=0.5).values_for("encode") == params.values_for("encode")


def test_changed_stage_returns_earliest():
    base = MapParams()
    assert changed_stage(base, base) is None
    assert changed_stage(base, MapParams(min_dist=0.3)) == "layout"
    assert changed_stage(base, MapParams(min_dist=0.3, ngram_min=3)) == "encode"
    assert changed_stage(base, MapParams(label_terms=5)) == "view"


def test_normalized_clamps_and_orders_ngrams():
    params = MapParams(ngram_min=5, ngram_max=2, min_dist=9.0).normalized()
    assert params.ngram_max == 5
    assert params.min_dist == 1.0


def test_dict_roundtrip_ignores_unknown_and_bad_values():
    data = MapParams(seed=7).to_dict() | {"unknown": 1, "min_dist": "bad"}
    params = MapParams.from_dict(data)
    assert params.seed == 7
    assert params.min_dist == MapParams().min_dist


def test_auto_cluster_size():
    params = MapParams()
    assert params.resolved_min_cluster_size(100) == 5
    assert params.resolved_min_cluster_size(3000) == 30
    assert params.resolved_min_samples(3000) == 30
    assert MapParams(min_samples=4).resolved_min_samples(3000) == 4

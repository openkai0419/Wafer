import numpy as np
import pytest

from extensions.mapping import projection, session
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec, MapError, MapPipeline, MapRequest
from wafer.core.db.path_values import PathValue


@pytest.fixture()
def embed_calls(monkeypatch):
    calls = []

    def fake_embed(matrix, n_components, n_neighbors, min_dist, seed):
        calls.append(n_components)
        return jittered_copy(matrix, n_components)

    monkeypatch.setattr(projection, "embed", fake_embed)
    return calls


def jittered_copy(matrix, n_components):
    output = np.zeros((matrix.shape[0], n_components), dtype=np.float32)
    width = min(n_components, matrix.shape[1])
    noise = np.random.default_rng(0).normal(0, 1e-3, (matrix.shape[0], width))
    output[:, :width] = matrix[:, :width] + noise
    return output


def make_request(count=40, grouping=True, features=None, params=None):
    paths = [f"c:/{i}.png" for i in range(count)]
    values = {
        p: {
            "tags": PathValue("cat, sky" if i < count // 2 else "dog, sea"),
            "modified": PathValue(str(i), float(i)),
        }
        for i, p in enumerate(paths)
    }
    features = [FeatureSpec("tags", "token_set")] if features is None else features
    return MapRequest(paths, values, features, params or MapParams(), grouping)


def pipeline():
    return MapPipeline(lambda path: np.full((8, 8, 3), 128, dtype=np.uint8))


def test_run_produces_positions_groups_and_terms(embed_calls):
    result = pipeline().run(make_request())
    assert result.positions.shape == (40, 2)
    assert np.isfinite(result.positions).all()
    assert result.labels is not None and set(result.labels.tolist()) <= {-1, 0, 1}
    assert sorted(result.order.tolist()) == list(range(40))
    assert any({"cat", "sky"} & set(words) for words in result.group_terms.values())


def test_grouping_off_skips_clustering(embed_calls):
    result = pipeline().run(make_request(grouping=False))
    assert result.labels is None and result.group_terms == {}
    assert embed_calls == [2]


def test_cluster_only_change_does_not_rerun_layout(embed_calls):
    runner = pipeline()
    runner.run(make_request())
    embed_calls.clear()
    runner.run(make_request(params=MapParams(min_cluster_size=3)))
    assert embed_calls == []


def test_view_only_change_does_not_rerun_layout(embed_calls):
    runner = pipeline()
    runner.run(make_request())
    embed_calls.clear()
    runner.run(make_request(params=MapParams(clip_percent=5.0, label_terms=1)))
    assert embed_calls == []


def test_weight_change_reruns_layout_but_not_encoding(embed_calls, monkeypatch):
    runner = pipeline()
    runner.run(make_request())
    encoded = []
    original = session.ENCODERS["token_set"].encode
    monkeypatch.setattr(session.ENCODERS["token_set"], "encode", lambda self, *a: encoded.append(1) or original(self, *a))
    embed_calls.clear()
    runner.run(make_request(features=[FeatureSpec("tags", "token_set", weight=2.0)]))
    assert embed_calls and encoded == []


def test_unset_rows_are_excluded(embed_calls):
    request = make_request(count=10)
    for p in request.paths[:2]:
        request.values[p] = {}
    result = pipeline().run(request)
    assert result.unset.tolist()[:3] == [True, True, False]
    assert np.isnan(result.positions[0]).all()
    assert result.order.tolist()[-2:] == [0, 1]


def test_all_missing_key_with_another_key(embed_calls):
    features = [FeatureSpec("tags", "token_set"), FeatureSpec("missing", "text")]
    result = pipeline().run(make_request(features=features))
    assert result.diagnostics.blocks[1].missing == 40


def test_errors_for_too_few_files_and_no_features():
    with pytest.raises(MapError):
        pipeline().run(make_request(count=2))
    with pytest.raises(MapError):
        pipeline().run(make_request(features=[]))


def test_three_files_work():
    result = pipeline().run(make_request(count=3))
    assert np.isfinite(result.positions).all()


def test_image_feature_uses_pixel_cache(embed_calls):
    loads = []
    runner = MapPipeline(lambda path: loads.append(path) or np.full((8, 8, 3), 100, dtype=np.uint8))
    request = make_request(count=5, features=[FeatureSpec(None, "image_color")])
    runner.run(request)
    runner.run(make_request(count=5, features=[FeatureSpec(None, "image_color")], params=MapParams(image_grid=4)))
    assert len(loads) == 5


def test_cancelled_returns_none():
    assert pipeline().run(make_request(), cancelled=lambda: True) is None


def test_feature_spec_roundtrip_and_validation():
    spec = FeatureSpec("tags", "token_set", 1.5, {"separator": "space"})
    assert FeatureSpec.from_dict(spec.to_dict()) == spec
    assert FeatureSpec.from_dict({"key": "x", "encoder": "nope"}) is None
    assert FeatureSpec.from_dict({"key": "x", "encoder": "image_color"}) is None
    assert FeatureSpec.from_dict({"key": None, "encoder": "text"}) is None


@pytest.mark.parametrize("weight, expected", [(float("inf"), 1.0), (float("nan"), 1.0), (10**400, 1.0), (99, 3.0), (-2, 0.0), ("x", 1.0)])
def test_feature_spec_sanitizes_weight(weight, expected):
    spec = FeatureSpec.from_dict({"key": "tags", "encoder": "token_set", "weight": weight})
    assert spec.weight == expected


def test_feature_spec_ignores_non_dict_options_and_data():
    spec = FeatureSpec.from_dict({"key": "tags", "encoder": "token_set", "options": "space"})
    assert spec is not None and spec.options == {}
    assert FeatureSpec.from_dict("garbage") is None
    assert FeatureSpec.from_dict(None) is None
    assert FeatureSpec.from_dict([1, 2]) is None


def test_cancelled_before_start_encodes_nothing(monkeypatch):
    calls = []
    original = ENCODERS["token_set"].encode
    monkeypatch.setattr(ENCODERS["token_set"], "encode", lambda self, inputs, params: calls.append(1) or original(self, inputs, params))
    assert pipeline().run(make_request(), cancelled=lambda: True) is None
    assert calls == []


def test_cancel_between_features_skips_remaining_encodes(monkeypatch):
    calls = []
    original = ENCODERS["token_set"].encode
    monkeypatch.setattr(ENCODERS["token_set"], "encode", lambda self, inputs, params: calls.append(1) or original(self, inputs, params))
    features = [FeatureSpec("tags", "token_set"), FeatureSpec("tags", "token_set", options={"separator": "comma"})]
    assert pipeline().run(make_request(features=features), cancelled=lambda: len(calls) >= 1) is None
    assert calls == [1]

import numpy as np
import pytest

from extensions.mapping import projection, session
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec, MapError, MapPipeline, MapRequest, layout_from_space
from extensions.mapping.space import Preset
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


def make_request(count=40, features=None, params=None):
    paths = [f"c:/{i}.png" for i in range(count)]
    values = {
        p: {
            "tags": PathValue("cat, sky" if i < count // 2 else "dog, sea"),
            "modified": PathValue(str(i), float(i)),
        }
        for i, p in enumerate(paths)
    }
    features = [FeatureSpec("tags", "token_set")] if features is None else features
    return MapRequest(paths, values, features, params or MapParams())


def pipeline():
    return MapPipeline()


def test_run_produces_positions_groups_and_terms(embed_calls):
    result = pipeline().run(make_request())
    assert result.positions.shape == (40, 2)
    assert np.isfinite(result.positions).all()
    assert result.labels is not None and set(result.labels.tolist()) <= {-1, 0, 1}
    assert sorted(result.order.tolist()) == list(range(40))
    assert any({"cat", "sky"} & set(words) for words in result.group_terms.values())


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
    runner.run(make_request(params=MapParams(outlier_percent=5.0, label_terms=1)))
    assert embed_calls == []


def test_weight_change_reruns_layout_but_not_encoding(embed_calls, monkeypatch):
    runner = pipeline()
    runner.run(make_request())
    encoded = []
    original = session.ENCODERS["token_set"].fit_transform
    monkeypatch.setattr(session.ENCODERS["token_set"], "fit_transform", lambda self, *a: encoded.append(1) or original(self, *a))
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


def test_cancelled_returns_none():
    assert pipeline().run(make_request(), cancelled=lambda: True) is None


def test_feature_spec_roundtrip_and_validation():
    spec = FeatureSpec("tags", "token_set", 1.5, {"separator": "space"})
    assert FeatureSpec.from_dict(spec.to_dict()) == spec
    assert FeatureSpec.from_dict({"key": "x", "encoder": "nope"}) is None
    assert FeatureSpec.from_dict({"key": "x", "encoder": "image_color"}) is None
    assert FeatureSpec.from_dict({"key": None, "encoder": "text"}) is None
    assert FeatureSpec.from_dict({"encoder": "text"}) is None


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
    original = ENCODERS["token_set"].fit_transform
    monkeypatch.setattr(ENCODERS["token_set"], "fit_transform", lambda self, inputs, params: calls.append(1) or original(self, inputs, params))
    assert pipeline().run(make_request(), cancelled=lambda: True) is None
    assert calls == []


def test_cancel_between_features_skips_remaining_encodes(monkeypatch):
    calls = []
    original = ENCODERS["token_set"].fit_transform
    monkeypatch.setattr(ENCODERS["token_set"], "fit_transform", lambda self, inputs, params: calls.append(1) or original(self, inputs, params))
    features = [FeatureSpec("tags", "token_set"), FeatureSpec("tags", "token_set", options={"separator": "comma"})]
    assert pipeline().run(make_request(features=features), cancelled=lambda: len(calls) >= 1) is None
    assert calls == [1]


def space_values(count=12, version="2"):
    values = {}
    for i in range(count):
        x = 0.0 if i < count // 2 else 10.0
        values[f"c:/{i}.png"] = {
            "tags": PathValue("cat" if i < count // 2 else "dog"),
            "mapping.x": PathValue(str(x + i * 0.01), x + i * 0.01),
            "mapping.y": PathValue("0", 0.0),
            "mapping.gx": PathValue(str(x), x),
            "mapping.gy": PathValue("0", 0.0),
            "mapping.model": PathValue(version, float(version)),
        }
    return values


def space_preset(version=2):
    return Preset([FeatureSpec("tags", "token_set")], MapParams(), version)


def test_layout_from_space_uses_current_version_only():
    values = space_values()
    values["c:/0.png"]["mapping.model"] = PathValue("1", 1.0)
    values["c:/archive.zip::m.png"] = {"tags": PathValue("cat")}
    paths = list(values)
    result = layout_from_space(paths, values, space_preset(), MapParams(min_cluster_size=3))
    assert result.unset[paths.index("c:/0.png")] and result.unset[paths.index("c:/archive.zip::m.png")]
    assert np.isfinite(result.positions[~result.unset]).all()
    assert result.diagnostics.unset == 2
    assert result.labels is not None and len(set(result.labels[~result.unset].tolist()) - {-1}) == 2
    assert any("cat" in words for words in result.group_terms.values())
    assert sorted(result.order.tolist()) == list(range(len(paths)))
    assert set(result.order[-2:].tolist()) == {paths.index("c:/0.png"), paths.index("c:/archive.zip::m.png")}


def test_layout_from_space_without_placed_files_raises():
    with pytest.raises(MapError):
        layout_from_space(["a", "b"], {"a": {}, "b": {}}, space_preset(), MapParams())


def test_layout_from_space_ignores_other_versions_and_missing_numbers():
    values = space_values(count=6)
    values["c:/0.png"]["mapping.model"] = PathValue("3", 3.0)
    values["c:/1.png"]["mapping.x"] = PathValue("n/a")
    result = layout_from_space(list(values), values, space_preset(), MapParams())
    assert result.unset.tolist() == [True, True, False, False, False, False]


def test_layout_from_space_with_one_placed_file_still_lays_out():
    values = {"a": space_values(count=1)["c:/0.png"], "b": {}}
    result = layout_from_space(["a", "b"], values, space_preset(), MapParams())
    assert result.unset.tolist() == [False, True]
    assert result.labels is None and result.order.tolist() == [0, 1]


def test_describe_space_groups_uses_fit_describe_and_matches_fit_transform(monkeypatch):
    values = space_values()
    for i, path in enumerate(values):
        values[path]["color.palette.1"] = PathValue("", float(0xFF0000 if i % 2 else 0x0000FF))
    preset = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("color.palette", "palette")], MapParams(), 2)
    paths = list(values)
    labels = np.array([0] * 6 + [1] * 6, dtype=np.int32)
    calls = []
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_transform", lambda self, inputs, params, original=cls.fit_transform: calls.append(self.NAME) or original(self, inputs, params))
    fast = session.describe_space_groups(paths, values, preset, labels, MapParams())
    assert calls == ["token_set"]
    calls.clear()
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_describe", lambda self, inputs, params: self.fit_transform(inputs, params))
    assert session.describe_space_groups(paths, values, preset, labels, MapParams()) == fast
    assert sorted(calls) == ["palette", "token_set"]
    assert "cat" in fast[0] and "dog" in fast[1]


def test_spacing_changes_the_layout_but_not_the_groups(monkeypatch):
    calls = []

    def spacing_embed(matrix, n_components, n_neighbors, min_dist, seed):
        calls.append(min_dist)
        return jittered_copy(matrix, n_components) + min_dist * 100

    monkeypatch.setattr(projection, "embed", spacing_embed)
    runner = pipeline()
    first = runner.run(make_request(params=MapParams(min_dist=0.1)))
    assert calls == [0.1, projection.GROUPING_MIN_DIST]
    second = runner.run(make_request(params=MapParams(min_dist=0.5)))
    assert calls == [0.1, projection.GROUPING_MIN_DIST, 0.5]
    assert np.array_equal(first.labels, second.labels)
    runner.run(make_request(params=MapParams(min_dist=0.5, n_neighbors=5)))
    assert calls[-2:] == [0.5, projection.GROUPING_MIN_DIST]


def test_layout_from_space_groups_by_the_grouping_coordinates():
    values = space_values()
    order = np.random.default_rng(3).permutation(len(values))
    for rank, entry in zip(order, values.values()):
        entry["mapping.x"] = PathValue(str(rank), float(rank))
    paths = list(values)
    result = layout_from_space(paths, values, space_preset(), MapParams(min_cluster_size=3))
    half = len(paths) // 2
    assert len(set(result.labels[:half].tolist())) == 1 and len(set(result.labels[half:].tolist())) == 1
    assert result.labels[0] != result.labels[-1]


def test_layouts_use_the_resolved_neighbor_count(monkeypatch):
    seen = []

    def record(matrix, n_components, n_neighbors, min_dist, seed):
        seen.append(n_neighbors)
        return jittered_copy(matrix, n_components)

    monkeypatch.setattr(projection, "embed", record)
    pipeline().run(make_request())
    assert seen == [MapParams().resolved_neighbors(40)] * 2
    seen.clear()
    pipeline().run(make_request(params=MapParams(n_neighbors=7)))
    assert seen == [7, 7]

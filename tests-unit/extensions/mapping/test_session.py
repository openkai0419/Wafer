import numpy as np
import pytest

from extensions.mapping import projection, session
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec, MapError, MapPipeline, MapRequest, SpaceLayout, grouping_text
from extensions.mapping.space import Preset
from wafer.core.db.path_values import PathValue


@pytest.fixture()
def embed_calls(monkeypatch):
    calls = []

    def fake_embed(matrix, neighbors, min_dist, seed, dims=2):
        calls.append(min_dist)
        return jittered_copy(matrix, dims)

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
            "mapping.group": PathValue(grouping_text([x] + [0.0] * (projection.GROUPING_DIMS - 1))),
            "mapping.model": PathValue(version, float(version)),
        }
    return values


def space_preset(version=2):
    return Preset([FeatureSpec("tags", "token_set")], MapParams(), version)


def test_space_layout_uses_current_version_only():
    values = space_values()
    values["c:/0.png"]["mapping.model"] = PathValue("1", 1.0)
    values["c:/archive.zip::m.png"] = {"tags": PathValue("cat")}
    paths = list(values)
    result = SpaceLayout(paths, values, space_preset()).run(MapParams())
    assert result.unset[paths.index("c:/0.png")] and result.unset[paths.index("c:/archive.zip::m.png")]
    assert np.isfinite(result.positions[~result.unset]).all()
    assert result.diagnostics.unset == 2
    assert result.labels is not None and len(set(result.labels[~result.unset].tolist()) - {-1}) == 2
    assert any("cat" in words for words in result.group_terms.values())
    assert sorted(result.order.tolist()) == list(range(len(paths)))
    assert set(result.order[-2:].tolist()) == {paths.index("c:/0.png"), paths.index("c:/archive.zip::m.png")}


def test_space_layout_without_placed_files_raises():
    with pytest.raises(MapError):
        SpaceLayout(["a", "b"], {"a": {}, "b": {}}, space_preset()).run(MapParams())


def test_space_layout_ignores_other_versions_and_missing_numbers():
    values = space_values(count=6)
    values["c:/0.png"]["mapping.model"] = PathValue("3", 3.0)
    values["c:/1.png"]["mapping.x"] = PathValue("n/a")
    result = SpaceLayout(list(values), values, space_preset()).run(MapParams())
    assert result.unset.tolist() == [True, True, False, False, False, False]


def test_space_layout_with_one_placed_file_still_lays_out():
    values = {"a": space_values(count=1)["c:/0.png"], "b": {}}
    result = SpaceLayout(["a", "b"], values, space_preset()).run(MapParams())
    assert result.unset.tolist() == [False, True]
    assert result.labels is None and result.order.tolist() == [0, 1]


def test_space_describers_use_fit_describe_and_matches_fit_transform(monkeypatch):
    values = space_values()
    for i, path in enumerate(values):
        values[path]["color.palette.1"] = PathValue("", float(0xFF0000 if i % 2 else 0x0000FF))
    preset = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("color.palette", "palette")], MapParams(), 2)
    paths = list(values)
    labels = np.array([0] * 6 + [1] * 6, dtype=np.int32)
    calls = []
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_transform", lambda self, inputs, params, original=cls.fit_transform: calls.append(self.NAME) or original(self, inputs, params))
    rows = np.arange(len(paths))
    fast = session.describe_groups(SpaceLayout(paths, values, preset).space_describers(rows, MapParams()), labels, MapParams())
    assert calls == ["token_set"]
    calls.clear()
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_describe", lambda self, inputs, params: self.fit_transform(inputs, params))
    assert session.describe_groups(SpaceLayout(paths, values, preset).space_describers(rows, MapParams()), labels, MapParams()) == fast
    assert sorted(calls) == ["palette", "token_set"]
    assert "cat" in fast[0] and "dog" in fast[1]


def test_spacing_changes_the_layout_but_not_the_groups(monkeypatch):
    calls = []

    def spacing_embed(matrix, neighbors, min_dist, seed, dims=2):
        calls.append(min_dist)
        return jittered_copy(matrix, dims) + min_dist * 100

    monkeypatch.setattr(projection, "embed", spacing_embed)
    runner = pipeline()
    first = runner.run(make_request(params=MapParams(min_dist=0.1)))
    assert calls == [0.1, projection.GROUPING_MIN_DIST]
    second = runner.run(make_request(params=MapParams(min_dist=0.5)))
    assert calls == [0.1, projection.GROUPING_MIN_DIST, 0.5]
    assert np.array_equal(first.labels, second.labels)
    runner.run(make_request(params=MapParams(min_dist=0.5, neighbors=0.5)))
    assert calls[-2:] == [0.5, projection.GROUPING_MIN_DIST]


def test_space_layout_groups_by_the_grouping_coordinates():
    values = space_values()
    order = np.random.default_rng(3).permutation(len(values))
    for rank, entry in zip(order, values.values()):
        entry["mapping.x"] = PathValue(str(rank), float(rank))
    paths = list(values)
    result = SpaceLayout(paths, values, space_preset()).run(MapParams())
    half = len(paths) // 2
    assert len(set(result.labels[:half].tolist())) == 1 and len(set(result.labels[half:].tolist())) == 1
    assert result.labels[0] != result.labels[-1]


def test_both_layouts_share_one_neighbor_search_of_the_resolved_size(monkeypatch):
    searched, used = [], []
    real_search = projection.nearest_neighbors

    def search(matrix, n_neighbors, seed):
        searched.append(n_neighbors)
        return real_search(matrix, n_neighbors, seed)

    def record(matrix, neighbors, min_dist, seed, dims=2):
        used.append(neighbors)
        return jittered_copy(matrix, dims)

    monkeypatch.setattr(projection, "nearest_neighbors", search)
    monkeypatch.setattr(projection, "embed", record)
    runner = pipeline()
    runner.run(make_request())
    assert searched == [MapParams().resolved_neighbors(40)]
    assert len(used) == 2 and used[0] is used[1]
    runner.run(make_request(params=MapParams(min_dist=0.5)))
    assert len(searched) == 1 and len(used) == 3
    runner.run(make_request(params=MapParams(neighbors=0.5)))
    assert searched[-1] == 8 and len(used) == 5


def test_space_layout_groups_once_and_relabels_on_view_changes(monkeypatch):
    clusters, fits = [], []
    real_cluster = projection.cluster
    monkeypatch.setattr(projection, "cluster", lambda *args: clusters.append(args[1:]) or real_cluster(*args))
    real_fit = ENCODERS["token_set"].fit_describe
    monkeypatch.setattr(ENCODERS["token_set"], "fit_describe", lambda self, inputs, params: fits.append(1) or real_fit(self, inputs, params))
    values = space_values()
    layout = SpaceLayout(list(values), values, space_preset())
    first = layout.run(MapParams())
    second = layout.run(MapParams(outlier_percent=10.0, label_terms=1))
    assert len(clusters) == 1 and len(fits) == 1
    assert second.labels.tolist() == first.labels.tolist()
    assert all(len(words) <= 1 for words in second.group_terms.values())
    assert not np.array_equal(second.positions, first.positions)


def test_detail_change_reduces_again_without_encoding_again(embed_calls, monkeypatch):
    encodes = []
    real = ENCODERS["token_set"].fit_transform
    monkeypatch.setattr(ENCODERS["token_set"], "fit_transform", lambda self, inputs, params: encodes.append(1) or real(self, inputs, params))
    runner = pipeline()
    runner.run(make_request())
    layouts = len(embed_calls)
    runner.run(make_request(features=[FeatureSpec("tags", "token_set", options={"summary": "3"})]))
    assert len(encodes) == 1 and len(embed_calls) > layouts


def test_quick_train_learns_from_the_training_limit_and_places_the_rest(monkeypatch):
    searched, embedded = [], []
    real_search = projection.nearest_neighbors

    def search(matrix, n_neighbors, seed):
        searched.append((matrix.shape[0], n_neighbors))
        return real_search(matrix, n_neighbors, seed)

    def record(matrix, neighbors, min_dist, seed, dims=2):
        embedded.append(matrix.shape[0])
        return jittered_copy(matrix, dims)

    monkeypatch.setattr(projection, "nearest_neighbors", search)
    monkeypatch.setattr(projection, "embed", record)
    runner = pipeline()
    result = runner.run(make_request(count=200, params=MapParams(train_limit=50)))
    assert embedded == [50, 50] and searched == [(50, MapParams().resolved_neighbors(50))]
    assert np.isfinite(result.positions).all()
    cats, dogs = result.positions[:100], result.positions[100:]
    assert np.linalg.norm(cats.mean(axis=0) - dogs.mean(axis=0)) > max(cats.std(), dogs.std())
    runner.run(make_request(count=200, params=MapParams(train_limit=50, outlier_percent=5.0)))
    assert len(embedded) == 2
    runner.run(make_request(count=200, params=MapParams(train_limit=0)))
    assert embedded[-2:] == [200, 200]


def test_quick_train_groups_on_the_ten_dimensional_layout(monkeypatch):
    calls = []

    def record(matrix, neighbors, min_dist, seed, dims=2):
        calls.append((dims, min_dist))
        return jittered_copy(matrix, dims)

    monkeypatch.setattr(projection, "embed", record)
    clustered = []
    real_cluster = projection.cluster
    monkeypatch.setattr(projection, "cluster", lambda space, *args: clustered.append(space.shape[1]) or real_cluster(space, *args))
    pipeline().run(make_request(params=MapParams(min_dist=0.3)))
    assert calls == [(2, 0.3), (projection.GROUPING_DIMS, projection.GROUPING_MIN_DIST)]
    assert clustered == [projection.GROUPING_DIMS]


def test_space_layout_can_show_the_map_before_grouping(monkeypatch):
    clustered = []
    real_cluster = projection.cluster
    monkeypatch.setattr(projection, "cluster", lambda *args: clustered.append(1) or real_cluster(*args))
    values = space_values()
    layout = SpaceLayout(list(values), values, space_preset())
    plain = layout.run(MapParams(), grouped=False)
    assert plain.labels is None and plain.group_terms == {} and clustered == []
    assert np.isfinite(plain.positions).all() and sorted(plain.order.tolist()) == list(range(len(values)))
    grouped = layout.run(MapParams())
    assert grouped.labels is not None and clustered == [1]
    assert np.array_equal(plain.positions, grouped.positions)


def test_grouping_text_roundtrip_and_bad_values():
    from extensions.mapping.session import grouping_values

    numbers = np.linspace(-3.5, 7.25, projection.GROUPING_DIMS)
    assert np.allclose(grouping_values(grouping_text(numbers)), numbers, rtol=1e-5)
    assert grouping_values("1,2") is None and grouping_values("") is None
    assert grouping_values(",".join(["x"] * projection.GROUPING_DIMS)) is None


def test_group_size_regroups_the_shown_files_without_moving_them(monkeypatch):
    seen = []
    real_cluster = projection.cluster
    monkeypatch.setattr(projection, "cluster", lambda space, size, samples: seen.append((size, samples)) or real_cluster(space, size, samples))
    values = space_values(40)
    layout = SpaceLayout(list(values), values, space_preset())
    first = layout.run(MapParams())
    finer = layout.run(MapParams(group_size=0.5))
    again = layout.run(MapParams())
    assert seen == [MapParams().group_sizes(40), MapParams(group_size=0.5).group_sizes(40)]
    assert np.array_equal(first.positions, finer.positions) and np.array_equal(first.labels, again.labels)
    assert layout.is_grouped()


def test_quick_train_uses_the_group_size(monkeypatch, embed_calls):
    seen = []
    real_cluster = projection.cluster
    monkeypatch.setattr(projection, "cluster", lambda space, size, samples: seen.append(size) or real_cluster(space, size, samples))
    runner = pipeline()
    runner.run(make_request(params=MapParams(group_size=2.0)))
    layouts = len(embed_calls)
    runner.run(make_request(params=MapParams(group_size=0.5)))
    assert seen == [MapParams(group_size=2.0).group_sizes(40)[0], MapParams(group_size=0.5).group_sizes(40)[0]]
    assert len(embed_calls) == layouts

import numpy as np
import pytest

from extensions.mapping import projection, session
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import Grouping, TrainParams, ViewParams
from extensions.mapping.session import FeatureSpec, MapError, SpaceLayout, grouping_text
from extensions.mapping.space import Preset
from wafer.core.db.path_values import PathValue


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
    return Preset([FeatureSpec("tags", "token_set")], TrainParams(), version)


def test_space_layout_uses_current_version_only():
    values = space_values()
    values["c:/0.png"]["mapping.model"] = PathValue("1", 1.0)
    values["c:/archive.zip::m.png"] = {"tags": PathValue("cat")}
    paths = list(values)
    result = SpaceLayout(paths, values, space_preset()).run(ViewParams())
    assert result.unset[paths.index("c:/0.png")] and result.unset[paths.index("c:/archive.zip::m.png")]
    assert np.isfinite(result.positions[~result.unset]).all()
    assert result.diagnostics.unset == 2
    assert result.labels is not None and len(set(result.labels[~result.unset].tolist()) - {-1}) == 2
    assert any("cat" in words for words in result.group_terms.values())
    assert sorted(result.order.tolist()) == list(range(len(paths)))
    assert set(result.order[-2:].tolist()) == {paths.index("c:/0.png"), paths.index("c:/archive.zip::m.png")}


def test_space_layout_without_placed_files_raises():
    with pytest.raises(MapError):
        SpaceLayout(["a", "b"], {"a": {}, "b": {}}, space_preset()).run(ViewParams())


def test_space_layout_ignores_other_versions_and_missing_numbers():
    values = space_values(count=6)
    values["c:/0.png"]["mapping.model"] = PathValue("3", 3.0)
    values["c:/1.png"]["mapping.x"] = PathValue("n/a")
    result = SpaceLayout(list(values), values, space_preset()).run(ViewParams())
    assert result.unset.tolist() == [True, True, False, False, False, False]


def test_space_layout_with_one_placed_file_still_lays_out():
    values = {"a": space_values(count=1)["c:/0.png"], "b": {}}
    result = SpaceLayout(["a", "b"], values, space_preset()).run(ViewParams())
    assert result.unset.tolist() == [False, True]
    assert result.labels is None and result.order.tolist() == [0, 1]


def test_space_describers_use_fit_describe_and_matches_fit_transform(monkeypatch):
    values = space_values()
    for i, path in enumerate(values):
        values[path]["color.palette.1"] = PathValue("", float(0xFF0000 if i % 2 else 0x0000FF))
    preset = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("color.palette", "palette")], TrainParams(), 2)
    paths = list(values)
    labels = np.array([0] * 6 + [1] * 6, dtype=np.int32)
    calls = []
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_transform", lambda self, inputs, original=cls.fit_transform: calls.append(self.NAME) or original(self, inputs))
    rows = np.arange(len(paths))
    fast = session.describe_groups(SpaceLayout(paths, values, preset).space_describers(rows), labels, 3)
    assert calls == ["token_set"]
    calls.clear()
    for cls in ENCODERS.values():
        monkeypatch.setattr(cls, "fit_describe", lambda self, inputs: self.fit_transform(inputs))
    assert session.describe_groups(SpaceLayout(paths, values, preset).space_describers(rows), labels, 3) == fast
    assert sorted(calls) == ["palette", "token_set"]
    assert "cat" in fast[0] and "dog" in fast[1]


def test_space_layout_groups_by_the_grouping_coordinates():
    values = space_values()
    order = np.random.default_rng(3).permutation(len(values))
    for rank, entry in zip(order, values.values()):
        entry["mapping.x"] = PathValue(str(rank), float(rank))
    paths = list(values)
    result = SpaceLayout(paths, values, space_preset()).run(ViewParams())
    half = len(paths) // 2
    assert len(set(result.labels[:half].tolist())) == 1 and len(set(result.labels[half:].tolist())) == 1
    assert result.labels[0] != result.labels[-1]


def test_space_layout_groups_once_and_relabels_on_view_changes(monkeypatch):
    fits = []
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    real_fit = ENCODERS["token_set"].fit_describe
    monkeypatch.setattr(ENCODERS["token_set"], "fit_describe", lambda self, inputs: fits.append(1) or real_fit(self, inputs))
    values = space_values()
    layout = SpaceLayout(list(values), values, space_preset())
    first = layout.run(ViewParams())
    second = layout.run(ViewParams(outlier_percent=10.0, label_terms=1))
    assert len(FakeTree.built) == 1 and len(fits) == 1
    assert second.labels.tolist() == first.labels.tolist()
    assert all(len(words) <= 1 for words in second.group_terms.values())
    assert not np.array_equal(second.positions, first.positions)


def test_space_layout_can_show_the_map_before_grouping(monkeypatch):
    clustered = []
    monkeypatch.setattr(projection, "ClusterTree", lambda space, samples: clustered.append(1) or FakeTree(space, samples))
    values = space_values()
    layout = SpaceLayout(list(values), values, space_preset())
    plain = layout.run(ViewParams(), grouped=False)
    assert plain.labels is None and plain.group_terms == {} and clustered == []
    assert np.isfinite(plain.positions).all() and sorted(plain.order.tolist()) == list(range(len(values)))
    grouped = layout.run(ViewParams())
    assert grouped.labels is not None and clustered == [1]
    assert np.array_equal(plain.positions, grouped.positions)


def test_grouping_text_roundtrip_and_bad_values():
    from extensions.mapping.session import grouping_values

    numbers = np.linspace(-3.5, 7.25, projection.GROUPING_DIMS)
    assert np.allclose(grouping_values(grouping_text(numbers)), numbers, rtol=1e-5)
    assert grouping_values("1,2") is None and grouping_values("") is None
    assert grouping_values(",".join(["x"] * projection.GROUPING_DIMS)) is None


def test_group_size_regroups_the_shown_files_without_moving_them(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    values = space_values(40)
    layout = SpaceLayout(list(values), values, space_preset())
    first = layout.run(ViewParams())
    finer = layout.run(ViewParams(), share=0.5)
    again = layout.run(ViewParams())
    assert np.array_equal(first.positions, finer.positions) and np.array_equal(first.labels, again.labels)
    layout.run(ViewParams(), grouping=Grouping(strictness=2.0))
    layout.run(ViewParams(), grouping=Grouping(fine=1))
    samples = [samples for _count, samples in FakeTree.built]
    default, strict = Grouping().cluster_options(40)[1], Grouping(strictness=2.0).cluster_options(40)[1]
    smaller = Grouping().cluster_options(40, 0.5)[1]
    assert samples == [default, smaller, strict, default]
    assert ("leaf" in [method for _size, method in FakeTree.cuts]) and layout.is_grouped()


class FakeTree:
    built = []
    cuts = []

    def __init__(self, space, min_samples):
        FakeTree.built.append((len(space), min_samples))
        self.space = space

    def labels(self, min_cluster_size, method="eom"):
        FakeTree.cuts.append((min_cluster_size, method))
        return (self.space[:, 0] > self.space[:, 0].mean()).astype(np.int32) * 7


def whole_space(count=60):
    from extensions.mapping.session import SpaceGroups

    points = np.zeros((count, projection.GROUPING_DIMS))
    points[:, 0] = np.r_[np.zeros(count // 2), np.full(count - count // 2, 10.0)]
    return SpaceGroups([f"c:/{i}.png" for i in range(count)], points)


def test_selections_take_their_groups_from_the_whole_space(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    groups = whole_space()
    values = space_values(12)
    first = SpaceLayout(list(values)[:6], values, space_preset(), groups).run(ViewParams())
    both = SpaceLayout(list(values), values, space_preset(), groups).run(ViewParams())
    assert first.labels.tolist() == [0] * 6
    assert both.labels.tolist() == [0] * 12
    assert FakeTree.built == [(60, Grouping().cluster_options(60)[1])]
    assert first.diagnostics.groups == 1


def test_whole_space_labels_are_cut_per_size_and_rebuilt_per_strictness(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    groups = whole_space(12_000)
    paths = ["c:/0.png", "c:/11999.png", "c:/missing.png"]
    assert groups.labels_for(paths, Grouping()).tolist() == [0, 7, -1]
    groups.labels_for(paths, Grouping(size=0.5))
    groups.labels_for(paths, Grouping(fine=1))
    groups.labels_for(paths, Grouping(), share=0.5)
    assert len(FakeTree.built) == 1
    groups.labels_for(paths, Grouping(), share=0.25)
    assert [samples for _count, samples in FakeTree.built] == [10, 6]
    groups.labels_for(paths, Grouping(strictness=2.0))
    assert len(FakeTree.built) == 3


def test_smaller_groups_stay_inside_their_base_group():
    from extensions.mapping.session import nested_labels

    base = np.array([0, 0, 0, 1, 1, 1, -1])
    finer = np.array([4, 4, 5, 4, 6, -1, 4])
    nested = nested_labels(base, finer)
    assert nested[6] == -1
    assert nested[0] == nested[1] != nested[2] and nested[3] not in (nested[0], nested[2], nested[4])
    assert nested[5] >= 0 and nested[5] not in (nested[3], nested[4], nested[0], nested[2])
    assert len(set(nested.tolist()) - {-1}) == 5


def test_selection_without_a_whole_space_groups_by_itself(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    values = space_values(40)
    SpaceLayout(list(values), values, space_preset()).run(ViewParams())
    assert FakeTree.built == [(40, Grouping().cluster_options(40)[1])]


def test_whole_space_groups_are_loaded_only_when_grouping(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    loads = []
    groups = whole_space()
    values = space_values(12)
    layout = SpaceLayout(list(values), values, space_preset(), load_groups=lambda: loads.append(1) or groups)
    layout.run(ViewParams(), grouped=False)
    assert loads == []
    layout.run(ViewParams())
    layout.run(ViewParams(), share=0.5)
    assert loads == [1] and layout.groups is groups

import numpy as np
import pytest

from extensions.mapping import projection, session
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import Grouping, TrainParams, ViewParams
from extensions.mapping.session import FeatureSpec, MapError, SpaceLayout, WholeSpace, coordinate_text, coordinate_values
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
            "mapping.2d": PathValue(coordinate_text([x + i * 0.01, 0.0])),
            "mapping.group": PathValue(coordinate_text([x] + [0.0] * (projection.GROUPING_DIMS - 1))),
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
    values["c:/1.png"]["mapping.2d"] = PathValue("n/a")
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
        entry["mapping.2d"] = PathValue(coordinate_text([float(rank), 0.0]))
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


def test_coordinate_text_roundtrip_and_bad_values():
    numbers = np.linspace(-3.5, 7.25, projection.GROUPING_DIMS)
    assert np.allclose(coordinate_values(coordinate_text(numbers), projection.GROUPING_DIMS), numbers, rtol=1e-5)
    assert coordinate_values("1,2", projection.GROUPING_DIMS) is None and coordinate_values("", 2) is None
    assert coordinate_values(",".join(["x"] * projection.GROUPING_DIMS), projection.GROUPING_DIMS) is None
    assert np.allclose(coordinate_values("1.5,-2", 2), [1.5, -2.0]) and coordinate_values("1,inf", 2) is None


def test_space_layout_reads_the_2d_key():
    values = {"a": {"mapping.2d": PathValue("1.5,-2"), "mapping.group": PathValue(coordinate_text([0.0] * projection.GROUPING_DIMS)), "mapping.model": PathValue("2", 2.0)}}
    assert np.allclose(SpaceLayout(["a"], values, space_preset()).space_coords()[0, :2], [1.5, -2.0])


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
    coords = np.zeros((count, 2 + projection.GROUPING_DIMS))
    coords[:, 0] = np.arange(count, dtype=np.float64)
    coords[:, 2] = np.r_[np.zeros(count // 2), np.full(count - count // 2, 10.0)]
    return WholeSpace([f"c:/{i}.png" for i in range(count)], coords)


def point(x):
    return np.array([[x] + [0.0] * (projection.GROUPING_DIMS - 1)])


class FakeModel:
    def __init__(self, space):
        self.space = space
        self.calls = []
        self.placed = 0
        self.stages = []

    def whole_space(self):
        return self.space

    def place(self, entries):
        output = np.full((len(entries), 2 + projection.GROUPING_DIMS), np.nan, dtype=np.float32)
        for row, entry in enumerate(entries):
            if "tags" in entry:
                output[row] = 0.0
                output[row, 0] = 100.0 + row
                self.placed += 1
        return output

    def relayout(self, entries, start, cancelled=lambda: False, progress=lambda stage: None):
        progress("encode")
        progress("layout")
        self.calls.append(len(entries))
        local = np.array(start, dtype=np.float32)
        local[:, 0] = -local[:, 0]
        local[:, 2] = np.where(np.arange(len(start)) % 2, 5.0, -5.0)
        return local


def test_selections_take_their_groups_from_the_whole_space(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    model = FakeModel(whole_space())
    values = space_values(12)
    first = SpaceLayout(list(values)[:6], values, space_preset(), model).run(ViewParams())
    both = SpaceLayout(list(values), values, space_preset(), model).run(ViewParams())
    assert first.labels.tolist() == [0] * 6
    assert both.labels.tolist() == [0] * 12
    assert FakeTree.built == [(60, Grouping().cluster_options(60)[1])]
    assert first.diagnostics.groups == 1


def test_whole_space_labels_are_cut_per_size_and_rebuilt_per_strictness(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    groups = whole_space(12_000)
    paths = ["c:/0.png", "c:/11999.png", "c:/missing.png"]
    points = np.vstack([point(0.0), point(10.0), point(9.5)])
    assert groups.labels_for(paths, points, Grouping()).tolist() == [0, 7, 7]
    groups.labels_for(paths, points, Grouping(size=0.5))
    groups.labels_for(paths, points, Grouping(fine=1))
    groups.labels_for(paths, points, Grouping(), share=0.5)
    assert len(FakeTree.built) == 1
    groups.labels_for(paths, points, Grouping(), share=0.25)
    assert [samples for _count, samples in FakeTree.built] == [10, 6]
    groups.labels_for(paths, points, Grouping(strictness=2.0))
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


def test_selection_without_a_model_groups_by_itself(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    values = space_values(40)
    layout = SpaceLayout(list(values), values, space_preset())
    layout.run(ViewParams())
    assert FakeTree.built == [(40, Grouping().cluster_options(40)[1])]
    assert not layout.refine()


def test_model_is_loaded_only_when_grouping_or_coordinates_are_missing(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    loads = []
    model = FakeModel(whole_space())
    values = space_values(12)
    layout = SpaceLayout(list(values), values, space_preset(), load_model=lambda: loads.append(1) or model)
    layout.run(ViewParams(), grouped=False)
    assert loads == []
    layout.run(ViewParams())
    layout.run(ViewParams(), share=0.5)
    assert loads == [1] and layout.model is model


def test_files_not_yet_written_take_their_coordinates_from_the_model():
    model = FakeModel(whole_space())
    values = {path: {"tags": PathValue("cat")} for path in model.space.paths[:5]}
    values["c:/3.png"] = space_values(1)["c:/0.png"]
    values["c:/empty.png"] = {}
    layout = SpaceLayout(list(values), values, space_preset(), load_model=lambda: model)
    result = layout.run(ViewParams(), grouped=False)
    assert result.unset.tolist() == [False] * 5 + [True]
    raw = layout.space_coords()
    assert raw[3, 0] == 10.0 and model.space.coords[3, 0] == 3.0
    assert np.array_equal(raw[[0, 1, 2, 4]], model.space.coords[[0, 1, 2, 4]])


def test_new_files_are_placed_from_the_model_and_laid_out_with_the_rest():
    layout = refining_layout(count=40, space_count=60, new_files=2)
    plain = layout.run(ViewParams(), grouped=False)
    assert not plain.unset.any() and layout.model.placed == 2
    assert layout.refine() and layout.model.calls == [42]


def test_files_placed_after_training_join_the_group_of_their_nearest_file(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    model = FakeModel(whole_space())
    values = {"c:/0.png": {}, "c:/59.png": {}, "c:/late.png": space_values(12)["c:/11.png"]}
    result = SpaceLayout(list(values), values, space_preset(), model).run(ViewParams())
    assert result.labels.tolist()[2] == result.labels.tolist()[1] != result.labels.tolist()[0]


def refining_layout(count=40, space_count=60, new_files=0):
    model = FakeModel(whole_space(space_count))
    values = {path: {"tags": PathValue("cat")} for path in model.space.paths[:count]}
    values.update({f"c:/new/{i}.png": {"tags": PathValue("cat")} for i in range(new_files)})
    return SpaceLayout(list(values), values, space_preset(), model)


def test_each_map_is_laid_out_again_on_its_own():
    layout = refining_layout()
    before = layout.run(ViewParams(), grouped=False)
    stages = []
    assert layout.refine(progress=stages.append) and layout.model.calls == [40] and layout.is_local()
    assert stages == ["encode", "layout"]
    after = layout.run(ViewParams(), grouped=False)
    assert np.allclose(after.positions[:, 0], 1.0 - before.positions[:, 0], atol=1e-6)
    assert not layout.refine() and layout.model.calls == [40]


@pytest.mark.parametrize("count, space_count", [(10, 60), (60, 60), (6000, 6000)])
def test_every_selection_is_laid_out_again_whatever_its_size(count, space_count):
    layout = refining_layout(count, space_count)
    assert layout.refine() and layout.model.calls == [count]


def test_two_files_are_shown_without_grouping():
    layout = refining_layout(count=2)
    assert not layout.refine() and layout.model.calls == []
    assert layout.run(ViewParams()).labels is None


def test_local_groups_split_the_whole_space_groups_by_the_same_size(monkeypatch):
    monkeypatch.setattr(projection, "ClusterTree", FakeTree)
    FakeTree.built, FakeTree.cuts = [], []
    layout = refining_layout()
    base = layout.run(ViewParams()).labels
    layout.refine()
    same = layout.run(ViewParams()).labels
    assert same.tolist() == base.tolist()
    finer = layout.run(ViewParams(), share=0.5).labels
    assert len(set(finer.tolist())) > len(set(base.tolist()))
    for group in set(finer.tolist()):
        assert len(set(base[finer == group].tolist())) == 1
    local_tree = FakeTree.built[-1]
    assert local_tree == (40, Grouping().cluster_options(60, 0.5)[1])
    assert FakeTree.cuts[-1] == (Grouping().cluster_options(60, 0.5)[0], "eom")

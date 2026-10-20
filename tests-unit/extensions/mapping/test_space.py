import numpy as np
import pytest

from extensions.mapping import projection, space
from extensions.mapping.encoders import ENCODERS
from extensions.mapping.params import TrainParams, ViewParams
from extensions.mapping.session import FeatureSpec, MapError, SpaceLayout
from extensions.mapping.space import Preset, SpaceLoadError, SpaceModel, SpaceStatus, load_preset, read_status, save_preset, write_status
from wafer.core.db.path_values import PathValue


@pytest.fixture(autouse=True)
def fast_embed(monkeypatch):
    def fake_embed(matrix, neighbors, min_dist, seed, dims=2, **_):
        out = np.zeros((matrix.shape[0], dims), dtype=np.float32)
        width = min(dims, matrix.shape[1])
        out[:, :width] = matrix[:, :width]
        return out

    monkeypatch.setattr(projection, "embed", fake_embed)


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    import wafer.core.common.paths as paths

    monkeypatch.setattr(paths, "setting_db_path", lambda name: str(tmp_path / f"{name}.settings.db"))
    monkeypatch.setattr(space, "setting_db_path", lambda name: str(tmp_path / f"{name}.settings.db"))
    return tmp_path


def tag_values(count=40):
    return {f"c:/{i}.png": {"tags": PathValue("cat, sky" if i < count // 2 else "dog, sea")} for i in range(count)}


def preset(version=1):
    return Preset([FeatureSpec("tags", "token_set"), FeatureSpec("color.palette", "palette")], TrainParams(), version)


def test_preset_roundtrip_and_keys(settings):
    save_preset("db1", preset(3))
    loaded = load_preset("db1")
    assert loaded.version == 3 and [f.key for f in loaded.features] == ["tags", "color.palette"]
    assert loaded.trigger_keys()[:2] == ("file_hash", "tags")
    assert "color.palette.1" in loaded.value_keys() and "color.palette.30" in loaded.value_keys()
    assert load_preset("missing") is None
    assert Preset.from_dict({"features": "bad"}) is None


def test_unreadable_preset_version_reads_as_zero_and_is_logged(monkeypatch):
    warnings = []
    monkeypatch.setattr(space.AppLogger, "warning", lambda message, exc=None: warnings.append(message))
    assert Preset.from_dict({"features": [], "version": "x"}).version == 0
    assert len(warnings) == 1


def test_fit_places_training_files_and_new_files_near_neighbours():
    model = SpaceModel.fit(preset(), tag_values())
    assert model.trained == len(model.paths) == 40
    cat = np.array(model.coords_for("c:/0.png"))
    dog = np.array(model.coords_for("c:/39.png"))
    new = model.place([{"tags": PathValue("cat, sky")}, {}])
    assert np.linalg.norm(new[0] - cat) < np.linalg.norm(new[0] - dog)
    assert np.isnan(new[1]).all()


def test_fit_requires_three_files_with_values():
    with pytest.raises(MapError):
        SpaceModel.fit(preset(), {"a": {"tags": PathValue("x")}, "b": {}})


def test_save_load_roundtrip_and_old_versions_removed(tmp_path):
    first = SpaceModel.fit(preset(1), tag_values())
    first.save(tmp_path)
    second = SpaceModel.fit(preset(2), tag_values())
    second.save(tmp_path)
    assert not list(tmp_path.glob("model-v1.*"))
    loaded = SpaceModel.load(tmp_path, preset(2))
    assert loaded.paths == second.paths and loaded.trained == second.trained
    assert np.allclose(loaded.place([{"tags": PathValue("cat, sky")}]), second.place([{"tags": PathValue("cat, sky")}]))
    assert SpaceModel.load(tmp_path, preset(9)) is None


def test_corrupt_model_raises_load_error(tmp_path):
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)
    (tmp_path / "model-v1.pkl").write_bytes(b"not a pickle")
    with pytest.raises(SpaceLoadError):
        SpaceModel.load(tmp_path, preset(1))


def test_status_roundtrip(tmp_path):
    assert read_status(tmp_path).state == "none"
    write_status(tmp_path, SpaceStatus("ready", 2, trained=40, built_at=1.0, sources_at_training=55))
    assert read_status(tmp_path) == SpaceStatus("ready", 2, trained=40, built_at=1.0, sources_at_training=55)


def colored_values(count=40):
    values = {}
    for i in range(count):
        cat = i < count // 2
        values[f"c:/{i}.png"] = {
            "tags": PathValue("cat, sky" if cat else "dog, sea"),
            "color.palette.1": PathValue("", float(0xFF0000 if cat else 0x0000FF)),
        }
    return values


def test_place_with_only_some_features():
    model = SpaceModel.fit(preset(), colored_values())
    cat = np.array(model.coords_for("c:/0.png"))
    dog = np.array(model.coords_for("c:/39.png"))
    by_tags, by_color = model.place([{"tags": PathValue("dog, sea")}, {"color.palette.1": PathValue("", float(0xFF0000))}])
    assert np.linalg.norm(by_tags - dog) < np.linalg.norm(by_tags - cat)
    assert np.linalg.norm(by_color - cat) < np.linalg.norm(by_color - dog)


@pytest.mark.parametrize("count", [3, 5, 9])
def test_place_with_fewer_rows_than_neighbours(count):
    model = SpaceModel.fit(preset(), tag_values(count))
    placed = model.place([{"tags": PathValue("cat, sky")}])
    assert placed.shape == (1, 2 + projection.GROUPING_DIMS) and np.isfinite(placed).all()


def test_cleanup_matches_whole_version_only(tmp_path):
    values = tag_values()
    SpaceModel.fit(preset(10), values).save(tmp_path)
    SpaceModel.fit(preset(1), values).save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model-v1.npz", "model-v1.pkl"]
    SpaceModel.fit(preset(10), values).save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model-v10.npz", "model-v10.pkl"]


def test_save_leaves_no_temp_files_and_keeps_status(tmp_path):
    write_status(tmp_path, SpaceStatus("ready", 1))
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)
    assert sorted(p.name for p in tmp_path.iterdir()) == ["model-v1.npz", "model-v1.pkl", "status.json"]


def test_save_writes_the_arrays_last_so_readers_never_see_them_without_the_state(tmp_path, monkeypatch):
    replaced = []
    original = space.os.replace
    monkeypatch.setattr(space.os, "replace", lambda source, target: replaced.append(target.name) or original(source, target))
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)
    assert replaced == ["model-v1.pkl", "model-v1.npz"]


def test_save_survives_undeletable_stale_file(tmp_path, monkeypatch):
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)

    def deny(self, missing_ok=False):
        raise PermissionError("locked")

    monkeypatch.setattr(type(tmp_path), "unlink", deny)
    SpaceModel.fit(preset(2), tag_values()).save(tmp_path)
    assert SpaceModel.load(tmp_path, preset(2)) is not None


def test_npz_stores_paths_compactly(tmp_path):
    values = {f"c:/folder/{i:05d}.png": {"tags": PathValue("cat, sky" if i % 2 else "dog, sea")} for i in range(1000)}
    long_path = "c:/" + "x" * 300 + ".png"
    values[long_path] = {"tags": PathValue("cat, sky")}
    model = SpaceModel.fit(preset(1), values)
    model.save(tmp_path)
    raw = len("\n".join(model.paths).encode("utf-8")) + model.matrix.nbytes + model.coords.nbytes
    assert (tmp_path / "model-v1.npz").stat().st_size < raw + 2048
    assert SpaceModel.load(tmp_path, preset(1)).paths == model.paths


def test_mismatched_model_raises_load_error(tmp_path):
    import pickle

    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)
    pkl = tmp_path / "model-v1.pkl"
    state = pickle.loads(pkl.read_bytes())
    state["encoders"] = state["encoders"][:1]
    pkl.write_bytes(pickle.dumps(state))
    with pytest.raises(SpaceLoadError):
        SpaceModel.load(tmp_path, preset(1))

    SpaceModel.fit(preset(2), tag_values()).save(tmp_path)
    path = tmp_path / "model-v2.npz"
    with np.load(path) as arrays:
        data = {k: arrays[k] for k in arrays.files}
    data["coords"] = data["coords"][:-1]
    np.savez(path, **data)
    with pytest.raises(SpaceLoadError):
        SpaceModel.load(tmp_path, preset(2))


def test_load_ignores_a_model_built_from_another_preset(tmp_path):
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path)
    other = Preset([FeatureSpec("tags", "text")], TrainParams(), 1)
    assert SpaceModel.load(tmp_path, other) is None
    retuned = Preset(preset(1).features, TrainParams(neighbors=2.0), 1)
    assert SpaceModel.load(tmp_path, retuned) is None
    assert SpaceModel.load(tmp_path, preset(1)) is not None


def test_grouping_coordinates_do_not_depend_on_spacing(monkeypatch):
    calls = []

    def spacing_embed(matrix, neighbors, min_dist, seed, dims=2, **_):
        calls.append((dims, min_dist))
        return np.full((matrix.shape[0], dims), min_dist, dtype=np.float32) + matrix[:, :1]

    monkeypatch.setattr(projection, "embed", spacing_embed)
    tight = SpaceModel.fit(Preset([FeatureSpec("tags", "token_set")], TrainParams(min_dist=0.05), 1), tag_values())
    loose = SpaceModel.fit(Preset([FeatureSpec("tags", "token_set")], TrainParams(min_dist=0.9), 1), tag_values())
    grouping = (projection.GROUPING_DIMS, projection.GROUPING_MIN_DIST)
    assert calls == [(2, 0.05), grouping, (2, 0.9), grouping]
    assert tight.coords.shape[1] == 2 + projection.GROUPING_DIMS
    assert np.allclose(tight.coords[:, 2:], loose.coords[:, 2:])
    assert not np.allclose(tight.coords[:, :2], loose.coords[:, :2])
    assert tight.place([{"tags": PathValue("cat, sky")}]).shape == (1, 2 + projection.GROUPING_DIMS)


def test_model_with_two_dimensional_grouping_must_be_retrained(tmp_path):
    SpaceModel.fit(preset(2), tag_values()).save(tmp_path)
    path = tmp_path / "model-v2.npz"
    with np.load(path) as arrays:
        data = {k: arrays[k] for k in arrays.files}
    data["coords"] = data["coords"][:, :4]
    np.savez(path, **data)
    with pytest.raises(SpaceLoadError):
        SpaceModel.load(tmp_path, preset(2))


def limited(limit, seed=42):
    return Preset([FeatureSpec("tags", "token_set")], TrainParams(train_limit=limit, seed=seed), 1)


def is_cat(path):
    return int(path.split("/")[-1].split(".")[0]) < 20


def test_fit_learns_from_a_sample_and_places_every_other_file():
    values = tag_values(40)
    model = SpaceModel.fit(limited(10), values)
    assert model.trained == len(model.matrix) == 10
    assert sorted(model.paths) == sorted(values)
    trained = model.paths[: model.trained]
    assert any(is_cat(p) for p in trained) and not all(is_cat(p) for p in trained)
    cat = np.mean([model.coords_for(p) for p in trained if is_cat(p)], axis=0)
    dog = np.mean([model.coords_for(p) for p in trained if not is_cat(p)], axis=0)
    for path in model.paths[model.trained :]:
        point = np.array(model.coords_for(path))
        near, far = (cat, dog) if is_cat(path) else (dog, cat)
        assert np.linalg.norm(point - near) < np.linalg.norm(point - far)


def test_the_training_sample_depends_only_on_the_files_and_the_seed():
    values = tag_values(40)
    first = SpaceModel.fit(limited(10), values)
    shuffled = dict(reversed(list(values.items())))
    assert sorted(SpaceModel.fit(limited(10), shuffled).paths[:10]) == sorted(first.paths[:10])
    assert sorted(SpaceModel.fit(limited(10, seed=7), values).paths[:10]) != sorted(first.paths[:10])


def test_zero_training_limit_learns_from_every_file():
    assert SpaceModel.fit(limited(0), tag_values(40)).trained == 40


def test_files_without_values_are_left_out_of_the_space():
    values = {**tag_values(40), "c:/empty.png": {}}
    model = SpaceModel.fit(limited(10), values)
    assert model.coords_for("c:/empty.png") is None and len(model.paths) == 40


def test_placed_files_survive_save_and_load(tmp_path):
    model = SpaceModel.fit(limited(10), tag_values(40))
    model.save(tmp_path)
    loaded = SpaceModel.load(tmp_path, limited(10))
    assert loaded.trained == 10 and loaded.paths == model.paths
    assert np.allclose(loaded.coords, model.coords)


def test_cancelling_while_placing_stops_the_fit(monkeypatch):
    monkeypatch.setattr(space, "PLACE_BATCH", 5)
    checks = []

    def cancelled():
        checks.append(1)
        return len(checks) > 3

    with pytest.raises(MapError):
        SpaceModel.fit(limited(10), tag_values(40), cancelled=cancelled)


def test_the_training_sample_is_drawn_only_from_files_with_values():
    values = {**tag_values(40), **{f"c:/bare{i}.png": {"modified": PathValue(str(i), float(i))} for i in range(400)}}
    model = SpaceModel.fit(limited(10), values)
    assert model.trained == 10 and len(model.paths) == 40
    assert all(path in tag_values(40) for path in model.paths)


def test_placing_encodes_each_distinct_value_once_with_the_same_result(monkeypatch):
    model = SpaceModel.fit(limited(10), tag_values(40))
    entries = [{"tags": PathValue("cat, sky")}, {"tags": PathValue("dog, sea")}, {"tags": PathValue("cat, sky")}, {}, {"tags": PathValue("dog, sea")}]
    separately = np.vstack([model.place([entry]) for entry in entries])
    encoded = []
    encoder = model.encoders[0]
    original = type(encoder).transform
    monkeypatch.setattr(type(encoder), "transform", lambda self, inputs: encoded.append(len(inputs)) or original(self, inputs))
    together = model.place(entries)
    assert encoded == [3]
    assert np.allclose(together, separately, equal_nan=True)


def test_placing_reuses_encoded_values_across_batches(monkeypatch):
    monkeypatch.setattr(space, "PLACE_BATCH", 5)
    values = {**tag_values(40), **{f"c:/copy/{i}.png": {"tags": PathValue("cat, sky" if i % 2 else "dog, sea")} for i in range(30)}}
    encoded = []
    original = ENCODERS["token_set"].transform
    monkeypatch.setattr(ENCODERS["token_set"], "transform", lambda self, inputs: encoded.append(len(inputs)) or original(self, inputs))
    SpaceModel.fit(limited(10), values)
    assert sum(encoded) == 2


def test_viewer_reads_the_saved_model_once_per_version(tmp_path, monkeypatch):
    monkeypatch.setattr(space, "model_dir", lambda name: tmp_path / name)
    space.forget_space_models()
    current = preset(3)
    assert space.space_model("db1", current) is None
    SpaceModel.fit(current, tag_values()).save(tmp_path / "db1")
    loads = []
    original = SpaceModel.load
    monkeypatch.setattr(SpaceModel, "load", classmethod(lambda cls, *a: loads.append(1) or original.__func__(cls, *a)))
    model = space.space_model("db1", current)
    assert model is not None and space.space_model("db1", current) is model and loads == [1]
    whole = model.whole_space()
    assert whole is model.whole_space() and whole.size == 40 and whole.coords.shape == (40, 2 + projection.GROUPING_DIMS)
    SpaceModel.fit(preset(4), tag_values()).save(tmp_path / "db1")
    assert space.space_model("db1", preset(4)) is not model and loads == [1, 1]
    space.forget_space_models()


def test_unreadable_model_is_not_retried_until_it_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(space, "model_dir", lambda name: tmp_path / name)
    space.forget_space_models()
    SpaceModel.fit(preset(1), tag_values()).save(tmp_path / "db1")
    (tmp_path / "db1" / "model-v1.pkl").write_bytes(b"broken")
    assert space.space_model("db1", preset(1)) is None
    monkeypatch.setattr(SpaceModel, "load", classmethod(lambda cls, *a: pytest.fail("must not reload")))
    assert space.space_model("db1", preset(1)) is None
    space.forget_space_models()


def test_relayout_lays_out_only_the_given_files_from_their_space_positions(monkeypatch):
    calls = []

    def record(matrix, neighbors, min_dist, seed, dims=2, init=None, epochs=projection.LAYOUT_EPOCHS):
        calls.append((len(matrix), dims, min_dist, epochs, None if init is None else init.shape))
        return np.asarray(init, dtype=np.float32) * 2

    model = SpaceModel.fit(preset(), tag_values())
    monkeypatch.setattr(projection, "embed", record)
    entries = [{"tags": PathValue("cat, sky")}] * 4 + [{}] + [{"tags": PathValue("dog, sea")}] * 4
    start = np.arange(9 * (2 + projection.GROUPING_DIMS), dtype=np.float32).reshape(9, -1)
    local = model.relayout(entries, start)
    params = preset().params
    assert calls == [(8, 2, params.min_dist, projection.LOCAL_EPOCHS, (8, 2)), (8, projection.GROUPING_DIMS, projection.GROUPING_MIN_DIST, projection.LOCAL_EPOCHS, (8, projection.GROUPING_DIMS))]
    assert np.isnan(local[4]).all()
    assert np.allclose(np.delete(local, 4, axis=0), np.delete(start, 4, axis=0) * 2)


def test_relayout_learns_from_the_training_limit_and_places_the_rest(monkeypatch):
    model = SpaceModel.fit(limited(10), tag_values(40))
    sizes = []
    monkeypatch.setattr(projection, "embed", lambda matrix, neighbors, d, s, dims=2, init=None, **_: sizes.append(len(matrix)) or np.asarray(init, dtype=np.float32))
    entries = [{"tags": PathValue("cat, sky" if i < 15 else "dog, sea")} for i in range(30)]
    start = np.zeros((30, 2 + projection.GROUPING_DIMS), dtype=np.float32)
    start[15:] = 10.0
    local = model.relayout(entries, start)
    assert sizes == [10, 10] and np.isfinite(local).all()
    assert np.allclose(local[:15], 0.0, atol=1e-3) and np.allclose(local[15:], 10.0, atol=1e-3)


def test_cancelling_a_relayout_stops_it():
    model = SpaceModel.fit(preset(), tag_values())
    start = np.zeros((4, 2 + projection.GROUPING_DIMS), dtype=np.float32)
    with pytest.raises(MapError):
        model.relayout([{"tags": PathValue("cat")}] * 4, start, cancelled=lambda: True)


def test_fit_reports_its_stages_and_logs_each_key_share(monkeypatch):
    stages, logged = [], []
    monkeypatch.setattr(space.AppLogger, "info", lambda message, *a, **k: logged.append(message))
    SpaceModel.fit(preset(), tag_values(), progress=stages.append)
    assert stages == ["encode", "layout"]
    assert any("tags=" in message and "color.palette=" in message for message in logged)


def test_cancelling_before_encoding_encodes_nothing(monkeypatch):
    encoded = []
    original = ENCODERS["token_set"].fit_transform
    monkeypatch.setattr(ENCODERS["token_set"], "fit_transform", lambda self, inputs: encoded.append(1) or original(self, inputs))
    with pytest.raises(MapError):
        SpaceModel.fit(preset(), tag_values(), cancelled=lambda: True)
    assert encoded == []


def test_both_layouts_share_one_neighbor_search_of_the_resolved_size(monkeypatch):
    searched, used = [], []
    real_search = projection.nearest_neighbors

    def search(matrix, n_neighbors, seed):
        searched.append(n_neighbors)
        return real_search(matrix, n_neighbors, seed)

    def record(matrix, neighbors, min_dist, seed, dims=2, **_):
        used.append(neighbors)
        return np.zeros((matrix.shape[0], dims), dtype=np.float32) + matrix[:, :1]

    monkeypatch.setattr(projection, "nearest_neighbors", search)
    monkeypatch.setattr(projection, "embed", record)
    SpaceModel.fit(limited(10), tag_values(40))
    assert searched == [TrainParams().resolved_neighbors(10)]
    assert len(used) == 2 and used[0] is used[1]


def test_model_layout_shows_the_fitted_files_grouped_by_their_own_count(monkeypatch):
    from extensions.mapping.params import Grouping, ViewParams

    built = []
    real_tree = projection.ClusterTree
    monkeypatch.setattr(projection, "ClusterTree", lambda points, samples: built.append(len(points)) or real_tree(points, samples))
    values = {**tag_values(40), "c:/empty.png": {}}
    model = SpaceModel.fit(limited(10), values)
    layout = model.layout(values)
    first = layout.run(ViewParams())
    assert first.paths == model.paths and not first.unset.any()
    assert np.isfinite(first.positions).all() and first.labels is not None
    assert built == [40]
    layout.run(ViewParams(), grouping=Grouping(fine=1))
    assert built == [40]


def test_relayout_reports_encode_then_layout(monkeypatch):
    model = SpaceModel.fit(preset(), tag_values())
    monkeypatch.setattr(projection, "embed", lambda matrix, neighbors, d, s, dims=2, init=None, **_: np.asarray(init, dtype=np.float32))
    stages = []
    start = np.zeros((4, 2 + projection.GROUPING_DIMS), dtype=np.float32)
    model.relayout([{"tags": PathValue("cat, sky")}] * 4, start, progress=stages.append)
    assert stages == ["encode", "layout"]


def test_model_layout_keeps_the_model_for_placing_new_files():
    model = SpaceModel.fit(preset(), tag_values())
    values = {**tag_values(), "c:/new.png": {"tags": PathValue("cat, sky")}}
    layout = SpaceLayout([*model.paths, "c:/new.png"], values, model.preset, model)
    assert layout.model is model
    plain = layout.run(ViewParams(), grouped=False)
    assert not plain.unset.any()


def test_cancelling_a_relayout_stops_between_encoding_batches(monkeypatch):
    monkeypatch.setattr(space, "PLACE_BATCH", 5)
    model = SpaceModel.fit(preset(), tag_values())
    encoded = []
    encoder = model.encoders[0]
    original = type(encoder).transform
    monkeypatch.setattr(type(encoder), "transform", lambda self, inputs: encoded.append(len(inputs)) or original(self, inputs))
    entries = [{"tags": PathValue(f"tag{i}, sky")} for i in range(40)]
    start = np.zeros((40, 2 + projection.GROUPING_DIMS), dtype=np.float32)
    with pytest.raises(MapError):
        model.relayout(entries, start, cancelled=lambda: bool(encoded))
    assert encoded == [5]


def test_relayout_uses_the_given_spacing_for_the_display_layout_only(monkeypatch):
    model = SpaceModel.fit(preset(), tag_values())
    calls = []
    monkeypatch.setattr(projection, "embed", lambda matrix, neighbors, d, s, dims=2, init=None, **_: calls.append((dims, d)) or np.asarray(init, dtype=np.float32))
    start = np.zeros((4, 2 + projection.GROUPING_DIMS), dtype=np.float32)
    model.relayout([{"tags": PathValue("cat, sky")}] * 4, start, min_dist=0.4)
    assert calls == [(2, 0.4), (projection.GROUPING_DIMS, projection.GROUPING_MIN_DIST)]
    calls.clear()
    model.relayout([{"tags": PathValue("cat, sky")}] * 4, start)
    assert calls[0] == (2, model.preset.params.min_dist)

import numpy as np
import pytest

from extensions.mapping import projection, space
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec, MapError
from extensions.mapping.space import Preset, SpaceLoadError, SpaceModel, SpaceStatus, load_preset, read_status, save_preset, write_status
from wafer.core.db.path_values import PathValue


@pytest.fixture(autouse=True)
def fast_embed(monkeypatch):
    def fake_embed(matrix, n_components, n_neighbors, min_dist, seed):
        out = np.zeros((matrix.shape[0], n_components), dtype=np.float32)
        width = min(n_components, matrix.shape[1])
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
    return Preset([FeatureSpec("tags", "token_set"), FeatureSpec("color.palette", "palette")], MapParams(), version)


def test_preset_roundtrip_and_keys(settings):
    save_preset("db1", preset(3))
    loaded = load_preset("db1")
    assert loaded.version == 3 and [f.key for f in loaded.features] == ["tags", "color.palette"]
    assert loaded.trigger_keys()[:2] == ("file_hash", "tags")
    assert "color.palette.1" in loaded.value_keys() and "color.palette.30" in loaded.value_keys()
    assert load_preset("missing") is None
    assert Preset.from_dict({"features": "bad"}) is None


def test_fit_places_training_files_and_new_files_near_neighbours():
    model = SpaceModel.fit(preset(), tag_values())
    assert len(model.train_paths) == 40
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
    assert loaded.train_paths == second.train_paths
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


def test_saved_model_drops_training_texts_and_still_places(tmp_path):
    import pickle

    texts = {f"c:/{i}.png": {"tags": PathValue("cat, sky" if i < 20 else "dog, sea"), "prompt": PathValue(f"a long prompt number {i}")} for i in range(40)}
    features = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("prompt", "text")], MapParams(), 1)
    model = SpaceModel.fit(features, texts)
    before = model.place([{"tags": PathValue("cat, sky"), "prompt": PathValue("a long prompt number 3")}])
    model.save(tmp_path)
    state = pickle.loads((tmp_path / "model-v1.pkl").read_bytes())
    tag_encoder, text_encoder = state["encoders"]
    assert tag_encoder.matrix is None and tag_encoder.names == []
    assert text_encoder.texts == []
    loaded = SpaceModel.load(tmp_path, features)
    after = loaded.place([{"tags": PathValue("cat, sky"), "prompt": PathValue("a long prompt number 3")}])
    assert np.allclose(before, after)


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
    assert placed.shape == (1, 2) and np.isfinite(placed).all()


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
    raw = len("\n".join(model.train_paths).encode("utf-8")) + model.matrix.nbytes + model.coords.nbytes
    assert (tmp_path / "model-v1.npz").stat().st_size < raw + 2048
    assert SpaceModel.load(tmp_path, preset(1)).train_paths == model.train_paths


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
    other = Preset([FeatureSpec("tags", "text")], MapParams(), 1)
    assert SpaceModel.load(tmp_path, other) is None
    retuned = Preset(preset(1).features, MapParams(n_neighbors=30), 1)
    assert SpaceModel.load(tmp_path, retuned) is None
    assert SpaceModel.load(tmp_path, preset(1)) is not None

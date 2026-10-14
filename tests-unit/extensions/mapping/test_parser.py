import sqlite3
import threading
import time

import numpy as np
import pytest

from extensions.mapping import parser as parser_module
from extensions.mapping import projection, space
from extensions.mapping.params import MapParams
from extensions.mapping.parser import MappingParser
from extensions.mapping.session import FeatureSpec, MapError
from extensions.mapping.space import Preset, SpaceStatus, read_status, save_preset, write_status
from wafer.core.db.file_db import FileDB


@pytest.fixture()
def env(tmp_path, monkeypatch):
    import wafer.core.common.paths as paths

    db_path = tmp_path / "map.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    rows = [(f"c:/{i}.png", f"h{i}", 100, 1.0, 1.0, 1.0) for i in range(30)]
    db.upsert_basic_sources(rows, [(f"c:/{i}.png", f"c:/{i}.png", f"{i}.png", 1.0, None) for i in range(30)])
    db.upsert_collection_results([], [], [(f"c:/{i}.png", "wd14.tags", "cat, sky" if i < 15 else "dog, sea", None) for i in range(30)], [])
    settings = lambda name: str(tmp_path / f"{name}.settings.db")
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))
    monkeypatch.setattr(paths, "setting_db_path", settings)
    monkeypatch.setattr(space, "setting_db_path", settings)
    monkeypatch.setattr(space, "resolve_cache_path", lambda rel: str(tmp_path / "cache" / rel))
    monkeypatch.setattr(parser_module, "data_db_path", lambda name: str(db_path))
    monkeypatch.setattr(projection, "embed", lambda m, n, k, d, s: np.asarray(m[:, :n], dtype=np.float32))
    save_preset("map", Preset([FeatureSpec("wd14.tags", "token_set")], MapParams(), 1))
    plugin = MappingParser()
    plugin.db_name = "map"
    yield plugin, db, tmp_path
    plugin.shutdown()
    db.close()


def run(plugin, path):
    return plugin.process(path, (1.0, 100, "h"), {})


def test_trigger_keys_follow_the_preset(env):
    assert MappingParser.trigger_keys("map") == ("file_hash", "wd14.tags")
    assert MappingParser.trigger_keys("unknown") == ("file_hash",)


def test_first_call_trains_and_writes_training_coordinates(env):
    plugin, _db, tmp = env
    result = run(plugin, "c:/0.png")
    assert result.status and set(result.meta_info) == {"x", "y", "model"}
    assert result.meta_info["model"] == "1"
    assert read_status(tmp / "cache" / "mapping" / "map").state == "ready"


def test_new_file_is_placed_near_similar_files(env):
    plugin, db, _tmp = env
    run(plugin, "c:/0.png")
    db.upsert_basic_sources([("c:/new.png", "hn", 1, 1.0, 1.0, 1.0)], [("c:/new.png", "c:/new.png", "new.png", 1.0, None)])
    db.upsert_collection_results([], [], [("c:/new.png", "wd14.tags", "cat, sky", None)], [])
    placed = run(plugin, "c:/new.png").meta_info
    cat, dog = run(plugin, "c:/1.png").meta_info, run(plugin, "c:/20.png").meta_info
    point = lambda m: np.array([float(m["x"]), float(m["y"])])
    assert np.linalg.norm(point(placed) - point(cat)) < np.linalg.norm(point(placed) - point(dog))


def test_file_without_values_clears_coordinates(env):
    plugin, db, _tmp = env
    db.upsert_basic_sources([("c:/empty.png", "he", 1, 1.0, 1.0, 1.0)], [("c:/empty.png", "c:/empty.png", "empty.png", 1.0, None)])
    result = run(plugin, "c:/empty.png")
    assert result.status and result.delete_meta_keys == ["mapping.x", "mapping.y", "mapping.model"]


def test_version_change_retrains(env, monkeypatch):
    plugin, _db, _tmp = env
    run(plugin, "c:/0.png")
    calls = []
    original = space.SpaceModel.fit
    monkeypatch.setattr(space.SpaceModel, "fit", classmethod(lambda cls, *a, **k: calls.append(1) or original.__func__(cls, *a, **k)))
    save_preset("map", Preset([FeatureSpec("wd14.tags", "token_set")], MapParams(), 2))
    monkeypatch.setattr(parser_module, "PRESET_TTL", 0.0)
    assert run(plugin, "c:/0.png").meta_info["model"] == "2"
    assert calls == [1]


def test_stuck_training_status_is_retrained(env):
    plugin, _db, tmp = env
    write_status(tmp / "cache" / "mapping" / "map", SpaceStatus("training", 1))
    assert run(plugin, "c:/0.png").meta_info["model"] == "1"


def test_unreadable_model_passes_files_through(env):
    plugin, _db, tmp = env
    run(plugin, "c:/0.png")
    (tmp / "cache" / "mapping" / "map" / "model-v1.pkl").write_bytes(b"broken")
    fresh = MappingParser()
    fresh.db_name = "map"
    result = run(fresh, "c:/1.png")
    assert result.status and result.meta_info is None
    assert read_status(tmp / "cache" / "mapping" / "map").state == "unreadable"
    fresh.shutdown()


def test_training_failure_marks_failed_and_is_not_retried(env, monkeypatch):
    plugin, _db, tmp = env
    save_preset("map", Preset([FeatureSpec("missing.key", "text")], MapParams(), 3))
    calls = []
    original = space.SpaceModel.fit
    monkeypatch.setattr(space.SpaceModel, "fit", classmethod(lambda cls, *a, **k: calls.append(1) or original.__func__(cls, *a, **k)))
    assert run(plugin, "c:/0.png").status is False
    assert run(plugin, "c:/1.png").status is False
    assert calls == [1]
    assert read_status(tmp / "cache" / "mapping" / "map").state == "failed"


def test_model_is_released_after_idle(env, monkeypatch):
    plugin, _db, _tmp = env
    monkeypatch.setattr(parser_module, "IDLE_TIMEOUT", 0.05)
    run(plugin, "c:/0.png")
    assert plugin.model is not None
    deadline = time.monotonic() + 2
    while plugin.model is not None and time.monotonic() < deadline:
        time.sleep(0.02)
    assert plugin.model is None


def test_first_call_values_equal_training_coordinates(env):
    plugin, _db, _tmp = env
    meta = run(plugin, "c:/3.png").meta_info
    expected = plugin.model.coords_for("c:/3.png")
    assert (float(meta["x"]), float(meta["y"])) == pytest.approx(expected)


def test_current_version_file_is_placed_by_neighbours(env):
    plugin, db, _tmp = env
    run(plugin, "c:/0.png")
    trained = plugin.model.coords_for("c:/0.png")
    db.upsert_collection_results([], [("c:/0.png", "mapping.model", "1", None)], [("c:/0.png", "wd14.tags", "dog, sea", None)], [])
    meta = run(plugin, "c:/0.png").meta_info
    point = np.array([float(meta["x"]), float(meta["y"])])
    dog = np.array(plugin.model.coords_for("c:/20.png"))
    assert np.linalg.norm(point - dog) < np.linalg.norm(point - np.array(trained))


@pytest.mark.parametrize("error", [sqlite3.OperationalError("locked"), RuntimeError("numba")])
def test_unexpected_training_error_marks_failed_once(env, monkeypatch, error):
    plugin, _db, tmp = env
    calls = []

    def broken(cls, *a, **k):
        calls.append(1)
        raise error

    monkeypatch.setattr(space.SpaceModel, "fit", classmethod(broken))
    assert run(plugin, "c:/0.png").status is False
    assert run(plugin, "c:/1.png").status is False
    assert calls == [1]
    assert read_status(tmp / "cache" / "mapping" / "map").state == "failed"


def test_shutdown_interrupts_training_without_blocking(env, monkeypatch):
    plugin, _db, tmp = env
    started = threading.Event()

    def waiting(cls, preset, values, *, cancelled=lambda: False):
        started.set()
        deadline = time.monotonic() + 5
        while not cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        raise MapError("Cancelled")

    monkeypatch.setattr(space.SpaceModel, "fit", classmethod(waiting))
    results = []
    worker = threading.Thread(target=lambda: results.append(run(plugin, "c:/0.png")))
    worker.start()
    assert started.wait(5)
    plugin.shutdown()
    worker.join(5)
    assert not worker.is_alive()
    assert results[0].status is False
    assert read_status(tmp / "cache" / "mapping" / "map").state == "training"
    assert plugin.blocked is None
    assert plugin.idle_timer is None


def test_failed_read_keeps_coordinates(env, monkeypatch):
    plugin, _db, _tmp = env
    run(plugin, "c:/0.png")
    monkeypatch.setattr(parser_module, "fetch_path_values", lambda *a, **k: {})
    result = run(plugin, "c:/new.png")
    assert result.status is False and not result.delete_meta_keys

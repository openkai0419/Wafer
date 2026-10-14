import pytest

from extensions.mapping import space, space_panel
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec
from extensions.mapping.space import Preset, SpaceStatus, save_preset, write_status
from extensions.mapping.space_panel import MappingSpacePlugin, MappingSpaceWidget, current_status, read_snapshot, status_text
from wafer.core.db.file_db import FileDB


def test_status_text_states():
    assert "cannot be read" in status_text(SpaceStatus("unreadable", 2), total=10, placed=0)
    assert "recommended" in status_text(SpaceStatus("ready", 2, trained=100), total=130, placed=100)
    assert "recommended" not in status_text(SpaceStatus("ready", 2, trained=100), total=110, placed=100)
    assert "boom" in status_text(SpaceStatus("failed", 2, error="boom"), total=10, placed=0)


def test_status_text_counts_and_model_size():
    text = status_text(SpaceStatus("ready", 3, trained=100), total=130, placed=90, model_bytes=3 * 1024 * 1024)
    assert "v3" in text and "90 of 130" in text and "40 waiting" in text and "30 files added" in text and "3.0 MB" in text
    assert "MB" not in status_text(SpaceStatus("ready", 3, trained=100), total=100, placed=100)


def test_stale_status_reads_as_training():
    assert current_status(SpaceStatus("ready", 1, trained=5), 2) == SpaceStatus("training", 2)
    assert current_status(SpaceStatus("failed", 1, error="x"), 2) == SpaceStatus("training", 2)
    assert current_status(SpaceStatus("ready", 2, trained=5), 2) == SpaceStatus("ready", 2, trained=5)
    assert current_status(SpaceStatus("none", 0), 0) == SpaceStatus("none", 0)


@pytest.fixture()
def widget(qtbot, monkeypatch, tmp_path):
    saved = {}
    resets = []
    monkeypatch.setattr(space_panel, "load_preset", lambda name: saved.get(name))
    monkeypatch.setattr(space_panel, "save_preset", lambda name, preset: saved.__setitem__(name, preset))
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(tmp_path / f"{name}.db"))
    monkeypatch.setattr(space_panel.Recollect, "reset", staticmethod(lambda **kw: resets.append(kw) or 1))
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: None)
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "db1"
    w.apply_preset(Preset([FeatureSpec("tags", "token_set")], MapParams(), 1))
    yield w, saved, resets
    w.close()


def test_edits_mark_dirty_and_revert(widget):
    w, _saved, _resets = widget
    assert not w.is_dirty()
    w.feature_bar.add_feature("path")
    assert w.is_dirty() and w.revert_button.isEnabled()
    w.revert()
    assert not w.is_dirty() and not w.revert_button.isEnabled()
    assert [f.key for f in w.feature_bar.features()] == ["tags"]


def test_param_edits_mark_dirty(widget):
    w, _saved, _resets = widget
    w.tuning.controls["n_neighbors"].setValue(30)
    assert w.is_dirty()
    w.revert()
    assert not w.is_dirty() and w.tuning.params() == MapParams()


def test_form_hides_cluster_and_view_stages(widget):
    w, _saved, _resets = widget
    assert "n_neighbors" in w.tuning.controls
    assert "hover_size" not in w.tuning.controls and "min_cluster_size" not in w.tuning.controls


def test_save_and_retrain_bumps_version_and_resets_collection(widget):
    w, saved, resets = widget
    w.feature_bar.add_feature("path")
    w.save_and_retrain()
    assert saved["db1"].version == 2 and [f.key for f in saved["db1"].features] == ["tags", "path"]
    assert resets == [{"collector": "mapping", "db_scope": "db1"}]
    assert not w.is_dirty()
    assert "Training" in w.status_label.text() and "v2" in w.status_label.text()


def test_save_without_features_does_nothing(widget):
    w, saved, resets = widget
    w.feature_bar.set_features([])
    w.save_and_retrain()
    assert saved == {} and resets == []


def test_parser_warning_is_shown_only_when_disabled(widget):
    w, _saved, _resets = widget
    w.parser_on = False
    w.render_status()
    assert "Enable the Mapping parser" in w.status_label.text()
    w.parser_on = True
    w.render_status()
    assert "Enable the Mapping parser" not in w.status_label.text()


def test_enablement_follows_the_database_setting_then_defaults(monkeypatch):
    class Setting:
        enabled = None

        def __init__(self, path):
            pass

        def get_enabled_collectors(self):
            return Setting.enabled

    monkeypatch.setattr(space_panel, "SettingDB", Setting)
    monkeypatch.setattr(space_panel, "setting_db_path", lambda name: name)
    monkeypatch.setattr(space_panel.PluginSettings, "resolve_default_collectors", lambda self: ["other"])
    assert not space_panel.parser_enabled("db1")
    Setting.enabled = ["mapping"]
    assert space_panel.parser_enabled("db1")
    Setting.enabled = []
    assert not space_panel.parser_enabled("db1")


@pytest.fixture()
def database(tmp_path, monkeypatch):
    db_path = tmp_path / "map.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    count = 12
    db.upsert_basic_sources([(f"c:/{i}.png", f"h{i}", 100, 1.0, 1.0, 1.0) for i in range(count)], [(f"c:/{i}.png", f"c:/{i}.png", f"{i}.png", 1.0, None) for i in range(count)])
    meta = []
    for i in range(count - 2):
        meta += [(f"c:/{i}.png", "mapping.x", str(i), float(i)), (f"c:/{i}.png", "mapping.y", str(i % 3), float(i % 3)), (f"c:/{i}.png", "mapping.model", "1", 1.0)]
    db.upsert_collection_results([], meta, [(f"c:/{i}.png", "wd14.tags", "cat, sky", None) for i in range(count)], [])
    settings = lambda name: str(tmp_path / f"{name}.settings.db")
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(db_path))
    monkeypatch.setattr(space_panel, "setting_db_path", settings)
    monkeypatch.setattr(space, "setting_db_path", settings)
    monkeypatch.setattr(space, "resolve_cache_path", lambda rel: str(tmp_path / "cache" / rel))
    monkeypatch.setattr(space_panel.PluginSettings, "resolve_default_collectors", lambda self: [])
    save_preset("map", Preset([FeatureSpec("wd14.tags", "token_set")], MapParams(), 1))
    write_status(tmp_path / "cache" / "mapping" / "map", SpaceStatus("ready", 1, trained=10))
    (tmp_path / "cache" / "mapping" / "map" / "model-v1.npz").write_bytes(b"x" * 2048)
    yield tmp_path
    db.close()


def test_snapshot_reads_counts_status_and_preview(database):
    snapshot = read_snapshot("map")
    assert snapshot.preset.version == 1 and snapshot.status.state == "ready"
    assert snapshot.total == 12 and snapshot.placed == 10
    assert snapshot.model_bytes == 2048
    assert not snapshot.parser_enabled
    assert snapshot.result is not None and len(snapshot.result.paths) == 10 and not snapshot.result.unset.any()
    assert len(snapshot.detect_paths) == 12 and set(snapshot.sources) == set(snapshot.result.paths)


def test_snapshot_without_a_saved_preset_has_no_preview(database, monkeypatch):
    monkeypatch.setattr(space_panel, "load_preset", lambda name: None)
    snapshot = read_snapshot("map")
    assert snapshot.preset.version == 0 and snapshot.preset.features == []
    assert snapshot.total == 12 and snapshot.placed == 0 and snapshot.result is None


def test_snapshot_is_empty_when_the_database_is_missing(database, monkeypatch, tmp_path):
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(tmp_path / "missing.db"))
    snapshot = read_snapshot("map")
    assert snapshot.total == 0 and snapshot.result is None


def test_apply_snapshot_shows_preview_and_keeps_unsaved_edits(widget, database, monkeypatch):
    w, _saved, _resets = widget
    monkeypatch.setattr(space_panel, "load_preset", space.load_preset)
    snapshot = read_snapshot("map")
    w.feature_bar.add_feature("path")
    w.apply_snapshot(snapshot)
    assert w.saved.version == 1 and [f.key for f in w.feature_bar.features()] == ["tags", "path"]
    assert len(w.map_view.paths) == 10 and "10 of 12" in w.status_label.text()
    assert "Enable the Mapping parser" in w.status_label.text()
    w.revert()
    assert [f.key for f in w.feature_bar.features()] == ["wd14.tags"]


def test_plugin_identity_and_state(qtbot):
    assert MappingSpacePlugin.NAME == "mapping_space" and MappingSpacePlugin.DISPLAY_NAME == "Mapping Space"
    assert MappingSpacePlugin.DEFAULT_ENABLED and MappingSpacePlugin.STANDALONE_AVAILABLE
    plugin = MappingSpacePlugin()
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert isinstance(widget, MappingSpaceWidget)
    assert "splitter" in plugin.save_ui_state()
    widget.close()
    MappingSpacePlugin.saved_state = {}


def test_refresh_loads_preview_and_key_catalog_in_background(qtbot, database):
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "map"
    w.refresh()
    qtbot.waitUntil(lambda: len(w.map_view.paths) == 10 and bool(w.feature_bar.keys), timeout=10000)
    assert [f.key for f in w.feature_bar.features()] == ["wd14.tags"]
    keys = dict(w.feature_bar.keys)
    assert "wd14.tags" in keys and not set(keys) & set(space_panel.SPACE_KEYS)
    w.close()

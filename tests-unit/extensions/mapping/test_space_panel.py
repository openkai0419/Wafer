from contextlib import closing

import threading
import time

import numpy as np
import pytest
from PySide6 import QtCore

from extensions.mapping import projection, space, space_panel
from extensions.mapping.params import Grouping, TrainParams, ViewParams
from extensions.mapping.projection import GROUPING_DIMS
from extensions.mapping.session import FeatureSpec, MapError, coordinate_text
from extensions.mapping.space import Preset, SpaceModel, SpaceStatus, save_preset, write_status
from extensions.mapping.view_settings import ViewSettings
from extensions.mapping.space_panel import MappingSpaceWidget, SpaceSnapshot, current_status, read_snapshot, status_text
from wafer.core.db.db_utils import open_readonly
from wafer.core.db.file_db import FileDB
from wafer.core.db.path_values import PathValue


def test_status_text_states():
    assert "cannot be read" in status_text(SpaceStatus("unreadable", 2), total=10, placed=0)
    assert "recommended" in status_text(SpaceStatus("ready", 2, trained=60, sources_at_training=100), total=130, placed=100)
    assert "recommended" not in status_text(SpaceStatus("ready", 2, trained=60, sources_at_training=100), total=110, placed=100)
    assert "boom" in status_text(SpaceStatus("failed", 2, error="boom"), total=10, placed=0)


def test_status_text_counts_and_model_size():
    text = status_text(SpaceStatus("ready", 3, trained=100, sources_at_training=100), total=130, placed=90, waiting=25, model_bytes=3 * 1024 * 1024)
    assert "v3" in text and "90 of 130" in text and "25 waiting" in text and "30 files added" in text and "3.0 MB" in text
    assert "MB" not in status_text(SpaceStatus("ready", 3, trained=100, sources_at_training=100), total=100, placed=100)


def test_files_without_values_are_not_counted_as_added_or_waiting():
    text = status_text(SpaceStatus("ready", 2, trained=40, sources_at_training=100), total=100, placed=40)
    assert "added" not in text and "waiting" not in text and "recommended" not in text


def test_stale_status_reads_as_training():
    assert current_status(SpaceStatus("ready", 1, trained=5), 2) == SpaceStatus("training", 2)
    assert current_status(SpaceStatus("failed", 1, error="x"), 2) == SpaceStatus("training", 2)
    assert current_status(SpaceStatus("ready", 2, trained=5), 2) == SpaceStatus("ready", 2, trained=5)
    assert current_status(SpaceStatus("none", 0), 0) == SpaceStatus("none", 0)


@pytest.fixture(autouse=True)
def deterministic_groups(fake_cluster):
    return None


@pytest.fixture()
def widget(qtbot, monkeypatch, tmp_path):
    saved = {}
    resets = []
    monkeypatch.setattr(space_panel, "load_preset", lambda name: saved.get(name))
    monkeypatch.setattr(space_panel, "save_preset", lambda name, preset: saved.__setitem__(name, preset))
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(tmp_path / f"{name}.db"))
    monkeypatch.setattr(space_panel.Recollect, "reset", staticmethod(lambda **kw: resets.append(kw) or 1))
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: None)
    monkeypatch.setattr(MappingSpaceWidget, "sync_host", lambda self: None)
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "db1"
    w.apply_preset(Preset([FeatureSpec("tags", "token_set")], TrainParams(), 1))
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
    w.tuning.controls["neighbors"].setValue(2.0)
    assert w.is_dirty()
    w.revert()
    assert not w.is_dirty() and w.tuning.params() == TrainParams()


def test_form_shows_layout_stage_only(widget):
    w, _saved, _resets = widget
    assert "neighbors" in w.tuning.controls and "train_limit" in w.tuning.controls
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
        meta.append((f"c:/{i}.png", "mapping.model", "1", 1.0))
        meta.append((f"c:/{i}.png", "mapping.2d", coordinate_text([float(i), float(i % 3)]), None))
        meta.append((f"c:/{i}.png", "mapping.group", coordinate_text([float(i), float(i % 3)] + [0.0] * (GROUPING_DIMS - 2)), None))
    db.upsert_collection_results([], meta, [(f"c:/{i}.png", "wd14.tags", "cat, sky", None) for i in range(count)], [])
    settings = lambda name: str(tmp_path / f"{name}.settings.db")
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(db_path))
    monkeypatch.setattr(space_panel, "setting_db_path", settings)
    monkeypatch.setattr(space, "setting_db_path", settings)
    monkeypatch.setattr(space, "resolve_cache_path", lambda rel: str(tmp_path / "cache" / rel))
    monkeypatch.setattr(space_panel.PluginSettings, "resolve_default_collectors", lambda self: [])
    preset = Preset([FeatureSpec("wd14.tags", "token_set")], TrainParams(), 1)
    save_preset("map", preset)
    trained = {f"c:/{i}.png": {"wd14.tags": PathValue("cat, sky" if i % 2 else "dog, sea")} for i in range(count - 2)}
    with monkeypatch.context() as patch:
        patch.setattr(projection, "embed", lambda matrix, neighbors, d, seed, dims=2, **_: np.tile(np.asarray(matrix, dtype=np.float32), (1, dims))[:, :dims])
        SpaceModel.fit(preset, trained).save(tmp_path / "cache" / "mapping" / "map")
    write_status(tmp_path / "cache" / "mapping" / "map", SpaceStatus("ready", 1, trained=10))
    space.forget_space_models()
    yield db
    space.forget_space_models()
    db.close()


def test_snapshot_reads_counts_status_and_preview(database):
    snapshot = read_snapshot("map", ViewParams())
    assert snapshot.preset.version == 1 and snapshot.status.state == "ready"
    assert snapshot.total == 12 and snapshot.placed == 10 and snapshot.waiting == 0
    assert snapshot.model_bytes > 0
    assert not snapshot.parser_enabled
    assert snapshot.result is not None and len(snapshot.result.paths) == 10 and not snapshot.result.unset.any()
    assert set(snapshot.sources) == set(snapshot.result.paths)


def test_snapshot_without_a_saved_preset_has_no_preview(database, monkeypatch):
    monkeypatch.setattr(space_panel, "load_preset", lambda name: None)
    snapshot = read_snapshot("map", ViewParams())
    assert snapshot.preset.version == 0 and snapshot.preset.features == []
    assert snapshot.total == 12 and snapshot.placed == 0 and snapshot.result is None


def test_snapshot_is_empty_when_the_database_is_missing(database, monkeypatch, tmp_path):
    monkeypatch.setattr(space_panel, "data_db_path", lambda name: str(tmp_path / "missing.db"))
    snapshot = read_snapshot("map", ViewParams())
    assert snapshot.total == 0 and snapshot.result is None


def test_apply_snapshot_shows_preview_and_keeps_unsaved_edits(widget, database, monkeypatch):
    w, _saved, _resets = widget
    monkeypatch.setattr(space_panel, "load_preset", space.load_preset)
    snapshot = read_snapshot("map", ViewParams())
    w.feature_bar.add_feature("path")
    w.apply_snapshot(snapshot)
    assert w.saved.version == 1 and [f.key for f in w.feature_bar.features()] == ["tags", "path"]
    assert len(w.map_view.paths) == 10 and "10 of 12" in w.status_label.text()
    assert "Enable the Mapping parser" in w.status_label.text()
    w.revert()
    assert [f.key for f in w.feature_bar.features()] == ["wd14.tags"]


def test_refresh_loads_preview_and_key_catalog_in_background(qtbot, database):
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "map"
    w.refresh()
    qtbot.waitUntil(lambda: len(w.map_view.paths) == 10 and bool(w.feature_bar.keys), timeout=20000)
    assert [f.key for f in w.feature_bar.features()] == ["wd14.tags"]
    keys = dict(w.feature_bar.keys)
    assert "wd14.tags" in keys and not set(keys) & set(space_panel.SPACE_KEYS)
    w.close()


def add_sparse_files(db):
    paths = [f"c:/sparse/{i}.png" for i in range(20)]
    db.upsert_basic_sources([(path, f"s{i}", 100 + i, 1.0, 1.0, 1.0) for i, path in enumerate(paths)], [(path, path, f"{i}.png", 1.0, None) for i, path in enumerate(paths)])
    db.upsert_collection_results([], [(path, "sparse.score", str(i), float(i)) for i, path in enumerate(paths[-4:])], [(path, "sparse.tags", "cat, sky, sea", None) for path in paths[-4:]], [])


def test_detect_samples_files_that_have_the_key(database, monkeypatch):
    add_sparse_files(database)
    monkeypatch.setattr(space_panel, "DETECT_SAMPLE", 5)
    assert space_panel.detect_key_encoder("map", "sparse.score") == "numeric"
    assert space_panel.detect_key_encoder("map", "sparse.tags") == "token_set"
    assert space_panel.detect_key_encoder("map", "size") == "numeric"
    assert space_panel.detect_key_encoder("map", "missing.key") is None


def test_sampled_paths_mix_meta_and_tag_files(database):
    add_sparse_files(database)
    with closing(open_readonly(str(database.db_path))) as conn:
        assert len(space_panel.sample_paths_with_key(conn, "sparse.score", 3)) == 3
        assert set(space_panel.sample_paths_with_key(conn, "sparse.tags", 10)) == {f"c:/sparse/{i}.png" for i in range(16, 20)}
        assert len(space_panel.sample_paths_with_key(conn, "path", 7)) == 7


def test_added_key_is_detected_in_the_background(widget, database, qtbot, monkeypatch):
    w, _saved, _resets = widget
    add_sparse_files(database)
    monkeypatch.setattr(space_panel, "DETECT_SAMPLE", 5)
    w.feature_bar.add_feature("sparse.score")
    chip = w.feature_bar.chips()[-1]
    assert chip.spec().encoder == space_panel.PROVISIONAL_ENCODER and not w.save_button.isEnabled()
    qtbot.waitUntil(lambda: not w.detecting, timeout=10000)
    assert chip.spec().encoder == "numeric" and w.save_button.isEnabled()


def test_unknown_key_keeps_the_provisional_encoder(widget, database, qtbot):
    w, _saved, _resets = widget
    w.feature_bar.add_feature("missing.key")
    qtbot.waitUntil(lambda: not w.detecting, timeout=10000)
    assert w.feature_bar.chips()[-1].spec().encoder == space_panel.PROVISIONAL_ENCODER


def test_snapshot_counts_waiting_from_mapping_collection_status(database):
    database.upsert_collection_results(
        [], [], [], [("c:/0.png", "mapping", "pending", None), ("c:/1.png", "mapping", "dispatched", None), ("c:/2.png", "mapping", "done", 1.0), ("c:/3.png", "wd14", "pending", None)]
    )
    assert read_snapshot("map", ViewParams()).waiting == 2


def test_save_after_the_database_changed_only_refreshes(widget, monkeypatch):
    w, saved, resets = widget
    refreshed = []
    monkeypatch.setattr(MappingSpaceWidget, "sync_host", lambda self: setattr(self, "db_name", "db2"))
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: refreshed.append(self.db_name))
    w.feature_bar.add_feature("path")
    w.save_and_retrain()
    assert saved == {} and resets == [] and refreshed == ["db2"]


def test_save_failure_is_reported_and_keeps_the_edits(widget, monkeypatch):
    w, _saved, resets = widget

    def broken(name, preset):
        raise OSError("disk full")

    monkeypatch.setattr(space_panel, "save_preset", broken)
    w.feature_bar.add_feature("path")
    w.save_and_retrain()
    assert resets == [] and w.is_dirty() and w.saved.version == 1
    assert "Could not save the settings" in w.status_label.text()


def test_unreached_indexer_is_reported(widget, monkeypatch):
    w, saved, _resets = widget
    monkeypatch.setattr(space_panel.Recollect, "reset", staticmethod(lambda **kw: 0))
    w.feature_bar.add_feature("path")
    w.save_and_retrain()
    assert saved["db1"].version == 2
    assert "Could not reach the indexer; try again." in w.status_label.text()


def test_snapshot_keeps_counts_when_the_preview_fails(database, monkeypatch):
    def broken(*args, **kwargs):
        raise ValueError("bad layout")

    monkeypatch.setattr(space_panel.SpaceLayout, "run", broken)
    snapshot = read_snapshot("map", ViewParams())
    assert snapshot.result is None and snapshot.problem == "bad layout"
    assert snapshot.total == 12 and snapshot.placed == 10 and snapshot.status.state == "ready"


def test_hiding_the_space_panel_hides_the_hover(widget):
    w, _saved, _resets = widget
    w.show()
    w.host.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert w.host.preview.isVisible()
    w.hide()
    assert not w.host.preview.isVisible()


class FakeBridge(QtCore.QObject):
    db_content_updated = QtCore.Signal(str)


def test_indexer_updates_for_this_database_refresh_the_status_once_per_interval(qtbot, monkeypatch):
    from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

    bridge = FakeBridge()
    monkeypatch.setattr(ViewerIpcBridge, "instance", classmethod(lambda cls: bridge))
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: None)
    refreshed = []
    monkeypatch.setattr(MappingSpaceWidget, "refresh_status", lambda self: refreshed.append(self.db_name))
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "db1"
    bridge.db_content_updated.emit("db1")
    assert not w.status_timer.isActive()
    w.show()
    w.status_timer.setInterval(10)
    bridge.db_content_updated.emit("db2")
    assert not w.status_timer.isActive()
    bridge.db_content_updated.emit("db1")
    bridge.db_content_updated.emit("")
    assert w.status_timer.isActive()
    qtbot.waitUntil(lambda: refreshed == ["db1"], timeout=5000)
    qtbot.wait(50)
    assert refreshed == ["db1"]
    w.hide()
    assert not w.status_timer.isActive()
    w.close()


def test_status_refresh_reads_counts_without_the_preview(widget, database, monkeypatch, qtbot):
    w, _saved, _resets = widget
    monkeypatch.setattr(space_panel, "load_preset", space.load_preset)
    monkeypatch.setattr(space_panel.SpaceLayout, "run", lambda *args, **kwargs: pytest.fail("the status refresh must not lay out the preview"))
    w.db_name = "map"
    w.refresh_status()
    qtbot.waitUntil(lambda: w.total == 12, timeout=10000)
    assert w.placed == 10 and "10 of 12" in w.status_label.text()
    assert w.shown is None and w.map_view.paths == []


def test_preview_reloads_only_when_the_space_changes(widget, monkeypatch):
    w, _saved, _resets = widget
    reloads = []
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: reloads.append(1))
    preset = Preset([FeatureSpec("tags", "token_set")], TrainParams(), 2)
    snapshot = lambda placed, state="ready", version=2: SpaceSnapshot(preset, SpaceStatus(state, version), total=100, placed=placed, waiting=100 - placed)
    w.preview_mark = ("training", 2)
    w.on_status(snapshot(0))
    assert reloads == [1]
    w.preview_mark = ("ready", 2)
    w.on_status(snapshot(5))
    w.on_status(snapshot(95))
    assert reloads == [1]
    w.on_status(snapshot(0, "training", 3))
    assert reloads == [1, 1]
    w.preview_loading = True
    w.on_status(snapshot(0, "ready", 3))
    w.preview_loading, w.showing_quick = False, True
    w.on_status(snapshot(0, "ready", 3))
    assert reloads == [1, 1]


def test_preview_shows_the_trained_space_before_the_parser_writes_it(database, tmp_path, monkeypatch):
    preset = Preset([FeatureSpec("wd14.tags", "token_set")], TrainParams(), 2)
    save_preset("map", preset)
    values = {f"c:/{i}.png": {"wd14.tags": PathValue("cat, sky" if i % 2 else "dog, sea")} for i in range(12)}
    monkeypatch.setattr(projection, "embed", lambda matrix, neighbors, d, seed, dims=2, **_: np.tile(np.asarray(matrix, dtype=np.float32), (1, dims))[:, :dims])
    SpaceModel.fit(preset, values).save(tmp_path / "cache" / "mapping" / "map")
    write_status(tmp_path / "cache" / "mapping" / "map", SpaceStatus("ready", 2, trained=12))
    snapshot = read_snapshot("map", ViewParams())
    assert snapshot.placed == 0
    assert snapshot.result is not None and len(snapshot.result.paths) == 12 and not snapshot.result.unset.any()


def test_quick_train_shows_a_sample_without_saving_and_reuses_it(widget, database, monkeypatch, qtbot):
    w, saved, resets = widget
    reads = []
    original = space_panel.read_quick_train_sample
    monkeypatch.setattr(space_panel, "read_quick_train_sample", lambda *args: reads.append(args) or original(*args))
    w.db_name = "map"
    w.apply_preset(Preset([FeatureSpec("wd14.tags", "token_set")], TrainParams(), 1))
    w.quick_size.setValue(100)
    w.toggle_quick_train()
    assert w.quick_button.text() == "Cancel"
    qtbot.waitUntil(lambda: w.showing_quick, timeout=30000)
    assert len(w.map_view.paths) == 12 and "not saved" in w.count_label.text()
    assert w.quick_button.text() == "Quick Train" and not saved and not resets
    w.tuning.controls["neighbors"].setValue(0.5)
    w.showing_quick = False
    w.toggle_quick_train()
    qtbot.waitUntil(lambda: w.showing_quick, timeout=30000)
    assert len(reads) == 1
    w.on_status(SpaceSnapshot(w.saved, SpaceStatus("ready", 9), placed=1))
    assert w.showing_quick
    w.show_space()
    assert not w.showing_quick


def test_cancelling_quick_train_keeps_the_space_preview(widget, monkeypatch, qtbot):
    w, _saved, _resets = widget
    release = threading.Event()
    runs = []

    def recording_fit(preset, values, *, cancelled, progress):
        runs.append(cancelled())
        raise MapError("Cancelled")

    monkeypatch.setattr(space_panel.SpaceModel, "fit", recording_fit)
    sample = space_panel.QuickTrainSample("db1", 100, frozenset(), [], {}, {})
    started = threading.Event()
    monkeypatch.setattr(space_panel, "read_quick_train_sample", lambda *args: started.set() or (release.wait(10) and sample))
    w.toggle_quick_train()
    assert w.quick_running
    qtbot.waitUntil(started.is_set, timeout=5000)
    w.toggle_quick_train()
    assert not w.quick_running and w.quick_button.text() == "Quick Train" and w.count_label.text() == "Cancelled"
    release.set()
    qtbot.waitUntil(lambda: runs == [True], timeout=5000)
    qtbot.wait(50)
    assert not w.showing_quick and w.quick_sample is None and w.count_label.text() == "Cancelled"


def test_quick_train_size_is_kept_in_the_panel_state(widget):
    w, _saved, _resets = widget
    w.quick_size.setValue(8000)
    state = w.save_state()
    w.quick_size.setValue(space_panel.QUICK_TRAIN_FILES)
    w.restore_state(state)
    assert w.quick_size.value() == 8000


def test_label_and_outlier_changes_relayout_the_shown_sample(widget, qtbot, monkeypatch):
    from extensions.mapping.session import SpaceLayout
    from wafer.core.db.path_values import PathValue

    w, _saved, _resets = widget
    values = {
        f"c:/{i}.png": {
            "tags": PathValue("cat" if i < 6 else "dog"),
            "mapping.2d": PathValue(coordinate_text([float(i), 0.0])),
            "mapping.group": PathValue(coordinate_text([float(i)] + [0.0] * (GROUPING_DIMS - 1))),
            "mapping.model": PathValue("1", 1.0),
        }
        for i in range(12)
    }
    w.preview_layout = SpaceLayout(list(values), values, w.saved)
    monkeypatch.setattr(space_panel, "read_snapshot", lambda *args: pytest.fail("a view change must not read a new sample"))
    ViewSettings.instance().set_params(ViewParams(label_terms=1))
    qtbot.waitUntil(lambda: w.shown is not None, timeout=5000)
    assert w.shown.paths == list(values) and "12 files" in w.count_label.text()


def test_preview_is_shown_before_its_groups(qtbot, database, monkeypatch):
    shown = []
    original = MappingSpaceWidget.show_preview
    monkeypatch.setattr(MappingSpaceWidget, "show_preview", lambda self, result, sources, caption: shown.append(result.labels is None) or original(self, result, sources, caption))
    w = MappingSpaceWidget()
    qtbot.addWidget(w)
    w.db_name = "map"
    w.refresh()
    qtbot.waitUntil(lambda: len(shown) >= 2, timeout=20000)
    assert shown[:2] == [True, False] and w.shown.labels is not None
    w.close()


def test_grouping_changes_regroup_the_quick_train_view(widget, database, qtbot):
    w, _saved, _resets = widget
    w.db_name = "map"
    w.apply_preset(Preset([FeatureSpec("wd14.tags", "token_set")], TrainParams(), 1))
    w.quick_size.setValue(100)
    w.toggle_quick_train()
    qtbot.waitUntil(lambda: w.showing_quick and not w.quick_running, timeout=30000)
    previous = w.shown
    from extensions.mapping.view_settings import GroupingStore

    GroupingStore.instance().set("map", Grouping(size=0.25))
    qtbot.waitUntil(lambda: w.shown is not previous, timeout=30000)
    assert w.showing_quick and (Grouping(size=0.25), 1.0) in w.quick_layout.labels_by_options
    assert w.shown.paths == previous.paths


def test_mapping_only_group_size_does_not_regroup_the_preview(widget, monkeypatch):
    w, _saved, _resets = widget
    regroups = []
    monkeypatch.setattr(MappingSpaceWidget, "regroup", lambda self: regroups.append(1))
    settings = ViewSettings.instance()
    settings.set_params(ViewParams(subgroup_size=0.5))
    settings.set_params(ViewParams(subgroup_size=0.5, point_size=6))
    assert regroups == [] and w.map_view.point_base == 6
    settings.set_params(ViewParams(subgroup_size=0.5, point_size=6, outlier_percent=5.0))
    assert regroups == [1]


def test_snapshot_samples_at_most_the_given_number_of_files(database):
    snapshot = read_snapshot("map", ViewParams(), size=4)
    assert len(snapshot.result.paths) == 4


def test_whole_map_size_is_kept_and_changing_it_resamples(widget, monkeypatch, qtbot):
    w, _saved, _resets = widget
    refreshes = []
    monkeypatch.setattr(MappingSpaceWidget, "refresh", lambda self: refreshes.append(self.preview_size.value()))
    w.preview_size.setValue(8000)
    qtbot.waitUntil(lambda: refreshes == [8000], timeout=2000)
    state = w.save_state()
    w.preview_size.setValue(space_panel.PREVIEW_FILES)
    w.restore_state(state)
    assert w.preview_size.value() == 8000 and (w.preview_size.minimum(), w.preview_size.maximum()) == space_panel.PREVIEW_RANGE


def test_there_is_no_mapping_space_panel_anymore():
    assert not hasattr(space_panel, "MappingSpacePlugin")

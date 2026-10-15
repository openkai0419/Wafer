from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from PySide6 import QtCore

from extensions.mapping import commands, projection
from extensions.mapping import map_host as map_host_module
from extensions.mapping import map_view as map_view_module
from extensions.mapping import widget as widget_module
from extensions.mapping.params import MapParams
from extensions.mapping.session import FeatureSpec, MapPipeline
from extensions.mapping.space import Preset
from extensions.mapping.widget import MappingWidget
from wafer.core.db.path_values import PathValue


def fake_embed(matrix, n_components, n_neighbors, min_dist, seed):
    output = np.zeros((matrix.shape[0], n_components), dtype=np.float32)
    width = min(n_components, matrix.shape[1])
    output[:, :width] = matrix[:, :width] + np.random.default_rng(0).normal(0, 1e-3, (matrix.shape[0], width))
    return output


FIRST_RUN_TIMEOUT = 20000


class DropEvent:
    def __init__(self, mime):
        self.mime = mime
        self.accepted = None

    def mimeData(self):
        return self.mime

    def setDropAction(self, action):
        pass

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


@pytest.fixture(autouse=True)
def no_preset(monkeypatch):
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: None)


@pytest.fixture(autouse=True)
def deterministic_groups(fake_cluster):
    return None


@pytest.fixture()
def mapping(qtbot, monkeypatch):
    monkeypatch.setattr(projection, "embed", fake_embed)
    paths = [f"c:/{i}.png" for i in range(30)]
    values = {p: {"tags": PathValue("cat, sky" if i < 15 else "dog, sea")} for i, p in enumerate(paths)}
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {p: values[p] for p in ps if p in values})
    monkeypatch.setattr(widget_module, "fetch_sources", lambda db, ps: {p: p.replace(".png", ".zip") for p in ps})
    w = MappingWidget()
    qtbot.addWidget(w)
    w.resize(900, 600)
    w.show()
    w.restore_state({"features": [FeatureSpec("tags", "token_set").to_dict()]})
    w.set_files(paths, "db")
    qtbot.waitUntil(lambda: w.current_result() is not None, timeout=FIRST_RUN_TIMEOUT)
    yield w
    w.close()


def test_set_files_computes_map(mapping):
    assert len(mapping.current_result().paths) == 30


def test_selection_sync_and_context(mapping, qtbot):
    mapping.map_view.select_rows([0, 1])
    mapping.map_view.selection_changed.emit()
    assert mapping.file_list.selected_rows() == [0, 1]
    context = mapping.context_for_selection()
    assert context["paths"] == ["c:/0.png", "c:/1.png"]
    assert context["sources"] == ["c:/0.zip", "c:/1.zip"]


def test_list_selection_updates_map(mapping):
    mapping.file_list.select_rows([2, 5])
    mapping.file_list.selection_changed.emit()
    assert mapping.map_view.selected_rows() == [2, 5]
    assert mapping.selected_paths() == ["c:/2.png", "c:/5.png"]


def test_selection_survives_recompute(mapping, qtbot):
    mapping.map_view.select_rows([3, 4])
    mapping.map_view.selection_changed.emit()
    previous = mapping.current_result()
    mapping.recompute()
    qtbot.waitUntil(lambda: mapping.current_result() is not previous, timeout=5000)
    assert mapping.selected_paths() == ["c:/3.png", "c:/4.png"]


def test_stale_result_is_not_applied(mapping, qtbot):
    first = mapping.current_result()
    with patch.object(MappingWidget, "_apply_result", wraps=mapping._apply_result) as apply:
        mapping.recompute()
        mapping.recompute()
        qtbot.waitUntil(lambda: mapping.current_result() is not first, timeout=5000)
        qtbot.wait(200)
    assert apply.call_count == 1


def test_drill_down_and_back(mapping, qtbot):
    mapping.map_view.select_rows(range(10))
    mapping.map_view.selection_changed.emit()
    root = mapping.current_result()
    mapping.drill_down()
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 10, timeout=5000)
    mapping.drill_up()
    assert mapping.current_result() is root
    assert len(mapping.levels) == 1


def test_drill_down_needs_three(mapping):
    mapping.map_view.select_rows([0])
    mapping.drill_down()
    assert len(mapping.current_result().paths) == 30
    assert mapping.message_text() == "Select at least 3 files."


def test_remove_files(mapping, qtbot):
    mapping.remove_files(["c:/0.png"])
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 29, timeout=5000)


def test_remove_unknown_files_is_a_noop(mapping, qtbot):
    result = mapping.current_result()
    pipeline = mapping.levels[0].pipeline
    mapping.remove_files(["c:/unknown.png"])
    qtbot.wait(100)
    assert mapping.current_result() is result
    assert mapping.levels[0].pipeline is pipeline


def test_remove_keeps_results_of_untouched_levels(mapping, qtbot):
    mapping.map_view.select_rows(range(10))
    mapping.map_view.selection_changed.emit()
    mapping.drill_down()
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 10, timeout=5000)
    sub = mapping.current_result()
    mapping.remove_files(["c:/25.png"])
    qtbot.wait(100)
    assert mapping.current_result() is sub
    assert mapping.levels[0].result is None
    assert len(mapping.levels[0].paths) == 29


def test_remove_all_files_returns_to_empty_state(mapping):
    mapping.remove_files(list(mapping.paths))
    assert mapping.stack.currentIndex() == 0
    assert mapping.current_result() is None


def test_drill_down_before_values_loaded_is_ignored(qtbot):
    w = MappingWidget()
    qtbot.addWidget(w)
    w.drill_down()
    assert w.levels == []
    w.close()


def test_fetch_failure_shows_error(qtbot, monkeypatch):
    def fail(db, ps):
        raise OSError("boom")

    errors = []
    monkeypatch.setattr(widget_module, "fetch_path_values", fail)
    monkeypatch.setattr(widget_module.AppLogger, "error", lambda *args, **kwargs: errors.append(args))
    w = MappingWidget()
    qtbot.addWidget(w)
    w.set_files(["a", "b", "c"], "db")
    qtbot.waitUntil(lambda: w.message_text() == "Mapping failed. See the log for details.", timeout=5000)
    assert errors
    w.close()


def without_labels(mapping, qtbot):
    mapping.set_labels_shown(False)
    return mapping.map_view


def clickable_point(view):
    for row, (x, y) in enumerate(view.positions):
        pos = view.mapFromScene(QtCore.QPointF(x, y))
        hit = view.row_at(pos)
        if hit is not None and view.viewport().rect().contains(pos):
            return pos, hit
    raise AssertionError("no clickable point")


def test_right_click_on_selected_point_keeps_selection(mapping, qtbot):
    view = without_labels(mapping, qtbot)
    pos, hit = clickable_point(view)
    other = (hit + 1) % 30
    view.select_rows([hit, other])
    view.selection_changed.emit()
    expected = mapping.selected_paths()
    qtbot.mouseClick(view.viewport(), QtCore.Qt.RightButton, pos=pos)
    assert mapping.context_for_selection()["paths"] == expected
    assert len(expected) == 2


def test_right_click_on_unselected_point_selects_only_it(mapping, qtbot):
    view = without_labels(mapping, qtbot)
    pos, hit = clickable_point(view)
    view.select_rows([(hit + 1) % 30])
    view.selection_changed.emit()
    qtbot.mouseClick(view.viewport(), QtCore.Qt.RightButton, pos=pos)
    assert mapping.context_for_selection()["paths"] == [f"c:/{hit}.png"]
    assert mapping.file_list.selected_rows() == [hit]


def test_state_roundtrip(mapping):
    state = mapping.save_state()
    assert state["features"][0]["key"] == "tags"
    assert "params" in state and state["labels"] is True


def test_restore_state_applies_labels(mapping):
    state = mapping.save_state()
    state["labels"] = False
    mapping.restore_state(state)
    assert mapping.labels_shown is False
    assert not mapping.label_check.isChecked()
    assert mapping.map_view.label_items() and not any(label.isVisible() for label in mapping.map_view.label_items())


def test_label_checkbox_hides_labels_without_recomputing(mapping):
    previous = mapping.current_result()
    mapping.label_check.setChecked(False)
    assert mapping.labels_shown is False and mapping.current_result() is previous
    assert not any(label.isVisible() for label in mapping.map_view.label_items())
    assert mapping.current_result().labels is not None


def test_no_features_shows_message(qtbot, monkeypatch):
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {})
    monkeypatch.setattr(widget_module, "fetch_sources", lambda db, ps: {})
    w = MappingWidget()
    qtbot.addWidget(w)
    w.set_files(["a", "b", "c"], "db")
    qtbot.waitUntil(lambda: w.message_text() == "Add a key to start.", timeout=5000)
    w.close()


def test_cancel_button_stops_computation(mapping, qtbot):
    mapping.recompute()
    assert mapping.cancel_button.isVisible()
    mapping.cancel_button.click()
    assert not mapping.cancel_button.isVisible()
    assert mapping.message_text() == "Cancelled"


def test_drop_adds_files(mapping, tmp_path):
    dropped = tmp_path / "new.png"
    dropped.write_bytes(b"x")
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(dropped))])
    enter = DropEvent(mime)
    mapping.handle_drag_enter(enter)
    assert enter.accepted is True
    drop = DropEvent(mime)
    with patch.object(MappingWidget, "add_files") as add:
        mapping.handle_drop(drop)
    assert drop.accepted is True
    add.assert_called_once_with([widget_module.normalize_path(str(dropped))], "db")


def test_drop_without_files_is_ignored(mapping):
    event = DropEvent(QtCore.QMimeData())
    mapping.handle_drag_enter(event)
    assert event.accepted is False


def test_thumbnail_bucket_uses_the_logical_size(mapping, monkeypatch):
    monkeypatch.setattr(map_view_module, "dpix", lambda value: value * 2)
    mapping.set_image_scale(1.5)
    view = mapping.map_view
    view.set_thumbnail_zoom(view.zoom)
    assert view.display_size() == pytest.approx(map_view_module.THUMB_SIZE * 1.5)
    view.viewport().repaint()
    assert mapping.host.thumbs.size == 128
    assert mapping.host.thumbs.cache_limit == map_host_module.cache_limit(map_host_module.THUMB_BUDGET, 128)


def test_hiding_the_panel_hides_the_hover(mapping):
    mapping.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert mapping.host.preview.isVisible()
    mapping.hide()
    assert not mapping.host.preview.isVisible()


def test_smallest_thumbnail_bucket_matches_map_view():
    assert map_host_module.THUMB_BUCKETS[0] == map_view_module.THUMB_SIZE


def test_image_scale_resizes_thumbnails_and_persists(mapping):
    mapping.set_image_scale(2.0)
    assert mapping.map_view.image_scale == 2.0
    state = mapping.save_state()
    assert state["image_scale"] == 2.0
    mapping.set_image_scale(1.0)
    mapping.restore_state(state)
    assert mapping.map_view.image_scale == 2.0


def test_image_scale_up_and_down_use_ratio(mapping):
    mapping.image_scale_up(2.0)
    assert mapping.map_view.image_scale == 2.0
    mapping.image_scale_down(4.0)
    assert mapping.map_view.image_scale == 0.5
    mapping.image_scale_down(1000.0)
    assert mapping.map_view.image_scale == map_view_module.MIN_IMAGE_SCALE


@pytest.mark.parametrize("bad", ["x", None, float("nan"), float("inf")])
def test_restore_state_ignores_bad_image_scale(mapping, bad):
    mapping.restore_state({"image_scale": bad, "selection_mode": "weird"})
    assert mapping.map_view.image_scale == 1.0
    assert mapping.selection_mode == "single"


def test_restore_state_clamps_image_scale(mapping):
    mapping.restore_state({"image_scale": 99})
    assert mapping.map_view.image_scale == map_view_module.MAX_IMAGE_SCALE


def test_selection_mode_syncs_toolbar_and_persists(mapping):
    mapping.set_selection_mode("group")
    assert mapping.selection_mode == "group" and mapping.mode_buttons["group"].isChecked()
    state = mapping.save_state()
    assert state["selection_mode"] == "group"
    mapping.mode_buttons["single"].click()
    assert mapping.selection_mode == "single"
    mapping.restore_state(state)
    assert mapping.selection_mode == "group" and mapping.mode_buttons["group"].isChecked()


def test_group_selection_is_always_available(mapping):
    mapping.set_labels_shown(False)
    assert mapping.mode_buttons["group"].isEnabled()


def test_list_selection_expands_to_whole_group(mapping):
    labels = mapping.current_result().labels
    row = int(np.flatnonzero(labels >= 0)[0])
    members = np.flatnonzero(labels == labels[row]).tolist()
    assert len(members) > 1
    mapping.set_selection_mode("group")
    mapping.file_list.select_rows([row])
    mapping.file_list.selection_changed.emit()
    assert mapping.map_view.selected_rows() == members
    assert mapping.file_list.selected_rows() == members


def test_list_selection_stays_single_in_single_mode(mapping):
    labels = mapping.current_result().labels
    row = int(np.flatnonzero(labels >= 0)[0])
    mapping.file_list.select_rows([row])
    mapping.file_list.selection_changed.emit()
    assert mapping.file_list.selected_rows() == [row]


def test_hover_goes_through_host(mapping):
    mapping.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert mapping.host.preview.isVisible()
    mapping.hide_hover()
    assert not mapping.host.preview.isVisible()


def test_hover_size_param_reaches_host(mapping):
    mapping.on_params(MapParams(hover_size=0))
    assert mapping.host.hover_size == 0
    mapping.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert not mapping.host.preview.isVisible()


def test_sources_live_in_host(mapping):
    assert mapping.host.sources["c:/0.png"] == "c:/0.zip"
    mapping.reset()
    assert mapping.host.sources == {}


def test_computation_outranks_thumbnail_requests(mapping):
    with patch.object(mapping.dispatcher, "post") as post:
        mapping.recompute()
        mapping.fetch()
    assert [call.kwargs["priority"] for call in post.call_args_list] == [widget_module.COMPUTE_PRIORITY] * 2
    assert widget_module.COMPUTE_PRIORITY > 5


SPACE_UNSET = ("c:/27.png", "c:/28.png", "c:/29.png")


def make_space_widget(qtbot, monkeypatch, version=2):
    monkeypatch.setattr(projection, "embed", fake_embed)
    paths = [f"c:/{i}.png" for i in range(30)]
    values = {}
    for i, p in enumerate(paths):
        entry = {"tags": PathValue("cat, sky" if i < 15 else "dog, sea"), "prompt": PathValue("a cat" if i < 15 else "a dog")}
        if p not in SPACE_UNSET:
            x = float(i // 15) * 10 + i * 0.01
            entry.update({"mapping.x": PathValue(str(x), x), "mapping.y": PathValue("0", 0.0), "mapping.model": PathValue("2", 2.0)})
        values[p] = entry
    preset = Preset([FeatureSpec("tags", "token_set")], MapParams(), version)
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {p: values[p] for p in ps if p in values})
    monkeypatch.setattr(widget_module, "fetch_sources", lambda db, ps: {p: p for p in ps})
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: preset)
    w = MappingWidget()
    qtbot.addWidget(w)
    w.resize(900, 600)
    w.show()
    w.restore_state({"features": [FeatureSpec("tags", "token_set").to_dict()]})
    w.set_files(paths, "db")
    return w


@pytest.fixture()
def space_widget(qtbot, monkeypatch):
    w = make_space_widget(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: w.current_result() is not None, timeout=FIRST_RUN_TIMEOUT)
    yield w
    w.close()


def test_precomputed_mode_places_files_and_counts_waiting(space_widget):
    result = space_widget.current_result()
    assert space_widget.effective_mode() == "space" and space_widget.levels[0].mode == "space"
    assert [result.paths[row] for row in np.flatnonzero(result.unset)] == list(SPACE_UNSET)
    assert result.diagnostics.unset == 3
    assert "3 waiting for placement" in space_widget.message_text()
    assert space_widget.db_name == "db"


def test_precomputed_mode_shows_read_only_preset_keys(space_widget):
    assert space_widget.feature_bar.read_only
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags"]
    assert not space_widget.feature_bar.add_button.isEnabled()
    assert space_widget.edit_space_button.isVisibleTo(space_widget)
    assert space_widget.precomputed_button.isEnabled() and space_widget.precomputed_button.isChecked()


def test_precomputed_mode_skips_the_pipeline(qtbot, monkeypatch):
    with patch.object(MapPipeline, "run") as run:
        w = make_space_widget(qtbot, monkeypatch)
        qtbot.waitUntil(lambda: w.current_result() is not None, timeout=FIRST_RUN_TIMEOUT)
        w.close()
    run.assert_not_called()


def test_no_preset_pins_live_mode(mapping):
    assert mapping.effective_mode() == "live"
    assert not mapping.precomputed_button.isEnabled()
    assert mapping.levels[0].mode == "live"
    assert not mapping.feature_bar.read_only and not mapping.edit_space_button.isVisibleTo(mapping)


def test_preset_without_a_trained_version_pins_live_mode(qtbot, monkeypatch):
    w = make_space_widget(qtbot, monkeypatch, version=0)
    qtbot.waitUntil(lambda: w.current_result() is not None, timeout=FIRST_RUN_TIMEOUT)
    assert w.effective_mode() == "live" and not w.precomputed_button.isEnabled()
    assert w.space_mode == "space"
    w.close()


def test_set_space_mode_switches_between_space_and_live(space_widget, qtbot):
    space_widget.set_space_mode("live")
    qtbot.waitUntil(lambda: space_widget.levels[0].mode == "live" and space_widget.current_result() is not None, timeout=5000)
    assert space_widget.space_buttons["live"].isChecked() and not space_widget.feature_bar.read_only
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags"]
    assert space_widget.current_result().diagnostics.unset == 0
    space_widget.space_buttons["space"].click()
    qtbot.waitUntil(lambda: space_widget.levels[0].mode == "space" and space_widget.current_result() is not None, timeout=5000)
    assert space_widget.space_mode == "space" and space_widget.feature_bar.read_only
    assert space_widget.current_result().diagnostics.unset == 3


def test_drill_down_keeps_the_level_mode(space_widget, qtbot):
    space_widget.map_view.select_rows(range(10))
    space_widget.map_view.selection_changed.emit()
    space_widget.drill_down()
    qtbot.waitUntil(lambda: space_widget.current_result() is not None and len(space_widget.current_result().paths) == 10, timeout=5000)
    assert space_widget.levels[-1].mode == "space"


def test_relayout_selection_runs_the_live_pipeline(space_widget, qtbot):
    space_widget.map_view.select_rows(range(10))
    space_widget.map_view.selection_changed.emit()
    with patch.object(MapPipeline, "run", autospec=True, side_effect=MapPipeline.run) as run:
        space_widget.relayout_selection()
        qtbot.waitUntil(lambda: space_widget.current_result() is not None and len(space_widget.current_result().paths) == 10, timeout=5000)
    run.assert_called_once()
    assert space_widget.levels[-1].mode == "live" and space_widget.levels[0].mode == "space"
    assert not space_widget.feature_bar.read_only
    assert not space_widget.edit_space_button.isVisibleTo(space_widget)
    crumbs = [space_widget.crumbs.itemAt(i).widget().text() for i in range(space_widget.crumbs.count())]
    assert any(text.startswith("Selection (live)") for text in crumbs)
    space_widget.drill_up()
    assert space_widget.feature_bar.read_only and space_widget.edit_space_button.isVisibleTo(space_widget)


def test_relayout_selection_needs_three(space_widget):
    space_widget.map_view.select_rows([0])
    space_widget.relayout_selection()
    assert len(space_widget.levels) == 1
    assert space_widget.message_text() == "Select at least 3 files."


def test_space_mode_persists(space_widget):
    space_widget.space_mode = "live"
    state = space_widget.save_state()
    assert state["space_mode"] == "live"
    space_widget.restore_state(state)
    assert space_widget.space_mode == "live" and space_widget.effective_mode() == "live"
    space_widget.restore_state({"space_mode": "weird"})
    assert space_widget.space_mode == "space"


def test_saved_features_are_the_live_features(space_widget):
    assert [feature["key"] for feature in space_widget.save_state()["features"]] == ["tags"]
    space_widget.live_features = [FeatureSpec("prompt", "text", 2.0)]
    assert space_widget.save_state()["features"][0]["weight"] == 2.0


def test_edit_in_space_opens_the_space_panel(space_widget):
    manager = MagicMock()
    manager.panel_names.return_value = ["Mapping", "Mapping Space"]
    space_widget._layout_manager = manager
    space_widget.edit_space_button.click()
    manager.ensure_panel_visible.assert_called_once_with("Mapping Space")


def test_edit_in_space_ignores_a_missing_panel(space_widget):
    manager = MagicMock()
    manager.panel_names.return_value = ["Mapping"]
    space_widget._layout_manager = manager
    space_widget.open_space_panel()
    manager.ensure_panel_visible.assert_not_called()
    del space_widget._layout_manager
    space_widget.open_space_panel()


def test_nothing_placed_shows_the_hint(qtbot, monkeypatch):
    w = make_space_widget(qtbot, monkeypatch)
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {p: {"tags": PathValue("cat")} for p in ps})
    w.set_files([f"c:/{i}.png" for i in range(5)], "db")
    qtbot.waitUntil(lambda: w.message_text().startswith("No files have been placed yet"), timeout=FIRST_RUN_TIMEOUT)
    w.close()


class InstanceCtx(dict):
    def get_instance(self, name, default=None):
        return self.get(f"instance:{name}", default)


def test_preset_keys_follow_the_database(space_widget, qtbot, monkeypatch):
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags"]
    other = Preset([FeatureSpec("prompt", "text")], MapParams(), 2)
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: other)
    previous = space_widget.current_result()
    space_widget.set_files(list(space_widget.paths), "b")
    qtbot.waitUntil(lambda: space_widget.current_result() is not previous and space_widget.current_result() is not None, timeout=5000)
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["prompt"]
    assert space_widget.feature_bar.read_only


def test_retrained_preset_replaces_the_shown_keys(space_widget, qtbot, monkeypatch):
    retrained = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("prompt", "text")], MapParams(), 2)
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: retrained)
    previous = space_widget.current_result()
    space_widget.fetch()
    qtbot.waitUntil(lambda: space_widget.current_result() is not previous and space_widget.current_result() is not None, timeout=5000)
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags", "prompt"]


def test_space_keys_are_not_offered_as_live_keys(space_widget):
    assert not {key for key, _ in space_widget.feature_bar.keys} & {"mapping.x", "mapping.y", "mapping.model"}
    assert ("tags", 30) in space_widget.feature_bar.keys


def test_toggle_without_a_preset_does_nothing(mapping):
    root = mapping.levels[0]
    ctx = InstanceCtx(**{"instance:MappingWidget": mapping})
    with patch.object(MappingWidget, "recompute") as recompute:
        commands.toggle_space_mode(ctx)
        commands.toggle_space_mode(ctx)
    recompute.assert_not_called()
    assert mapping.space_mode == "space" and mapping.effective_mode() == "live"
    assert mapping.levels[0] is root


def test_relayout_from_a_space_level_seeds_live_keys_from_the_preset(space_widget, qtbot):
    space_widget.live_features = []
    space_widget.map_view.select_rows(range(10))
    space_widget.map_view.selection_changed.emit()
    with patch.object(MapPipeline, "run", autospec=True, side_effect=MapPipeline.run) as run:
        space_widget.relayout_selection()
        qtbot.waitUntil(lambda: space_widget.current_result() is not None and len(space_widget.current_result().paths) == 10, timeout=5000)
    run.assert_called_once()
    assert space_widget.live_features == space_widget.preset.features
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags"]
    assert not space_widget.feature_bar.read_only


def test_refresh_in_precomputed_mode_refetches_and_keeps_the_level(space_widget, qtbot, monkeypatch):
    space_widget.map_view.select_rows(range(10))
    space_widget.map_view.selection_changed.emit()
    space_widget.drill_down()
    qtbot.waitUntil(lambda: space_widget.current_result() is not None and len(space_widget.current_result().paths) == 10, timeout=5000)
    drilled = list(space_widget.levels[-1].paths)
    retrained = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("prompt", "text")], MapParams(), 2)
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: retrained)
    previous = space_widget.current_result()
    space_widget.refresh()
    qtbot.waitUntil(lambda: space_widget.current_result() is not previous and space_widget.current_result() is not None, timeout=5000)
    assert len(space_widget.levels) == 2 and space_widget.levels[-1].paths == drilled
    assert space_widget.current_result().paths == drilled
    assert space_widget.preset is retrained
    assert [chip.key for chip in space_widget.feature_bar.chips()] == ["tags", "prompt"]


def test_refresh_in_live_mode_only_recomputes(mapping):
    with patch.object(MappingWidget, "fetch") as fetch, patch.object(MappingWidget, "recompute") as recompute:
        mapping.refresh()
    fetch.assert_not_called()
    recompute.assert_called_once()


def test_recompute_command_refreshes(space_widget):
    ctx = InstanceCtx(**{"instance:MappingWidget": space_widget})
    with patch.object(MappingWidget, "fetch") as fetch:
        commands.recompute(ctx)
    fetch.assert_called_once_with(keep_levels=True)

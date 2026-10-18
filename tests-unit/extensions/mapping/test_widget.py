from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from PySide6 import QtCore

from extensions.mapping import commands
from extensions.mapping import map_host as map_host_module
from extensions.mapping import map_view as map_view_module
from extensions.mapping import widget as widget_module
from extensions.mapping.params import Grouping, TrainParams, ViewParams, param_specs
from extensions.mapping.projection import GROUPING_DIMS
from extensions.mapping.session import FeatureSpec, grouping_text
from extensions.mapping.space import Preset
from extensions.mapping.view_settings import ViewSettings
from extensions.mapping.widget import MappingWidget
from wafer.core.db.path_values import PathValue
from wafer.qt.commands.binding.instance_registry import InstanceRegistry

FIRST_RUN_TIMEOUT = 20000
PATHS = [f"c:/{i}.png" for i in range(30)]
UNSET = ("c:/27.png", "c:/28.png", "c:/29.png")


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


def settings() -> ViewSettings:
    return ViewSettings.instance()


class InstanceCtx(dict):
    def get_instance(self, name, default=None):
        return self.get(f"instance:{name}", default)


def space_values() -> dict:
    values = {}
    for i, path in enumerate(PATHS):
        entry = {"tags": PathValue("cat, sky" if i < 15 else "dog, sea")}
        if path not in UNSET:
            x = float(i // 15) * 10 + i * 0.01
            entry.update(
                {
                    "mapping.x": PathValue(str(x), x),
                    "mapping.y": PathValue("0", 0.0),
                    "mapping.group": PathValue(grouping_text([x] + [0.0] * (GROUPING_DIMS - 1))),
                    "mapping.model": PathValue("2", 2.0),
                }
            )
        values[path] = entry
    return values


@pytest.fixture(autouse=True)
def deterministic_groups(fake_cluster):
    return None


@pytest.fixture()
def space_data(monkeypatch):
    values = space_values()
    state = SimpleNamespace(preset=Preset([FeatureSpec("tags", "token_set")], TrainParams(), 2), values=values, groups=None)
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {p: state.values[p] for p in ps if p in state.values})
    monkeypatch.setattr(widget_module, "fetch_sources", lambda db, ps: {p: p.replace(".png", ".zip") for p in ps})
    monkeypatch.setattr(widget_module, "load_preset", lambda db_name: state.preset)
    monkeypatch.setattr(widget_module, "space_groups", lambda db_path, preset: state.groups)
    return state


def open_widget(qtbot, paths=PATHS, wait=True):
    w = MappingWidget()
    qtbot.addWidget(w)
    w.resize(900, 600)
    w.show()
    w.set_files(list(paths), "db")
    if wait:
        qtbot.waitUntil(lambda: w.current_result() is not None, timeout=FIRST_RUN_TIMEOUT)
    return w


@pytest.fixture()
def mapping(qtbot, space_data):
    w = open_widget(qtbot)
    yield w
    w.close()


def wait_for_new_result(qtbot, widget, previous):
    qtbot.waitUntil(lambda: widget.current_result() is not None and widget.current_result() is not previous, timeout=5000)


def test_set_files_places_files_from_the_space(mapping):
    result = mapping.current_result()
    assert len(result.paths) == 30
    assert [result.paths[row] for row in np.flatnonzero(result.unset)] == list(UNSET)
    assert "3 waiting for placement" in mapping.message_text()
    assert mapping.db_name == "db"


def test_only_view_settings_and_no_keys_are_shown(mapping):
    view_params = {name for name, _spec, _default in param_specs(ViewParams)}
    assert set(mapping.toolbar.tuning.controls) == view_params - {"subgroup_size"}
    assert set(mapping.toolbar.sliders) == {"subgroup_size"} and mapping.toolbar.fine_check is None
    assert not hasattr(mapping, "feature_bar")
    assert mapping.edit_space_button.isVisibleTo(mapping)


@pytest.mark.parametrize("preset", [None, Preset([FeatureSpec("tags", "token_set")], TrainParams(), 0)])
def test_without_a_trained_space_it_points_to_mapping_space(qtbot, space_data, preset):
    space_data.preset = preset
    w = open_widget(qtbot, wait=False)
    qtbot.waitUntil(lambda: w.message_text().startswith("This database has no Mapping Space yet"), timeout=5000)
    assert w.current_result() is None and w.edit_space_button.isVisibleTo(w)
    w.close()


def test_nothing_placed_shows_the_hint(qtbot, space_data):
    space_data.values = {p: {"tags": PathValue("cat")} for p in PATHS}
    w = open_widget(qtbot, wait=False)
    qtbot.waitUntil(lambda: w.message_text().startswith("No files have been placed yet"), timeout=FIRST_RUN_TIMEOUT)
    w.close()


def test_edit_in_space_opens_the_space_panel(mapping):
    with patch.object(widget_module, "open_panel") as open_panel:
        mapping.edit_space_button.click()
    open_panel.assert_called_once_with(name="Mapping Space", toggle=False)


def test_selection_sync_and_context(mapping):
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
    wait_for_new_result(qtbot, mapping, previous)
    assert mapping.selected_paths() == ["c:/3.png", "c:/4.png"]


def test_stale_result_is_not_applied(mapping, qtbot):
    first = mapping.current_result()
    with patch.object(MappingWidget, "_apply_result", wraps=mapping._apply_result) as apply:
        mapping.recompute()
        mapping.recompute()
        wait_for_new_result(qtbot, mapping, first)
        qtbot.wait(200)
    assert apply.call_count == 1


def drill(mapping, qtbot, rows):
    mapping.map_view.select_rows(rows)
    mapping.map_view.selection_changed.emit()
    mapping.drill_down()
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == len(rows), timeout=5000)


def test_drill_down_and_back(mapping, qtbot):
    root = mapping.current_result()
    drill(mapping, qtbot, range(10))
    crumbs = [mapping.crumbs.itemAt(i).widget().text() for i in range(mapping.crumbs.count())]
    assert any(text.startswith("Selection") for text in crumbs)
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
    result, level = mapping.current_result(), mapping.levels[0]
    mapping.remove_files(["c:/unknown.png"])
    qtbot.wait(100)
    assert mapping.current_result() is result and mapping.levels[0] is level


def test_remove_keeps_results_of_untouched_levels(mapping, qtbot):
    drill(mapping, qtbot, range(10))
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


def clickable_point(view):
    for row, (x, y) in enumerate(view.positions):
        pos = view.mapFromScene(QtCore.QPointF(x, y))
        hit = view.row_at(pos)
        if hit is not None and view.viewport().rect().contains(pos):
            return pos, hit
    raise AssertionError("no clickable point")


def test_right_click_on_selected_point_keeps_selection(mapping, qtbot):
    settings().set_labels_shown(False)
    view = mapping.map_view
    pos, hit = clickable_point(view)
    view.select_rows([hit, (hit + 1) % 27])
    view.selection_changed.emit()
    expected = mapping.selected_paths()
    qtbot.mouseClick(view.viewport(), QtCore.Qt.RightButton, pos=pos)
    assert mapping.context_for_selection()["paths"] == expected
    assert len(expected) == 2


def test_right_click_on_unselected_point_selects_only_it(mapping, qtbot):
    settings().set_labels_shown(False)
    view = mapping.map_view
    pos, hit = clickable_point(view)
    view.select_rows([(hit + 1) % 27])
    view.selection_changed.emit()
    qtbot.mouseClick(view.viewport(), QtCore.Qt.RightButton, pos=pos)
    assert mapping.context_for_selection()["paths"] == [f"c:/{hit}.png"]
    assert mapping.file_list.selected_rows() == [hit]


def test_label_checkbox_hides_labels_without_recomputing(mapping):
    previous = mapping.current_result()
    mapping.toolbar.label_check.setChecked(False)
    assert settings().labels_shown is False
    mapping.toolbar.thumbnail_check.setChecked(False)
    assert settings().thumbnails_shown is False and not mapping.map_view.thumbnails and mapping.current_result() is previous
    assert not any(label.isVisible() for label in mapping.map_view.label_items())
    assert mapping.current_result().labels is not None


def test_cancel_button_stops_computation(mapping):
    mapping.recompute()
    assert mapping.cancel_button.isVisible()
    mapping.cancel_button.click()
    assert not mapping.cancel_button.isVisible()
    assert mapping.message_text() == "Cancelled"


def dropped_file(tmp_path):
    dropped = tmp_path / "new.png"
    dropped.write_bytes(b"x")
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(dropped))])
    return dropped, mime


def test_drop_adds_files(mapping, tmp_path):
    dropped, mime = dropped_file(tmp_path)
    enter = DropEvent(mime)
    mapping.handle_drag_enter(enter)
    assert enter.accepted is True
    drop = DropEvent(mime)
    with patch.object(MappingWidget, "add_files") as add:
        mapping.handle_drop(drop)
    assert drop.accepted is True
    add.assert_called_once_with([widget_module.normalize_path(str(dropped))], "db")


def test_drop_on_a_floating_panel_uses_the_main_window_database(qtbot, tmp_path, monkeypatch):
    dropped, mime = dropped_file(tmp_path)
    monkeypatch.setattr(InstanceRegistry, "get_host_window", lambda self: SimpleNamespace(database_path="main.db"))
    w = MappingWidget()
    qtbot.addWidget(w)
    drop = DropEvent(mime)
    with patch.object(MappingWidget, "add_files") as add:
        w.handle_drop(drop)
    assert drop.accepted is True
    add.assert_called_once_with([widget_module.normalize_path(str(dropped))], "main.db")
    w.close()


def test_drop_without_files_is_ignored(mapping):
    event = DropEvent(QtCore.QMimeData())
    mapping.handle_drag_enter(event)
    assert event.accepted is False


def test_thumbnail_bucket_uses_the_logical_size(mapping, monkeypatch):
    monkeypatch.setattr(map_view_module, "dpix", lambda value: value * 2)
    settings().set_image_scale(3.0)
    view = mapping.map_view
    assert view.display_size() == pytest.approx(map_view_module.FIT_IMAGE_SIZE * 3.0)
    view.viewport().repaint()
    assert mapping.host.thumbs.size == 128
    assert mapping.host.thumbs.cache_limit == map_host_module.cache_limit(map_host_module.THUMB_BUDGET, 128)


def test_smallest_thumbnail_bucket_matches_map_view():
    assert map_host_module.THUMB_BUCKETS[0] == map_view_module.THUMB_SIZE


def test_point_size_comes_from_the_settings_without_relayout(mapping):
    assert mapping.map_view.point_base == ViewParams().point_size == 3.0
    previous = mapping.current_result()
    settings().set_params(ViewParams(point_size=6))
    assert mapping.map_view.point_base == 6 and mapping.current_result() is previous
    settings().set_image_scale(3.0)
    assert mapping.map_view.point_base == 6


def test_relayout_settings_recompute_the_map(mapping, qtbot):
    previous = mapping.current_result()
    settings().set_params(ViewParams(outlier_percent=5.0))
    wait_for_new_result(qtbot, mapping, previous)


def test_group_selection_is_always_available(mapping):
    settings().set_labels_shown(False)
    assert mapping.toolbar.mode_buttons["group"].isEnabled()


def test_list_selection_expands_to_whole_group(mapping):
    labels = mapping.current_result().labels
    row = int(np.flatnonzero(labels >= 0)[0])
    members = np.flatnonzero(labels == labels[row]).tolist()
    assert len(members) > 1
    settings().set_selection_mode("group")
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


def test_hover_goes_through_host_and_hides_with_the_panel(mapping):
    mapping.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    assert mapping.host.preview.isVisible()
    mapping.hide_hover()
    assert not mapping.host.preview.isVisible()
    mapping.show_hover("c:/1.png", QtCore.QPoint(300, 300))
    mapping.hide()
    assert not mapping.host.preview.isVisible()


def test_hover_size_param_reaches_host(mapping):
    settings().set_params(ViewParams(hover_size=0))
    assert mapping.host.hover_size == 0
    assert mapping.map_view.image_cap == ViewParams().hover_size
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


def test_retrained_preset_is_picked_up_on_refresh(mapping, qtbot, space_data):
    drill(mapping, qtbot, range(10))
    drilled = list(mapping.levels[-1].paths)
    retrained = Preset([FeatureSpec("tags", "token_set"), FeatureSpec("prompt", "text")], TrainParams(), 2)
    space_data.preset = retrained
    previous = mapping.current_result()
    mapping.refresh()
    wait_for_new_result(qtbot, mapping, previous)
    assert len(mapping.levels) == 2 and mapping.levels[-1].paths == drilled
    assert mapping.current_result().paths == drilled
    assert mapping.preset is retrained


def test_recompute_command_refreshes(mapping):
    ctx = InstanceCtx(**{"instance:MappingWidget": mapping})
    with patch.object(MappingWidget, "fetch") as fetch:
        commands.recompute(ctx)
    fetch.assert_called_once_with(keep_levels=True)


def test_widget_state_leaves_the_shared_view_settings_to_the_plugin(mapping):
    settings().set_labels_shown(False)
    state = mapping.save_state()
    assert set(state) == {"splitter"}
    mapping.restore_state({**state, "view": {"labels": True}})
    assert not settings().labels_shown


def test_loaded_view_settings_reach_the_map(mapping):
    settings().load({"labels": False, "thumbnails": False, "image_scale": 2.0, "selection_mode": "group"})
    assert not settings().thumbnails_shown and not mapping.map_view.thumbnails and not mapping.toolbar.thumbnail_check.isChecked()
    assert not settings().labels_shown and settings().image_scale == 2.0 and settings().selection_mode == "group"
    assert mapping.map_view.image_scale == 2.0 and mapping.map_view.selection_mode == "group"
    assert mapping.toolbar.mode_buttons["group"].isChecked() and not mapping.toolbar.label_check.isChecked()
    assert mapping.map_view.label_items() and not any(label.isVisible() for label in mapping.map_view.label_items())


@pytest.mark.parametrize("bad", ["x", None, float("nan"), float("inf")])
def test_loading_view_settings_ignores_bad_values(mapping, bad):
    settings().load({"image_scale": bad, "selection_mode": "weird"})
    assert settings().image_scale == 1.0 and settings().selection_mode == "single"


def test_image_scale_is_clamped(mapping):
    settings().set_image_scale(99)
    assert mapping.map_view.image_scale == map_view_module.MAX_IMAGE_SCALE
    settings().set_image_scale(0)
    assert mapping.map_view.image_scale == map_view_module.MIN_IMAGE_SCALE


def test_toolbar_drives_the_shared_settings(mapping):
    mapping.toolbar.mode_buttons["group"].click()
    assert settings().selection_mode == "group" and mapping.map_view.selection_mode == "group"
    mapping.toolbar.label_check.setChecked(False)
    assert settings().labels_shown is False
    mapping.toolbar.thumbnail_check.setChecked(False)
    assert settings().thumbnails_shown is False and not mapping.map_view.thumbnails


def test_view_settings_reach_the_mapping_space_panel(mapping, qtbot):
    from extensions.mapping.space_panel import MappingSpaceWidget

    with patch.object(MappingSpaceWidget, "refresh"):
        space = MappingSpaceWidget()
    qtbot.addWidget(space)
    settings().set_image_scale(3.0)
    settings().set_selection_mode("group")
    assert space.map_view.image_scale == 3.0 == mapping.map_view.image_scale
    assert space.toolbar.mode_buttons["group"].isChecked() and mapping.toolbar.mode_buttons["group"].isChecked()
    assert set(space.toolbar.tuning.controls) == set(mapping.toolbar.tuning.controls)
    space.close()


def test_map_is_shown_before_its_groups(qtbot, space_data, monkeypatch):
    shown = []
    original, regroup = MappingWidget.show_result, MappingWidget.apply_groups
    monkeypatch.setattr(MappingWidget, "show_result", lambda self, result: shown.append(("show", result.labels is None)) or original(self, result))
    monkeypatch.setattr(MappingWidget, "apply_groups", lambda self, result: shown.append(("groups", result.labels is None)) or regroup(self, result))
    w = open_widget(qtbot)
    assert shown[:2] == [("show", True), ("groups", False)]
    assert w.current_result().labels is not None and "groups" in w.message_text()
    w.close()


def test_group_size_slider_regroups_the_map(mapping, qtbot):
    previous = mapping.current_result()
    slider = mapping.toolbar.sliders["subgroup_size"]
    slider.setValue(slider.minimum())
    assert settings().params.subgroup_size == 0.0625 and mapping.toolbar.slider_values["subgroup_size"].text() == "\N{MULTIPLICATION SIGN}0.0625"
    wait_for_new_result(qtbot, mapping, previous)
    assert np.array_equal(mapping.current_result().positions, previous.positions, equal_nan=True)
    slider.setValue(slider.maximum())
    assert settings().params.subgroup_size == 1.0 and mapping.toolbar.slider_values["subgroup_size"].text() == "\N{MULTIPLICATION SIGN}1"


def test_mapping_space_sets_the_base_groups_of_its_database(mapping, qtbot, fresh_grouping_store):
    from extensions.mapping.space_panel import MappingSpaceWidget
    from extensions.mapping.view_settings import GroupingStore

    with patch.object(MappingSpaceWidget, "refresh"):
        space = MappingSpaceWidget()
    qtbot.addWidget(space)
    space.toolbar.set_db("db")
    assert set(space.toolbar.sliders) == {"size", "strictness"} and space.toolbar.fine_check is not None
    previous = mapping.current_result()
    space.toolbar.sliders["size"].setValue(space.toolbar.sliders["size"].minimum())
    space.toolbar.fine_check.setChecked(True)
    assert GroupingStore.instance().get("db") == Grouping(size=0.25, fine=1) == fresh_grouping_store["db"]
    wait_for_new_result(qtbot, mapping, previous)
    assert mapping.toolbar.slider_values["subgroup_size"].text() == "\N{MULTIPLICATION SIGN}1"
    assert space.toolbar.slider_values["size"].text() == "\N{MULTIPLICATION SIGN}0.25"
    space.toolbar.set_db("other")
    assert space.toolbar.slider_values["size"].text() == "\N{MULTIPLICATION SIGN}1" and not space.toolbar.fine_check.isChecked()
    space.close()


def test_base_strictness_change_regroups_the_map(mapping, qtbot):
    from extensions.mapping.view_settings import GroupingStore

    previous = mapping.current_result()
    GroupingStore.instance().set("db", Grouping(strictness=16.0))
    assert "Grouping" in mapping.message_text()
    wait_for_new_result(qtbot, mapping, previous)
    previous = mapping.current_result()
    GroupingStore.instance().set("other", Grouping(strictness=2.0))
    qtbot.wait(200)
    assert mapping.current_result() is previous


def test_group_sliders_step_by_the_same_ratio(mapping):
    from extensions.mapping.map_toolbar import MapToolbar
    from extensions.mapping.view_settings import GroupingStore

    space_toolbar = MapToolbar(edits_space_groups=True)
    space_toolbar.set_db("db")
    cases = (
        (mapping.toolbar, "subgroup_size", lambda: settings().params.subgroup_size, 0.0625, 1.0, {0.125, 0.25, 0.5}),
        (space_toolbar, "size", lambda: GroupingStore.instance().get("db").size, 0.25, 16.0, {0.5, 1.0, 2.0, 4.0, 8.0}),
        (space_toolbar, "strictness", lambda: GroupingStore.instance().get("db").strictness, 0.25, 16.0, {0.5, 1.0, 2.0, 4.0, 8.0}),
    )
    for toolbar, name, current, low, high, stops in cases:
        slider = toolbar.sliders[name]
        factors = []
        for position in range(slider.minimum(), slider.maximum() + 1):
            slider.setValue(position)
            factors.append(current())
        ratios = np.array(factors[1:]) / np.array(factors[:-1])
        assert factors[0] == low and factors[-1] == high and np.allclose(ratios, ratios[0])
        assert stops <= set(factors)


def test_regrouping_swaps_colors_and_labels_and_keeps_the_view(mapping, qtbot, monkeypatch):
    calls = []
    monkeypatch.setattr(MappingWidget, "show_result", lambda self, result: calls.append("show"))
    mapping.map_view.select_rows([0, 2])
    mapping.map_view.scale(2.0, 2.0)
    transform = mapping.map_view.transform()
    previous = mapping.current_result()
    settings().set_params(ViewParams(subgroup_size=0.25))
    assert "Grouping" in mapping.message_text()
    wait_for_new_result(qtbot, mapping, previous)
    assert calls == [] and mapping.map_view.transform() == transform
    assert mapping.map_view.selected_rows() == [0, 2] and "groups" in mapping.message_text()


def test_only_the_latest_regroup_is_computed(space_data):
    from extensions.mapping.session import SpaceLayout

    layout = SpaceLayout(list(space_data.values), space_data.values, space_data.preset)
    assert layout.run(ViewParams(), cancelled=lambda: True) is None
    assert layout.run(ViewParams()) is not None


def test_groups_start_from_the_size_of_the_whole_space(mapping, space_data):
    level = mapping.levels[-1]
    assert level.layout.groups is space_data.groups and level.layout.load_groups is None
    assert mapping.toolbar.sliders["subgroup_size"].value() == mapping.toolbar.sliders["subgroup_size"].maximum()

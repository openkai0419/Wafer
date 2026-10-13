from unittest.mock import patch

import numpy as np
import pytest
from PySide6 import QtCore

from extensions.mapping import projection
from extensions.mapping import map_view as map_view_module
from extensions.mapping import widget as widget_module
from extensions.mapping.map_view import MapPointItem
from extensions.mapping.session import FeatureSpec
from extensions.mapping.widget import MappingWidget
from wafer.core.db.path_values import PathValue


def fake_embed(matrix, n_components, n_neighbors, min_dist, seed):
    output = np.zeros((matrix.shape[0], n_components), dtype=np.float32)
    width = min(n_components, matrix.shape[1])
    output[:, :width] = matrix[:, :width] + np.random.default_rng(0).normal(0, 1e-3, (matrix.shape[0], width))
    return output


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


@pytest.fixture()
def mapping(qtbot, monkeypatch):
    monkeypatch.setattr(projection, "embed", fake_embed)
    paths = [f"c:/{i}.png" for i in range(30)]
    values = {p: {"tags": PathValue("cat, sky" if i < 15 else "dog, sea")} for i, p in enumerate(paths)}
    monkeypatch.setattr(widget_module, "fetch_path_values", lambda db, ps: {p: values[p] for p in ps if p in values})
    monkeypatch.setattr(widget_module, "fetch_sources", lambda db, ps: {p: p.replace(".png", ".zip") for p in ps})
    monkeypatch.setattr(widget_module, "load_pixels", lambda path: None)
    w = MappingWidget()
    qtbot.addWidget(w)
    w.resize(900, 600)
    w.show()
    w.restore_state({"features": [FeatureSpec("tags", "token_set").to_dict()]})
    w.set_files(paths, "db")
    qtbot.waitUntil(lambda: w.current_result() is not None, timeout=5000)
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
    mapping.set_grouping(False)
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
    previous = mapping.current_result()
    mapping.set_grouping(False)
    qtbot.waitUntil(lambda: mapping.current_result() is not previous, timeout=5000)
    return mapping.map_view


def clickable_point(view):
    for item in view.point_items():
        pos = view.mapFromScene(item.pos())
        hit = view.itemAt(pos)
        if isinstance(hit, MapPointItem):
            return pos, hit.row
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
    assert "params" in state and state["grouping"] is True


def test_restore_state_applies_grouping(mapping):
    state = mapping.save_state()
    state["grouping"] = False
    mapping.restore_state(state)
    assert mapping.grouping is False
    assert not mapping.group_check.isChecked()


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


def test_load_pixels_failure_is_a_missing_value(monkeypatch):
    def broken(path, size):
        raise ValueError("bad image")

    monkeypatch.setattr(widget_module, "load_thumbnail", broken)
    assert widget_module.load_pixels("c:/broken.png") is None


def test_thumbnail_cache_grows_to_hold_every_point(mapping, monkeypatch):
    monkeypatch.setattr(widget_module, "THUMB_CACHE", 5)
    mapping.show_result(mapping.current_result())
    assert mapping.thumbs.cache_limit == 30
    monkeypatch.setattr(widget_module, "THUMB_CACHE", 100)
    mapping.show_result(mapping.current_result())
    assert mapping.thumbs.cache_limit == 100


def test_thumbnail_size_matches_map_view():
    assert widget_module.THUMB_SIZE == map_view_module.THUMB_SIZE


def test_set_files_keeps_only_pixels_of_new_paths(mapping, qtbot):
    old = mapping.pixels
    mapping.pixels.update({"c:/0.png": None, "c:/1.png": None, "c:/gone.png": None})
    mapping.set_files(["c:/0.png", "c:/1.png", "c:/2.png"], "db")
    assert mapping.pixels is not old
    assert set(mapping.pixels) == {"c:/0.png", "c:/1.png"}
    assert "c:/gone.png" in old
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 3, timeout=5000)


def test_add_files_keeps_existing_pixels(mapping, qtbot):
    mapping.pixels.update({"c:/0.png": None, "c:/1.png": None})
    mapping.add_files(["c:/new.png"], "db")
    assert {"c:/0.png", "c:/1.png"} <= set(mapping.pixels)
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 31, timeout=5000)


def test_computation_outranks_thumbnail_requests(mapping):
    with patch.object(mapping.dispatcher, "post") as post:
        mapping.recompute()
        mapping.fetch()
    assert [call.kwargs["priority"] for call in post.call_args_list] == [widget_module.COMPUTE_PRIORITY] * 2
    assert widget_module.COMPUTE_PRIORITY > 5

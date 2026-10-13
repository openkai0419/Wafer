from unittest.mock import patch

import numpy as np
import pytest
from PySide6 import QtCore

from extensions.mapping import projection
from extensions.mapping import widget as widget_module
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
    assert mapping.message_text()


def test_remove_files(mapping, qtbot):
    mapping.remove_files(["c:/0.png"])
    qtbot.waitUntil(lambda: mapping.current_result() is not None and len(mapping.current_result().paths) == 29, timeout=5000)


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

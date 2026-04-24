from unittest.mock import MagicMock, patch

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.app.viewer.preview.editable_tag_card import (
    EditableTagCard,
    LineEditor,
    PlainEditor,
    RowEdit,
)
from wafer.app.viewer.preview.tag_edit_service import TagEditService


@pytest.fixture(autouse=True)
def reset_singleton():
    TagEditService._instance = None
    yield
    inst = TagEditService._instance
    if inst is not None and inst._timeout_timer is not None:
        inst._timeout_timer.stop()
    TagEditService._instance = None


@pytest.fixture
def card(qtbot, monkeypatch):
    svc = TagEditService.instance()
    node = MagicMock()
    monkeypatch.setattr(svc, "_resolve_node", lambda: node)
    c = EditableTagCard()
    qtbot.addWidget(c)
    yield c, svc, node
    if svc._timeout_timer is not None:
        svc._timeout_timer.stop()


def test_initial_render_displays_rows(card):
    c, _, _ = card
    c.update_data({"a": "1", "b": "2"}, {"a": False, "b": True}, None, "p", "h1", "db")
    assert set(c.widgets.keys()) == {"a", "b"}
    assert c.widgets["a"].value_cell.text() == "1"
    assert c.widgets["b"].lock_btn.isChecked() is True


def test_save_revert_buttons_disabled_without_changes(card):
    c, _, _ = card
    c.update_data({"a": "1"}, {}, None, "p", "h1", "db")
    assert c._save_btn.isEnabled() is False
    assert c._revert_btn.isEnabled() is False


def test_value_edit_buffered_until_save(card):
    c, _, node = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_row_value_committed("k", "new_v")
    assert "k" in c.local_edits
    assert c._save_btn.isEnabled() is True
    node.send_reliable.assert_not_called()
    c._on_save_clicked()
    assert node.send_reliable.call_count == 1
    payload = node.send_reliable.call_args[0][1]
    assert payload["upserts"] == [{"key": "k", "value": "new_v", "locked": False}]
    assert payload["deletes"] == []
    assert c.local_edits == {}


def test_revert_clears_local_without_submit(card):
    c, _, node = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_row_value_committed("k", "new_v")
    c._on_revert_clicked()
    assert c.local_edits == {}
    node.send_reliable.assert_not_called()


def test_delete_marks_row_until_save(card):
    c, _, node = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_row_delete_toggled("k", True)
    assert c.local_edits["k"].deleted is True
    node.send_reliable.assert_not_called()
    c._on_save_clicked()
    payload = node.send_reliable.call_args[0][1]
    assert payload["deletes"] == ["k"]
    assert payload["upserts"] == []


def test_lock_change_buffered(card):
    c, _, node = card
    c.update_data({"k": "v"}, {"k": False}, None, "p", "h1", "db")
    c._on_row_lock_toggled("k", True)
    assert c.local_edits["k"].new_locked is True
    node.send_reliable.assert_not_called()
    c._on_save_clicked()
    payload = node.send_reliable.call_args[0][1]
    assert payload["upserts"] == [{"key": "k", "value": "v", "locked": True}]


def test_add_via_local_includes_in_save(card):
    c, _, node = card
    c.update_data({}, {}, None, "p", "h1", "db")
    rid = "__new__test"
    c.local_edits[rid] = RowEdit(is_new=True, new_key="newk", new_value="newv", new_locked=False)
    c._render()
    c._on_save_clicked()
    payload = node.send_reliable.call_args[0][1]
    assert payload["upserts"] == [{"key": "newk", "value": "newv", "locked": False}]


def test_key_rename_sends_rename_payload(card):
    c, _, node = card
    c.update_data({"old": "v"}, {"old": True}, None, "p", "h1", "db")
    c._on_row_key_committed("old", "new")
    assert c.local_edits["old"].new_key == "new"
    c._on_save_clicked()
    payload = node.send_reliable.call_args[0][1]
    assert payload["deletes"] == []
    assert payload["upserts"] == []
    assert payload["renames"] == [
        {"old": "old", "new": "new", "value": "v", "locked": True}
    ]


def test_dedupe_key_appends_suffix(card):
    c, _, _ = card
    c.update_data({"k": "v", "k_2": "v2"}, {}, None, "p", "h1", "db")
    deduped = c._dedupe_key("k")
    assert deduped == "k_3"


def test_dedupe_key_excludes_self(card):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    deduped = c._dedupe_key("k", exclude_row_id="k")
    assert deduped == "k"


def test_key_rename_collision_auto_dedupes(card):
    c, _, node = card
    c.update_data({"a": "1", "b": "2"}, {}, None, "p", "h1", "db")
    c._on_row_key_committed("a", "b")
    assert c.local_edits["a"].new_key == "b_2"


def test_add_collision_auto_dedupes(card, qtbot):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")

    class _DlgStub:
        Accepted = QtWidgets.QDialog.Accepted

        def __init__(self, *a, **kw):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def values(self):
            return ("k", "v2")

    with patch("wafer.app.viewer.preview.editable_tag_card._AddTagDialog", _DlgStub):
        c._on_add_clicked()

    new_rows = [e for e in c.local_edits.values() if e.is_new]
    assert len(new_rows) == 1
    assert new_rows[0].new_key == "k_2"


def test_pending_overlay_state_propagates(card):
    c, svc, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    svc.submit("p", "h1", [("k", "new", False)], [], "db")
    assert "k" in c.widgets


def test_commit_confirmed_updates_base_state(card):
    c, svc, _ = card
    c.update_data({"k": "old"}, {"k": False}, None, "p", "h1", "db")
    rid = svc.submit("p", "h1", [("k", "new", True)], [], "db")
    svc.handle_ack({"request_id": rid, "file_hash": "h1", "applied": ["k"], "deleted": []})
    assert c._tags["k"] == "new"
    assert c._locks["k"] is True


def test_commit_confirmed_removes_deleted_keys(card):
    c, svc, _ = card
    c.update_data({"k": "v"}, {"k": False}, None, "p", "h1", "db")
    rid = svc.submit("p", "h1", [], ["k"], "db")
    svc.handle_ack({"request_id": rid, "file_hash": "h1", "applied": [], "deleted": ["k"]})
    assert "k" not in c._tags
    assert "k" not in c.widgets


def test_commit_confirmed_rename_swaps_base_keys(card):
    c, svc, _ = card
    c.update_data({"old": "v"}, {"old": True}, None, "p", "h1", "db")
    rid = svc.submit("p", "h1", [], [], "db", renames=[("old", "new", "v", True)])
    svc.handle_ack({
        "request_id": rid,
        "file_hash": "h1",
        "applied": ["new"],
        "deleted": ["old"],
    })
    assert "old" not in c._tags
    assert c._tags["new"] == "v"
    assert c._locks["new"] is True


def test_commit_confirmed_rename_synthesizes_old_delete(card):
    c, svc, _ = card
    c.update_data({"old": "v"}, {"old": True}, None, "p", "h1", "db")
    rid = svc.submit("p", "h1", [], [], "db", renames=[("old", "new", "v", True)])
    svc.handle_ack({
        "request_id": rid,
        "file_hash": "h1",
        "applied": ["new"],
        "deleted": [],
    })
    assert "old" not in c._tags
    assert c._tags["new"] == "v"


def test_switching_file_clears_local_edits(card):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_row_value_committed("k", "edited")
    assert c.local_edits
    c.update_data({"k": "v2"}, {}, None, "p2", "h2", "db")
    assert c.local_edits == {}


def test_save_does_nothing_when_no_local_edits(card):
    c, _, node = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_save_clicked()
    node.send_reliable.assert_not_called()


def test_value_edit_back_to_original_clears_local(card):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    c._on_row_value_committed("k", "edited")
    assert c.local_edits
    c._on_row_value_committed("k", "v")
    assert c.local_edits == {}


# --- editor type / focus / sizing -------------------------------------------


def test_value_cell_always_uses_plain_editor_for_short_text(card):
    c, _, _ = card
    c.update_data({"k": "short"}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    row.value_cell.start_edit()
    assert isinstance(row.value_cell._editor, PlainEditor)


def test_value_cell_uses_plain_editor_for_long_text(card):
    c, _, _ = card
    c.update_data({"k": "x" * 5000}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    row.value_cell.start_edit()
    assert isinstance(row.value_cell._editor, PlainEditor)


def test_key_cell_uses_line_editor(card):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    row.key_cell.start_edit()
    assert isinstance(row.key_cell._editor, LineEditor)


def test_line_editor_commits_on_focus_out(qtbot):
    container = QtWidgets.QWidget()
    qtbot.addWidget(container)
    lay = QtWidgets.QVBoxLayout(container)
    ed = LineEditor("orig", container)
    other = QtWidgets.QLineEdit(container)
    lay.addWidget(ed)
    lay.addWidget(other)
    container.show()
    qtbot.waitExposed(container)

    received = []
    ed.committed.connect(lambda v: received.append(v))

    ed.setFocus()
    qtbot.waitUntil(lambda: ed.hasFocus(), timeout=1000)
    ed.setText("changed")
    other.setFocus()
    qtbot.waitUntil(lambda: not ed.hasFocus(), timeout=1000)

    assert received == ["changed"]


def test_plain_editor_commits_on_focus_out(qtbot):
    container = QtWidgets.QWidget()
    qtbot.addWidget(container)
    lay = QtWidgets.QVBoxLayout(container)
    ed = PlainEditor("orig", container)
    other = QtWidgets.QLineEdit(container)
    lay.addWidget(ed)
    lay.addWidget(other)
    container.show()
    qtbot.waitExposed(container)

    received = []
    ed.committed.connect(lambda v: received.append(v))

    ed.setFocus()
    qtbot.waitUntil(lambda: ed.hasFocus(), timeout=1000)
    ed.setPlainText("changed")
    other.setFocus()
    qtbot.waitUntil(lambda: not ed.hasFocus(), timeout=1000)

    assert received == ["changed"]


def test_line_editor_escape_does_not_commit(qtbot):
    ed = LineEditor("orig")
    qtbot.addWidget(ed)
    received = []
    ed.committed.connect(lambda v: received.append(v))

    ed.setText("changed")
    QtGui.QGuiApplication.sendEvent(
        ed, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
    )
    assert received == []


def test_line_editor_commit_only_once(qtbot):
    ed = LineEditor("orig")
    qtbot.addWidget(ed)
    received = []
    ed.committed.connect(lambda v: received.append(v))

    ed.setText("changed")
    QtGui.QGuiApplication.sendEvent(
        ed, QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Return, QtCore.Qt.NoModifier)
    )
    ed._commit()
    assert received == ["changed"]


def test_plain_editor_grows_for_long_unwrapped_text(qtbot):
    container = QtWidgets.QWidget()
    qtbot.addWidget(container)
    container.setFixedWidth(300)
    container.resize(300, 600)
    lay = QtWidgets.QVBoxLayout(container)
    short_ed = PlainEditor("short", container)
    lay.addWidget(short_ed)
    container.show()
    qtbot.waitExposed(container)
    qtbot.wait(80)
    short_h = short_ed.height()

    long_ed = PlainEditor("x" * 1000, container)
    lay.addWidget(long_ed)
    qtbot.wait(120)
    long_h = long_ed.height()

    assert long_h > short_h
    assert long_ed._visual_line_count() > 1


def test_editable_cell_returns_to_label_after_commit(card, qtbot):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    cell = row.value_cell
    cell.start_edit()
    assert cell.is_editing() is True
    cell._on_commit("new_value")
    assert cell.is_editing() is False
    assert cell.text() == "new_value"


def test_editable_cell_returns_to_label_after_cancel(card, qtbot):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    cell = row.value_cell
    cell.start_edit()
    cell._on_cancel()
    assert cell.is_editing() is False
    assert cell.text() == "v"


def test_key_label_no_bold_property(card):
    c, _, _ = card
    c.update_data({"k": "v"}, {}, None, "p", "h1", "db")
    row = c.widgets["k"]
    assert row.key_cell._label.property("keyRole") in (None, False)


def test_other_rows_keep_height_when_one_row_enters_edit(qtbot, monkeypatch):
    TagEditService._instance = None
    svc = TagEditService.instance()
    monkeypatch.setattr(svc, "_resolve_node", lambda: MagicMock())

    container = QtWidgets.QWidget()
    qtbot.addWidget(container)
    container.setFixedWidth(400)
    container.resize(400, 600)
    lay = QtWidgets.QVBoxLayout(container)
    lay.setContentsMargins(0, 0, 0, 0)
    c = EditableTagCard(container)
    lay.addWidget(c)
    lay.addStretch(1)
    c.update_data({"a": "x", "b": "y", "c": "z"}, {}, None, "p", "h1", "db")
    container.show()
    qtbot.waitExposed(container)
    qtbot.wait(80)

    initial_heights = {k: w.height() for k, w in c.widgets.items()}
    assert len(set(initial_heights.values())) == 1

    c.widgets["a"].value_cell.start_edit()
    qtbot.wait(80)

    edit_h = c.widgets["a"].height()
    other_b = c.widgets["b"].height()
    other_c = c.widgets["c"].height()
    base = initial_heights["b"]

    assert other_b == base, f"row 'b' inflated to {other_b}, expected {base}"
    assert other_c == base, f"row 'c' inflated to {other_c}, expected {base}"
    assert edit_h > base



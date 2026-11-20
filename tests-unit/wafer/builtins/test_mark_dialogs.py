import sqlite3

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.builtins.mark import dialogs
from wafer.builtins.mark.registry import MarkRegistry


def test_mark_context_menu_keeps_direct_actions(qtbot, monkeypatch):
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    mark_id = MarkRegistry.instance().ids()[0]
    captured = {}

    class Spec:
        def exec(self, pos):
            captured["pos"] = pos

    class Session:
        def menu(self, items):
            captured["items"] = items
            return Spec()

    monkeypatch.setattr(dialogs.Menu, "session", lambda _parent: Session())
    pos = QtCore.QPoint(10, 20)
    dialogs.show_mark_context_menu(parent, mark_id, pos)

    displays = [getattr(item, "display", None) for item in captured["items"] if hasattr(item, "display")]
    assert displays == ["Rename...", "Change color...", "Change shape...", "Scope / Convert...", "Remove..."]
    assert "Manage..." not in displays
    assert captured["items"].count("-") == 2
    assert captured["pos"] == pos


def test_mark_scope_dialog_target_is_all_only_label(qtbot, monkeypatch):
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    mark_id = MarkRegistry.instance().ids()[0]
    captured = {}

    def fake_exec(self):
        captured["combo_texts"] = [[combo.itemText(i) for i in range(combo.count())] for combo in self.findChildren(QtWidgets.QComboBox)]
        captured["labels"] = [label.text() for label in self.findChildren(QtWidgets.QLabel)]
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    assert dialogs.show_mark_management_dialog(parent, mark_id) is True
    assert captured["combo_texts"] == [["Metadata (path scoped)", "Tag (hash scoped)"]]
    assert "All databases" in captured["labels"]


def test_prompt_new_mark_dialog_shows_scope_choices(qtbot, monkeypatch):
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    captured = {}

    def fake_exec(self):
        captured["combo_texts"] = [[combo.itemText(i) for i in range(combo.count())] for combo in self.findChildren(QtWidgets.QComboBox)]
        captured["labels"] = [label.text() for label in self.findChildren(QtWidgets.QLabel)]
        return QtWidgets.QDialog.Rejected

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    assert dialogs.prompt_new_mark(parent, scope="tag") is None
    assert captured["combo_texts"] == [["Mark (metadata / path scoped)", "Tag (hash scoped)"]]
    assert "Create as:" in captured["labels"]


def test_prompt_new_mark_uses_selected_scope(qtbot, monkeypatch):
    reg = MarkRegistry.instance()

    def fake_exec(self):
        line_edit = self.findChildren(QtWidgets.QLineEdit)[0]
        combo = self.findChildren(QtWidgets.QComboBox)[0]
        assert combo.currentData() == "tag"
        line_edit.setText("Tag Scoped Mark")
        combo.setCurrentIndex(combo.findData("meta_info"))
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)

    class _Color:
        def name(self):
            return "#123456"

    monkeypatch.setattr(dialogs.ColorPickerDialog, "get_color", lambda *args, **kwargs: _Color())
    monkeypatch.setattr(dialogs, "has_stored_data", lambda mark_id: False)
    mark_id = reg.id_for("Tag Scoped Mark")
    dialogs.prompt_new_mark(scope="tag")
    try:
        qtbot.waitUntil(lambda: reg.get(mark_id) is not None)
        assert reg.scope_of(mark_id) == "meta_info"
    finally:
        reg.remove(mark_id)


@pytest.fixture
def stored_mark_db(tmp_path, monkeypatch):
    db_path = tmp_path / "db1.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE meta_info (path TEXT, key TEXT, value TEXT)")
    conn.execute("CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT)")
    conn.execute("INSERT INTO meta_info VALUES ('a.png', 'mark.revived', '1')")
    conn.execute("INSERT INTO tags VALUES ('h1', 'mark.revived_tag', '1')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(dialogs, "list_setting_db_names", lambda: ["db1", "missing"])
    monkeypatch.setattr(dialogs, "data_db_path", lambda name: tmp_path / f"{name}.db")
    return db_path


def test_has_stored_data_finds_leftover_meta_and_tag_rows(stored_mark_db):
    assert dialogs.has_stored_data("revived") is True
    assert dialogs.has_stored_data("revived_tag") is True
    assert dialogs.has_stored_data("fresh") is False


def _fake_new_mark_inputs(monkeypatch, name):
    def fake_exec(self):
        self.findChildren(QtWidgets.QLineEdit)[0].setText(name)
        return QtWidgets.QDialog.Accepted

    class _Color:
        def name(self):
            return "#123456"

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    monkeypatch.setattr(dialogs.ColorPickerDialog, "get_color", lambda *args, **kwargs: _Color())


@pytest.mark.parametrize("choice", ["restore", "delete"])
def test_prompt_new_mark_asks_when_a_removed_mark_left_data(qtbot, monkeypatch, stored_mark_db, choice):
    reg = MarkRegistry.instance()
    asked, purged = [], []
    _fake_new_mark_inputs(monkeypatch, "Revived!")
    monkeypatch.setattr(dialogs, "ask_stored_data", lambda parent, mark_id: asked.append(mark_id) or choice)
    monkeypatch.setattr(dialogs, "_purge_mark_from_all_dbs", purged.append)
    dialogs.prompt_new_mark()
    try:
        qtbot.waitUntil(lambda: reg.get("revived") is not None)
        assert asked == ["revived"]
        assert purged == (["revived"] if choice == "delete" else [])
    finally:
        reg.remove("revived")


def test_prompt_new_mark_cancel_on_leftover_data_adds_nothing(qtbot, monkeypatch, stored_mark_db):
    reg = MarkRegistry.instance()
    asked = []
    _fake_new_mark_inputs(monkeypatch, "revived")
    monkeypatch.setattr(dialogs, "ask_stored_data", lambda parent, mark_id: asked.append(mark_id))
    dialogs.prompt_new_mark()
    qtbot.waitUntil(lambda: asked == ["revived"])
    qtbot.wait(50)
    assert reg.get("revived") is None


def test_prompt_new_mark_without_leftover_data_does_not_ask(qtbot, monkeypatch, stored_mark_db):
    reg = MarkRegistry.instance()
    asked = []
    _fake_new_mark_inputs(monkeypatch, "Fresh Mark")
    monkeypatch.setattr(dialogs, "ask_stored_data", lambda parent, mark_id: asked.append(mark_id))
    dialogs.prompt_new_mark()
    try:
        qtbot.waitUntil(lambda: reg.get("fresh_mark") is not None)
        assert asked == []
    finally:
        reg.remove("fresh_mark")


@pytest.mark.parametrize(("label", "expected"), [("Restore", "restore"), ("Delete", "delete"), ("Cancel", None)])
def test_ask_stored_data_returns_the_clicked_choice(monkeypatch, label, expected):
    def fake_exec(self):
        next(b for b in self.buttons() if b.text().replace("&", "") == label).click()
        return 0

    monkeypatch.setattr(QtWidgets.QMessageBox, "exec", fake_exec)
    assert dialogs.ask_stored_data(None, "revived") == expected


def test_prompt_pick_shape_updates_shape_key(qtbot, monkeypatch):
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    reg = MarkRegistry.instance()
    mark_id = reg.add("Shape Dialog Mark", "#123456", shape_key="circle")

    def fake_exec(self):
        combo = self.findChildren(QtWidgets.QComboBox)[0]
        combo.setCurrentIndex(combo.findData("heart"))
        return QtWidgets.QDialog.Accepted

    monkeypatch.setattr(QtWidgets.QDialog, "exec", fake_exec)
    try:
        assert dialogs.prompt_pick_shape(parent, mark_id) is True
        assert reg.shape_key_of(mark_id) == "heart"
    finally:
        reg.remove(mark_id)

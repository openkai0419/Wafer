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
    assert captured["combo_texts"] == [
        ["Metadata (path scoped)", "Tag (hash scoped)"]
    ]
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


def test_prompt_new_mark_uses_selected_scope(monkeypatch):
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
    mark_id = dialogs.prompt_new_mark(scope="tag")
    try:
        assert mark_id is not None
        assert reg.scope_of(mark_id) == "meta_info"
    finally:
        if mark_id:
            reg.remove(mark_id)


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

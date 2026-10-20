from PySide6 import QtCore, QtWidgets
import pytest

from wafer.app.viewer.widgets.workspace_picker import PickResult, WorkspacePickerDialog
from wafer.core.store.workspace import WindowSlot


@pytest.fixture(autouse=True)
def isolated_dialog_layout(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.core.common.paths.resolve_data_path", lambda relative: tmp_path / relative)


def make_slots():
    return [
        WindowSlot(slot_id="a", name="Alpha", path={"database_name": "main"}),
        WindowSlot(slot_id="b", path={"database_name": "main", "selected": ["C:/x/photos"]}),
    ]


def make_dialog(qtbot, *, open_ids=frozenset(), allow_open=True, databases=()):
    dlg = WorkspacePickerDialog(make_slots(), set(open_ids), allow_open=allow_open, databases=list(databases))
    qtbot.addWidget(dlg)
    return dlg


def test_first_row_is_new_workspace(qtbot):
    dlg = make_dialog(qtbot)
    assert dlg.list_widget.count() == 3
    dlg.list_widget.setCurrentRow(0)
    dlg.accept()
    assert dlg.result_value() == PickResult(None, "")


def test_default_selection_is_first_saved_workspace(qtbot):
    dlg = make_dialog(qtbot)
    assert dlg.list_widget.currentRow() == 1
    dlg.accept()
    assert dlg.result_value() == PickResult("a", "")


def test_default_selection_skips_disabled_rows(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a"}, allow_open=False)
    assert dlg.list_widget.currentRow() == 2


def test_default_selection_falls_back_to_new_workspace(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a", "b"}, allow_open=False)
    assert dlg.list_widget.currentRow() == 0


def test_open_rows_disabled_when_not_allowed(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a"}, allow_open=False)
    assert not dlg.list_widget.item(1).flags() & QtCore.Qt.ItemIsEnabled
    assert dlg.list_widget.item(2).flags() & QtCore.Qt.ItemIsEnabled
    assert dlg.list_widget.item(0).flags() & QtCore.Qt.ItemIsEnabled


def test_open_rows_selectable_when_allowed(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a"}, allow_open=True)
    assert dlg.list_widget.item(1).flags() & QtCore.Qt.ItemIsEnabled
    dlg.list_widget.setCurrentRow(1)
    dlg.accept()
    assert dlg.result_value() == PickResult("a", "")


def test_open_rows_are_marked_in_subtitle(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a"})
    assert dlg.list_widget.item(1).data(QtCore.Qt.UserRole + 1).endswith("Open")
    assert not dlg.list_widget.item(2).data(QtCore.Qt.UserRole + 1).endswith("Open")


def test_open_button_disabled_without_enabled_selection(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a", "b"}, allow_open=False)
    dlg.list_widget.setCurrentRow(1)
    assert dlg.open_button.isEnabled() is False
    dlg.list_widget.setCurrentRow(0)
    assert dlg.open_button.isEnabled() is True


def test_close_returns_none(qtbot):
    dlg = make_dialog(qtbot)
    dlg.reject()
    assert dlg.result_value() is None


def test_double_click_accepts(qtbot):
    dlg = make_dialog(qtbot)
    dlg.list_widget.itemDoubleClicked.emit(dlg.list_widget.item(2))
    assert dlg.result() == QtWidgets.QDialog.Accepted
    assert dlg.result_value() == PickResult("b", "")


def test_double_click_on_disabled_row_does_nothing(qtbot):
    dlg = make_dialog(qtbot, open_ids={"a"}, allow_open=False)
    dlg.list_widget.itemDoubleClicked.emit(dlg.list_widget.item(1))
    assert dlg.result() != QtWidgets.QDialog.Accepted


def test_database_choice_hidden_below_two(qtbot):
    dlg = make_dialog(qtbot, databases=["a"])
    dlg.show()
    assert dlg.database_combo.isVisible() is False
    dlg.list_widget.setCurrentRow(0)
    dlg.accept()
    assert dlg.result_value() == PickResult(None, "a")


def test_database_choice_empty_list_gives_empty_name(qtbot):
    dlg = make_dialog(qtbot, databases=[])
    dlg.list_widget.setCurrentRow(0)
    dlg.accept()
    assert dlg.result_value() == PickResult(None, "")


def test_database_choice_shown_for_two(qtbot):
    dlg = make_dialog(qtbot, databases=["a", "b"])
    dlg.show()
    assert dlg.database_combo.isVisible() is True
    assert dlg.database_combo.currentText() == "a"
    dlg.database_combo.setCurrentIndex(1)
    dlg.list_widget.setCurrentRow(0)
    dlg.accept()
    assert dlg.result_value() == PickResult(None, "b")


def test_ask_returns_none_when_rejected(qtbot, monkeypatch):
    monkeypatch.setattr(WorkspacePickerDialog, "exec", lambda self: self.reject())
    assert WorkspacePickerDialog.ask(make_slots(), set(), allow_open=True, databases=[]) is None


def test_size_is_restored(qtbot):
    first = make_dialog(qtbot)
    first.resize(555, 444)
    first.done(QtWidgets.QDialog.Rejected)
    second = make_dialog(qtbot)
    assert second.size() == first.size()

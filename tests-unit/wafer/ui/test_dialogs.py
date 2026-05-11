import py_compile


def test_file_conflict_dialog_parse_choice():
    from wafer.ui.dialogs import FileConflictDialog

    assert FileConflictDialog.parse_choice(None) is None
    assert FileConflictDialog.parse_choice("") is None
    assert FileConflictDialog.parse_choice("キャンセル") == "cancel"
    assert FileConflictDialog.parse_choice("別名で保存") == "rename"
    assert FileConflictDialog.parse_choice("上書き") == "overwrite"


def test_drop_operation_dialog_normalizes_operation():
    from wafer.ui.dialogs import DropOperationDialog

    assert DropOperationDialog.normalize_operation("copy") == "copy"
    assert DropOperationDialog.normalize_operation("move") == "move"
    assert DropOperationDialog.normalize_operation("invalid") == "copy"
    assert DropOperationDialog.normalize_operation(None, default="move") == "move"


def test_drop_target_dialog_normalizes_candidates():
    from wafer.ui.dialogs import DropTargetDialog

    assert DropTargetDialog.normalize_candidates(["a", "", None, "a", "b"]) == ["a", "b"]


def test_drop_target_dialog_uses_default(qtbot):
    from wafer.ui.dialogs import DropTargetDialog

    from PySide6 import QtWidgets

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    dialog = DropTargetDialog(["a", "b"], default="b", parent=parent)
    qtbot.addWidget(dialog)
    assert dialog.combo.currentData() == "b"


def test_drop_target_dialog_ok_sets_selected_path(qtbot):
    from wafer.ui.dialogs import DropTargetDialog

    from PySide6 import QtWidgets

    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    dialog = DropTargetDialog(["a", "b"], default="b", parent=parent)
    qtbot.addWidget(dialog)
    dialog._on_button(dialog.ok_text)
    assert dialog.selected_path == "b"


def test_compile():
    py_compile.compile("wafer/ui/dialogs.py")

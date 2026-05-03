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


def test_compile():
    py_compile.compile("wafer/ui/dialogs.py")

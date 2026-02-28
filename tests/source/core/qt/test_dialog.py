import py_compile


def test_file_conflict_dialog_parse_choice():
    from source.core.qt.dialog import FileConflictDialog

    assert FileConflictDialog.parse_choice(None) is None
    assert FileConflictDialog.parse_choice('') is None
    assert FileConflictDialog.parse_choice('キャンセル') == 'cancel'
    assert FileConflictDialog.parse_choice('別名で保存') == 'rename'
    assert FileConflictDialog.parse_choice('上書き') == 'overwrite'


def test_compile():
    py_compile.compile('source/core/qt/dialog.py')

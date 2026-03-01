import os
import shutil
import tempfile
from PySide6 import QtWidgets
from afterimages.app.viewer.widgets.foldertree import LazyFolderTreeView


def create_fs_tree(base):
    os.makedirs(os.path.join(base, 'A', 'A1'), exist_ok=True)
    os.makedirs(os.path.join(base, 'B'), exist_ok=True)
    with open(os.path.join(base, 'A', 'file.txt'), 'w', encoding='utf-8'):
        pass


def test_rename_and_move(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        tree.expand_path(os.path.join(tmpdir, 'A'))

        # Rename folder A -> A_renamed
        a_path = os.path.join(tmpdir, 'A')
        assert os.path.isdir(a_path)
        assert tree.rename_path(a_path, 'A_renamed') is True
        a_new = os.path.join(tmpdir, 'A_renamed')
        assert os.path.isdir(a_new)
        assert tree.model_.find_item_by_path(a_new) is not None

        # Move A_renamed under B
        b_path = os.path.join(tmpdir, 'B')
        assert tree.move_paths([a_new], b_path) is True
        moved_path = os.path.join(b_path, 'A_renamed')
        assert os.path.isdir(moved_path)
        assert tree.model_.find_item_by_path(moved_path) is not None

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

import py_compile


def test_compile():
    py_compile.compile('afterimages/app/viewer/widgets/foldertree.py')

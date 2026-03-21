import os
import shutil
import tempfile
import time
from PySide6 import QtWidgets
from wafer.app.viewer.widgets.foldertree import (
    LazyFolderTreeView,
    _scan_children,
    _has_subfolders_bg,
    _collect_segments_for_paths,
)
from wafer.utils.paths import normalize_path


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

def test_set_state_preserves_multi_selection(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, 'X'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'Y'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'Z'), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_norm = tmpdir.replace('\\', '/')
        path_x = os.path.join(tmpdir, 'X').replace('\\', '/')
        path_y = os.path.join(tmpdir, 'Y').replace('\\', '/')
        path_z = os.path.join(tmpdir, 'Z').replace('\\', '/')

        tree.set_state(([root_norm], [path_x, path_y, path_z]))
        selected = tree.get_selected_paths()
        assert sorted(selected) == sorted([path_x, path_y, path_z])

        expanded, selected_out = tree.get_state()
        assert sorted(selected_out) == sorted([path_x, path_y, path_z])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


import py_compile


def test_scan_children_returns_dirs_only():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        children = _scan_children(tmpdir, set())
        names = [os.path.basename(p) for p, _ in children]
        assert 'A' in names
        assert 'B' in names
        assert 'file.txt' not in names
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_excludes_paths():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        excluded = {normalize_path(os.path.join(tmpdir, 'A'))}
        children = _scan_children(tmpdir, excluded)
        names = [os.path.basename(p) for p, _ in children]
        assert 'A' not in names
        assert 'B' in names
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_reports_subfolders():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        children = _scan_children(tmpdir, set())
        child_map = {os.path.basename(p): has_sub for p, has_sub in children}
        assert child_map['A'] is True
        assert child_map['B'] is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_nonexistent_dir():
    result = _scan_children('/nonexistent/path/that/does/not/exist', set())
    assert result == []


def test_has_subfolders_true():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        assert _has_subfolders_bg(tmpdir, set()) is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_has_subfolders_false():
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, 'leaf'))
        assert _has_subfolders_bg(os.path.join(tmpdir, 'leaf'), set()) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_has_subfolders_with_exclusion():
    tmpdir = tempfile.mkdtemp()
    try:
        sub = os.path.join(tmpdir, 'only_child')
        os.makedirs(sub)
        excluded = {normalize_path(sub)}
        assert _has_subfolders_bg(tmpdir, excluded) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_has_subfolders_nonexistent():
    assert _has_subfolders_bg('/nonexistent/path', set()) is False


def test_model_dispatcher_initialized(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        assert tree.model_._dispatcher is not None
        assert tree.model_._pending_expands == {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_compile():
    py_compile.compile('wafer/app/viewer/widgets/foldertree.py')


def test_collect_segments_basic():
    root = normalize_path('/data/photos')
    paths = [
        normalize_path('/data/photos/A/A1'),
        normalize_path('/data/photos/B'),
    ]
    segments = _collect_segments_for_paths(paths, [root])
    assert root in segments
    assert normalize_path('/data/photos/A') in segments
    assert normalize_path('/data/photos/A/A1') in segments
    assert normalize_path('/data/photos/B') in segments


def test_collect_segments_deduplicates():
    root = normalize_path('/r')
    paths = [normalize_path('/r/A/B'), normalize_path('/r/A/C')]
    segments = _collect_segments_for_paths(paths, [root])
    assert segments.count(normalize_path('/r/A')) == 1


def test_set_state_async_expands_and_selects(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, 'X'), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, 'Y'), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_norm = normalize_path(tmpdir)
        path_x = normalize_path(os.path.join(tmpdir, 'X'))
        path_y = normalize_path(os.path.join(tmpdir, 'Y'))

        done = []
        tree.set_state_async(
            ([root_norm], [path_x, path_y]),
            on_complete=lambda: done.append(True),
        )

        deadline = time.monotonic() + 5.0
        while not done and time.monotonic() < deadline:
            app.processEvents()
            time.sleep(0.01)

        assert done, "set_state_async did not complete"
        selected = tree.get_selected_paths()
        assert sorted(selected) == sorted([path_x, path_y])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_set_state_async_empty_states(qtbot):
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        done = []
        tree.set_state_async(([], []), on_complete=lambda: done.append(True))
        assert done
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

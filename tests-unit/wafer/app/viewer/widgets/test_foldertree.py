import os
import shutil
import tempfile
import threading
import time
from PySide6 import QtCore
from wafer.app.viewer.widgets import foldertree as foldertree_module
from wafer.app.viewer.widgets.foldertree import (
    LazyFolderTreeView,
    _scan_children,
    _has_subfolders_bg,
    _collect_segments_for_paths,
)
from wafer.utils.paths import normalize_path


def create_fs_tree(base):
    os.makedirs(os.path.join(base, "A", "A1"), exist_ok=True)
    os.makedirs(os.path.join(base, "B"), exist_ok=True)
    with open(os.path.join(base, "A", "file.txt"), "w", encoding="utf-8"):
        pass


def test_rename_and_move(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        tree.expand_path(os.path.join(tmpdir, "A"))

        # Rename folder A -> A_renamed
        a_path = os.path.join(tmpdir, "A")
        assert os.path.isdir(a_path)
        assert tree.rename_path(a_path, "A_renamed") is True
        a_new = os.path.join(tmpdir, "A_renamed")
        assert os.path.isdir(a_new)
        assert tree.model_.find_item_by_path(a_new) is not None

        # Move A_renamed under B
        b_path = os.path.join(tmpdir, "B")
        assert tree.move_paths([a_new], b_path) is True
        moved_path = os.path.join(b_path, "A_renamed")
        assert os.path.isdir(moved_path)
        assert tree.model_.find_item_by_path(moved_path) is not None

    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_set_state_preserves_multi_selection(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "X"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "Y"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "Z"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_norm = tmpdir.replace("\\", "/")
        path_x = os.path.join(tmpdir, "X").replace("\\", "/")
        path_y = os.path.join(tmpdir, "Y").replace("\\", "/")
        path_z = os.path.join(tmpdir, "Z").replace("\\", "/")

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
        assert "A" in names
        assert "B" in names
        assert "file.txt" not in names
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_excludes_paths():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        excluded = {normalize_path(os.path.join(tmpdir, "A"))}
        children = _scan_children(tmpdir, excluded)
        names = [os.path.basename(p) for p, _ in children]
        assert "A" not in names
        assert "B" in names
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_reports_subfolders():
    tmpdir = tempfile.mkdtemp()
    try:
        create_fs_tree(tmpdir)
        children = _scan_children(tmpdir, set())
        child_map = {os.path.basename(p): has_sub for p, has_sub in children}
        assert child_map["A"] is True
        assert child_map["B"] is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_scan_children_nonexistent_dir():
    result = _scan_children("/nonexistent/path/that/does/not/exist", set())
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
        os.makedirs(os.path.join(tmpdir, "leaf"))
        assert _has_subfolders_bg(os.path.join(tmpdir, "leaf"), set()) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_has_subfolders_with_exclusion():
    tmpdir = tempfile.mkdtemp()
    try:
        sub = os.path.join(tmpdir, "only_child")
        os.makedirs(sub)
        excluded = {normalize_path(sub)}
        assert _has_subfolders_bg(tmpdir, excluded) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_has_subfolders_nonexistent():
    assert _has_subfolders_bg("/nonexistent/path", set()) is False


def test_model_dispatcher_initialized(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        assert tree.model_._dispatcher is not None
        assert tree.model_._pending_expands == {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_foldertree_model_accepts_internal_copy_drop(qtbot, tmp_path):
    root = tmp_path / "root"
    src = root / "src"
    dst = root / "dst"
    src.mkdir(parents=True)
    dst.mkdir()
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(root)])
    tree.expand_path(str(dst))
    dst_index = tree.model_.find_index_by_path(str(dst))
    mime = QtCore.QMimeData()
    mime.setData(tree.model_._mime_type, str(src).encode("utf-8"))

    assert tree.model_.canDropMimeData(mime, QtCore.Qt.DropAction.CopyAction, -1, 0, dst_index)


def test_foldertree_internal_drop_uses_selected_copy_operation(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "root"
    src = root / "src"
    dst = root / "dst"
    src.mkdir(parents=True)
    dst.mkdir()
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(root)])
    tree.expand_path(str(dst))
    dst_index = tree.model_.find_index_by_path(str(dst))
    mime = QtCore.QMimeData()
    mime.setData(tree.model_._mime_type, str(src).encode("utf-8"))
    captured = {}
    monkeypatch.setattr(foldertree_module, "resolve_drop_operation_with_ui", lambda op, parent=None, message=None: "copy")
    monkeypatch.setattr(foldertree_module, "execute_paste_plans_with_ui", lambda plans, **kwargs: captured.setdefault("plans", plans) or [])

    assert tree.model_.dropMimeData(mime, QtCore.Qt.DropAction.CopyAction, -1, 0, dst_index)
    assert captured["plans"][0].action == "copy"


def test_foldertree_external_drop_uses_ask_operation(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    src = tmp_path / "source.txt"
    src.write_text("data", encoding="utf-8")
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(root)])
    root_index = tree.model_.find_index_by_path(str(root))
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(src))])
    captured = {}
    monkeypatch.setattr(foldertree_module, "drop_files_with_ui", lambda items, dst, op, **kwargs: captured.update({"op": op, "dst": dst}) or [])

    assert tree.model_.dropMimeData(mime, QtCore.Qt.DropAction.CopyAction, -1, 0, root_index)
    assert captured == {"op": "ask", "dst": foldertree_module.normalize_path(str(root))}


def test_compile():
    py_compile.compile("wafer/app/viewer/widgets/foldertree.py")


def test_collect_segments_basic():
    root = normalize_path("/data/photos")
    paths = [
        normalize_path("/data/photos/A/A1"),
        normalize_path("/data/photos/B"),
    ]
    segments = _collect_segments_for_paths(paths, [root])
    assert root in segments
    assert normalize_path("/data/photos/A") in segments
    assert normalize_path("/data/photos/A/A1") in segments
    assert normalize_path("/data/photos/B") in segments


def test_collect_segments_deduplicates():
    root = normalize_path("/r")
    paths = [normalize_path("/r/A/B"), normalize_path("/r/A/C")]
    segments = _collect_segments_for_paths(paths, [root])
    assert segments.count(normalize_path("/r/A")) == 1


def test_set_state_async_expands_and_selects(qtbot, qapp):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "X"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "Y"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_norm = normalize_path(tmpdir)
        path_x = normalize_path(os.path.join(tmpdir, "X"))
        path_y = normalize_path(os.path.join(tmpdir, "Y"))

        done = []
        tree.set_state_async(
            ([root_norm], [path_x, path_y]),
            on_complete=lambda: done.append(True),
        )

        deadline = time.monotonic() + 5.0
        while not done and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert done, "set_state_async did not complete"
        selected = tree.get_selected_paths()
        assert sorted(selected) == sorted([path_x, path_y])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_set_state_async_empty_states(qtbot):
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


def test_programmatic_expand_suppresses_request_expand(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        tree.expand_path(normalize_path(os.path.join(tmpdir, "A", "A1")))
        assert tree.model_._pending_expands == {}
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reload_tree_preserves_expansion(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1", "deep"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        deep_path = normalize_path(os.path.join(tmpdir, "A", "A1", "deep"))
        tree.expand_path(deep_path)

        expanded_before, _ = tree.get_state()
        tree.reload_tree()

        assert tree.model_._pending_expands == {}

        expanded_after, _ = tree.get_state()
        assert sorted(expanded_before) == sorted(expanded_after)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cancel_pending_expands(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        from wafer.core.qt.dispatcher import CancelToken

        token = CancelToken()
        tree.model_._pending_expands["dummy"] = token
        tree.model_.cancel_pending_expands()
        assert tree.model_._pending_expands == {}
        assert token.is_cancelled()
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_user_expand_triggers_request_expand(qtbot, qapp):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "child"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_item = tree.model_.item(0)
        root_index = tree.model_.indexFromItem(root_item)
        a_item = None
        tree.model_.load_children(root_item)
        for i in range(root_item.rowCount()):
            child = root_item.child(i)
            if child and "A" in (child.text() or ""):
                a_item = child
                break
        assert a_item is not None

        assert tree._programmatic_expand == 0
        a_index = tree.model_.indexFromItem(a_item)
        tree.on_expanded(a_index)

        deadline = time.monotonic() + 3.0
        while tree.model_._pending_expands and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        a_child_path = normalize_path(os.path.join(tmpdir, "A", "child"))
        child_item = tree.model_.find_item_by_path(a_child_path)
        assert child_item is not None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_expand_and_select_paths_multi(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "C"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = os.path.join(tmpdir, "A")
        path_b = os.path.join(tmpdir, "B")
        path_c = os.path.join(tmpdir, "C")

        done = []
        tree.expand_and_select_paths([path_a, path_b, path_c], on_complete=lambda: done.append(True))
        qtbot.waitUntil(lambda: bool(done), timeout=3000)
        selected = sorted(tree.get_selected_paths())
        expected = sorted(normalize_path(p) for p in [path_a, path_b, path_c])
        assert selected == expected

        cur = tree.currentIndex()
        assert cur.isValid()
        assert cur.data() is not None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_expand_and_select_paths_dedupes(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = os.path.join(tmpdir, "A")
        done = []
        tree.expand_and_select_paths([path_a, path_a, path_a], on_complete=lambda: done.append(True))
        qtbot.waitUntil(lambda: bool(done), timeout=3000)
        selected = tree.get_selected_paths()
        assert selected == [normalize_path(path_a)]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_visible_emits_after_selection(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_index = tree.expand_path(tmpdir)
        tree.setCurrentIndex(root_index)
        emitted = []
        tree.folder_selected.connect(lambda: emitted.append(list(tree.get_selected_paths())))

        path_a = normalize_path(os.path.join(tmpdir, "A"))
        assert tree.navigate_next_visible() == path_a
        qtbot.waitUntil(lambda: bool(emitted), timeout=3000)

        assert emitted == [[path_a]]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_visible_can_skip_search_emit(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_index = tree.expand_path(tmpdir)
        tree.setCurrentIndex(root_index)
        emitted = []
        done = []
        tree.folder_selected.connect(lambda: emitted.append(True))
        tree.current_path_changed.connect(lambda _path: done.append(True))

        path_a = normalize_path(os.path.join(tmpdir, "A"))
        assert tree.navigate_next_visible(trigger_search=False) == path_a
        qtbot.waitUntil(lambda: bool(done), timeout=3000)

        assert emitted == []
        assert tree.get_selected_paths() == [path_a]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_expand_recursive_drains_entries_by_timer(qtbot, monkeypatch, tmp_path):
    root = normalize_path(str(tmp_path))
    path_a = normalize_path(os.path.join(root, "A"))
    path_b = normalize_path(os.path.join(root, "B"))
    path_a1 = normalize_path(os.path.join(path_a, "A1"))
    path_b1 = normalize_path(os.path.join(path_b, "B1"))
    children_by_path = {
        root: [(path_a, True), (path_b, True)],
        path_a: [(path_a1, False)],
        path_b: [(path_b1, False)],
        path_a1: [],
        path_b1: [],
    }

    def scan_children(path, _excluded):
        return children_by_path.get(normalize_path(path), [])

    tree = LazyFolderTreeView(roots=[root], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])
    monkeypatch.setattr(foldertree_module, "_scan_children", scan_children)
    monkeypatch.setattr(foldertree_module, "EXPAND_RECURSIVE_BATCH_SIZE", 2)
    monkeypatch.setattr(foldertree_module, "EXPAND_RECURSIVE_DRAIN_MS", 0.0)
    drains = []
    applied = []
    original_drain = LazyFolderTreeView._drain_recursive_expand
    original_apply = LazyFolderTreeView._apply_recursive_expand_entry

    def drain(self, root_path):
        drains.append(root_path)
        original_drain(self, root_path)

    def apply_entry(self, path, children):
        applied.append(path)
        original_apply(self, path, children)

    monkeypatch.setattr(LazyFolderTreeView, "_drain_recursive_expand", drain)
    monkeypatch.setattr(LazyFolderTreeView, "_apply_recursive_expand_entry", apply_entry)

    root_index = tree.model_.indexFromItem(tree.model_.find_item_by_path(root))
    tree.expand_recursive(root_index)
    qtbot.waitUntil(lambda: root not in tree.model_._pending_expands, timeout=3000)

    assert len(drains) >= 2
    assert applied[:3] == [root, path_a, path_b]
    assert tree.model_.find_item_by_path(path_a1) is not None
    assert tree.model_.find_item_by_path(path_b1) is not None


def test_expand_recursive_cancel_clears_job(qtbot, monkeypatch, tmp_path):
    root = normalize_path(str(tmp_path))
    path_a = normalize_path(os.path.join(root, "A"))

    def scan_children(path, _excluded):
        return [(path_a, True)] if normalize_path(path) == root else []

    tree = LazyFolderTreeView(roots=[root], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])
    monkeypatch.setattr(foldertree_module, "_scan_children", scan_children)
    monkeypatch.setattr(foldertree_module, "EXPAND_RECURSIVE_DRAIN_MS", 0.0)

    root_index = tree.model_.indexFromItem(tree.model_.find_item_by_path(root))
    tree.expand_recursive(root_index)
    qtbot.waitUntil(lambda: root in tree._recursive_expand_jobs, timeout=3000)
    tree._cancel_recursive_expand_jobs()

    assert root not in tree._recursive_expand_jobs
    assert root not in tree.model_._pending_expands


def test_cancel_expand_recursive_cancels_active_job(qtbot, monkeypatch, tmp_path):
    root = normalize_path(str(tmp_path))
    path_a = normalize_path(os.path.join(root, "A"))
    os.makedirs(path_a, exist_ok=True)
    started = threading.Event()
    released = threading.Event()

    def scan_children(path, _excluded):
        if normalize_path(path) == root:
            started.set()
            released.wait(2.0)
            return [(path_a, False)]
        return []

    tree = LazyFolderTreeView(roots=[root], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])
    monkeypatch.setattr(foldertree_module, "_scan_children", scan_children)

    root_index = tree.model_.indexFromItem(tree.model_.find_item_by_path(root))
    tree.expand(root_index)
    tree.expand_recursive(root_index)
    qtbot.waitUntil(lambda: started.is_set() and root in tree.model_._pending_expands, timeout=3000)
    token = tree.model_._pending_expands[root]

    tree._cancel_expand_recursive(root_index)
    released.set()

    assert token.is_cancelled()
    assert root not in tree._recursive_expand_jobs
    assert root not in tree.model_._pending_expands
    assert not tree.isExpanded(root_index)

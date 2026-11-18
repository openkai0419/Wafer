import os
import shutil
import tempfile
import threading
import time
from PySide6 import QtCore, QtWidgets
from wafer.app.viewer.widgets import foldertree as foldertree_module
from wafer.app.viewer.widgets.foldertree import (
    LazyFolderTreeView,
    _scan_children,
    _has_subfolders_bg,
    _collect_segments_for_paths,
    structure_is_current,
)
from wafer.core.common.paths import normalize_path
from wafer.core.db.path_scope import compile_ignore_patterns


def item_of(tree, path):
    return tree.model_.path_item_map.get(normalize_path(path))


def index_of(tree, path):
    item = item_of(tree, path)
    return tree.model_.indexFromItem(item) if item is not None else None


def expand_to(qtbot, tree, path):
    roots = [normalize_path(r) for r in tree.model_.roots]
    done = []
    tree.expand_paths_async(_collect_segments_for_paths([normalize_path(path)], roots), on_complete=lambda: done.append(True))
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    return index_of(tree, path)


def reload_and_wait(qtbot, tree, load_settings=None):
    done = []
    tree.reload_folders_async(load_settings, on_complete=done.append)
    qtbot.waitUntil(lambda: bool(done), timeout=3000)
    return done[0]


def create_fs_tree(base):
    os.makedirs(os.path.join(base, "A", "A1"), exist_ok=True)
    os.makedirs(os.path.join(base, "B"), exist_ok=True)
    with open(os.path.join(base, "A", "file.txt"), "w", encoding="utf-8"):
        pass


def test_inline_rename_moves_the_folder_and_its_item(qtbot, tmp_path):
    create_fs_tree(str(tmp_path))
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(tmp_path)])
    a_index = expand_to(qtbot, tree, tmp_path / "A")

    assert tree.model_.setData(a_index, "A_renamed") is True

    assert (tmp_path / "A_renamed").is_dir()
    assert item_of(tree, tmp_path / "A_renamed" / "A1") is not None
    assert item_of(tree, tmp_path / "A") is None


def test_inline_rename_rejects_names_that_leave_the_parent(qtbot, tmp_path, monkeypatch):
    create_fs_tree(str(tmp_path))
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(tmp_path)])
    a_index = expand_to(qtbot, tree, tmp_path / "A")
    warnings = []
    monkeypatch.setattr(foldertree_module.Notifier, "warning", warnings.append)
    executed = []
    monkeypatch.setattr(foldertree_module, "execute_paste_plans_with_ui", lambda **kwargs: executed.append(kwargs))

    for name in ("x/y", "..", "CON"):
        assert tree.model_.setData(a_index, name) is False

    assert executed == []
    assert len(warnings) == 3
    assert (tmp_path / "A" / "A1").is_dir()


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

        done = []
        tree.set_state_async(([root_norm], [path_x, path_y, path_z]), on_complete=lambda: done.append(True))
        qtbot.waitUntil(lambda: bool(done), timeout=3000)
        selected = tree.get_selected_paths()
        assert sorted(selected) == sorted([path_x, path_y, path_z])

        expanded, selected_out = tree.get_state()
        assert sorted(selected_out) == sorted([path_x, path_y, path_z])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reload_tree_preserves_scroll_value(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        for i in range(80):
            os.makedirs(os.path.join(tmpdir, f"Folder_{i:03d}"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.resize(320, 180)
        tree.show()
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, normalize_path(tmpdir))
        bar = tree.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=3000)

        target = max(1, bar.maximum() // 2)
        bar.setValue(target)
        qtbot.waitUntil(lambda: bar.value() == target, timeout=3000)

        reload_and_wait(qtbot, tree)

        qtbot.waitUntil(lambda: abs(tree.verticalScrollBar().value() - target) <= 1, timeout=3000)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_restore_scroll_state_clamps_to_maximum(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        for i in range(40):
            os.makedirs(os.path.join(tmpdir, f"Folder_{i:03d}"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.resize(320, 180)
        tree.show()
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, normalize_path(tmpdir))
        bar = tree.verticalScrollBar()
        qtbot.waitUntil(lambda: bar.maximum() > 0, timeout=3000)

        tree.restore_scroll_state({"value": bar.maximum() + 1000, "maximum": bar.maximum() + 1000})

        qtbot.waitUntil(lambda: bar.value() == bar.maximum(), timeout=3000)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


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


def test_foldertree_model_accepts_internal_copy_drop(qtbot, tmp_path):
    root = tmp_path / "root"
    src = root / "src"
    dst = root / "dst"
    src.mkdir(parents=True)
    dst.mkdir()
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(root)])
    expand_to(qtbot, tree, str(dst))
    dst_index = index_of(tree, str(dst))
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
    expand_to(qtbot, tree, str(dst))
    dst_index = index_of(tree, str(dst))
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
    root_index = index_of(tree, str(root))
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(src))])
    captured = {}
    monkeypatch.setattr(foldertree_module, "drop_files_with_ui", lambda items, dst, op, **kwargs: captured.update({"op": op, "dst": dst}) or [])

    assert tree.model_.dropMimeData(mime, QtCore.Qt.DropAction.CopyAction, -1, 0, root_index)
    assert captured == {"op": "ask", "dst": foldertree_module.normalize_path(str(root))}


def make_drop_tree(qtbot, tmp_path):
    root = tmp_path / "root"
    a_dir = root / "A"
    b_dir = root / "B"
    a_dir.mkdir(parents=True)
    b_dir.mkdir()
    source = tmp_path / "source.txt"
    source.write_text("data", encoding="utf-8")
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.resize(360, 240)
    tree.show()
    tree.model_._build_roots([str(root)])
    expand_to(qtbot, tree, str(root))
    QtWidgets.QApplication.processEvents()
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(source))])
    return tree, root, mime


def test_foldertree_drop_target_resolver_uses_direct_hit(qtbot, tmp_path):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "A"))
    rect = tree.visualRect(target_index)

    resolved = tree._resolve_drop_target_index(rect.center(), mime, QtCore.Qt.DropAction.CopyAction)

    assert resolved == target_index


def test_foldertree_drop_target_resolver_uses_nearest_visible_folder(qtbot, tmp_path):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "B"))
    rect = tree.visualRect(target_index)
    gap_pos = QtCore.QPoint(tree.viewport().rect().center().x(), min(tree.viewport().rect().bottom(), rect.bottom() + rect.height()))

    resolved = tree._resolve_drop_target_index(gap_pos, mime, QtCore.Qt.DropAction.CopyAction)

    assert resolved == target_index


def test_foldertree_drop_target_resolver_ignores_model_drop_validation_during_preview(qtbot, tmp_path, monkeypatch):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    a_index = index_of(tree, str(root / "A"))
    original = tree.model_.canDropMimeData

    def can_drop_only_on_b(data, action, row, column, parent):
        return parent.data(foldertree_module.USER_ROLE_PATH) == normalize_path(str(root / "B")) and original(data, action, row, column, parent)

    monkeypatch.setattr(tree.model_, "canDropMimeData", can_drop_only_on_b)

    resolved = tree._resolve_drop_target_index(tree.visualRect(a_index).center(), mime, QtCore.Qt.DropAction.CopyAction)

    assert resolved == a_index


def test_foldertree_drop_target_resolver_does_not_call_isdir_during_preview(qtbot, tmp_path, monkeypatch):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "A"))
    rect = tree.visualRect(target_index)

    def fail_isdir(_path):
        raise AssertionError("preview should not call isdir")

    monkeypatch.setattr(foldertree_module.os.path, "isdir", fail_isdir)

    resolved = tree._resolve_drop_target_index(rect.center(), mime, QtCore.Qt.DropAction.CopyAction)

    assert resolved == target_index


def test_foldertree_drop_action_for_event_rejects_unsupported_action(qtbot, tmp_path):
    tree, _root, _mime = make_drop_tree(qtbot, tmp_path)

    class Event:
        def proposedAction(self):
            return QtCore.Qt.DropAction.LinkAction

        def dropAction(self):
            return QtCore.Qt.DropAction.LinkAction

    assert tree._drop_action_for_event(Event()) == QtCore.Qt.DropAction.IgnoreAction


def test_foldertree_drop_on_gap_calls_model_drop_on_nearest_target(qtbot, tmp_path, monkeypatch):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "B"))
    rect = tree.visualRect(target_index)
    gap_pos = QtCore.QPoint(tree.viewport().rect().center().x(), min(tree.viewport().rect().bottom(), rect.bottom() + rect.height()))
    captured = {}

    def drop_mime_data(data, action, row, column, parent):
        captured.update({"data": data, "action": action, "row": row, "column": column, "parent": parent})
        return True

    monkeypatch.setattr(tree.model_, "dropMimeData", drop_mime_data)

    assert tree._drop_on_target(gap_pos, mime, QtCore.Qt.DropAction.CopyAction)
    assert captured == {
        "data": mime,
        "action": QtCore.Qt.DropAction.CopyAction,
        "row": -1,
        "column": 0,
        "parent": target_index,
    }


def test_foldertree_drop_event_clears_preview_before_model_drop(qtbot, tmp_path, monkeypatch):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "B"))
    rect = tree.visualRect(target_index)
    gap_pos = QtCore.QPoint(tree.viewport().rect().center().x(), min(tree.viewport().rect().bottom(), rect.bottom() + rect.height()))
    calls = []

    class DropEvent:
        def mimeData(self):
            return mime

        def pos(self):
            return gap_pos

        def proposedAction(self):
            return QtCore.Qt.DropAction.CopyAction

        def setDropAction(self, action):
            calls.append(("setDropAction", action))

        def accept(self):
            raise AssertionError("dropEvent must not call accept")

        def ignore(self):
            raise AssertionError("dropEvent must not call ignore")

    def clear_drop_target_index():
        calls.append(("clear", None))
        tree._drop_target_index = QtCore.QModelIndex()

    def drop_mime_data(data, action, row, column, parent):
        calls.append(("drop", parent))
        return True

    tree._set_drop_target_index(target_index)
    monkeypatch.setattr(tree, "_clear_drop_target_index", clear_drop_target_index)
    monkeypatch.setattr(tree.model_, "dropMimeData", drop_mime_data)

    tree.dropEvent(DropEvent())

    assert calls[0] == ("clear", None)
    assert calls[1] == ("drop", target_index)
    assert calls[-1] == ("setDropAction", QtCore.Qt.DropAction.IgnoreAction)


def test_foldertree_drop_event_ignores_unsupported_action(qtbot, tmp_path, monkeypatch):
    tree, root, mime = make_drop_tree(qtbot, tmp_path)
    target_index = index_of(tree, str(root / "B"))
    rect = tree.visualRect(target_index)
    gap_pos = QtCore.QPoint(tree.viewport().rect().center().x(), min(tree.viewport().rect().bottom(), rect.bottom() + rect.height()))
    called = []

    class DropEvent:
        def mimeData(self):
            return mime

        def pos(self):
            return gap_pos

        def proposedAction(self):
            return QtCore.Qt.DropAction.LinkAction

        def dropAction(self):
            return QtCore.Qt.DropAction.LinkAction

        def setDropAction(self, action):
            called.append(("setDropAction", action))

    monkeypatch.setattr(tree.model_, "dropMimeData", lambda *args, **kwargs: called.append(("drop", args)) or True)

    tree.dropEvent(DropEvent())

    assert called == [("setDropAction", QtCore.Qt.DropAction.IgnoreAction)]


def test_foldertree_model_rejects_drop_when_target_path_is_not_directory(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "root"
    dst = root / "dst"
    root.mkdir()
    dst.mkdir()
    src = tmp_path / "source.txt"
    src.write_text("data", encoding="utf-8")
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([str(root)])
    dst_index = expand_to(qtbot, tree, str(dst))
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(src))])
    dst.rmdir()
    dst.write_text("file", encoding="utf-8")

    monkeypatch.setattr(foldertree_module, "drop_files_with_ui", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("drop_files_with_ui should not be called")))

    assert not tree.model_.dropMimeData(mime, QtCore.Qt.DropAction.CopyAction, -1, 0, dst_index)


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


def test_set_state_async_filters_ignore_pattern(qtbot, qapp):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "keep"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "cache_dir"), exist_ok=True)
        ignore_pattern_re = compile_ignore_patterns(["*cache*"])
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[], ignore_pattern_re=ignore_pattern_re)
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_norm = normalize_path(tmpdir)
        done = []
        tree.set_state_async(([root_norm], []), on_complete=lambda: done.append(True))

        deadline = time.monotonic() + 5.0
        while not done and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)

        assert done, "set_state_async did not complete"
        assert item_of(tree, os.path.join(tmpdir, "keep")) is not None
        assert item_of(tree, os.path.join(tmpdir, "cache_dir")) is None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_programmatic_expand_suppresses_request_expand(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, normalize_path(os.path.join(tmpdir, "A", "A1")))
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
        expand_to(qtbot, tree, deep_path)

        expanded_before, _ = tree.get_state()
        reload_and_wait(qtbot, tree)

        assert tree.model_._pending_expands == {}

        expanded_after, _ = tree.get_state()
        assert sorted(expanded_before) == sorted(expanded_after)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_structure_current_true_when_realized_tree_matches(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        expand_to(qtbot, tree, normalize_path(tmpdir))

        assert structure_is_current(tree.structure_snapshot(), [tmpdir], []) is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_structure_current_detects_loaded_child_rename_and_order_change(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        original_a = os.path.join(tmpdir, "A")
        original_b = os.path.join(tmpdir, "B10")
        os.makedirs(original_a, exist_ok=True)
        os.makedirs(original_b, exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        expand_to(qtbot, tree, normalize_path(tmpdir))

        renamed_b = os.path.join(tmpdir, "B01")
        os.rename(original_b, renamed_b)

        assert structure_is_current(tree.structure_snapshot(), [tmpdir], []) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_structure_current_skips_placeholder_only_descendants(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        parent = os.path.join(tmpdir, "A")
        os.makedirs(os.path.join(parent, "child1"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        expand_to(qtbot, tree, normalize_path(tmpdir))

        os.makedirs(os.path.join(parent, "child2"), exist_ok=True)

        assert structure_is_current(tree.structure_snapshot(), [tmpdir], []) is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_structure_current_detects_excluded_change(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        excluded = normalize_path(os.path.join(tmpdir, "A"))
        os.makedirs(excluded, exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        assert structure_is_current(tree.structure_snapshot(), [tmpdir], [excluded]) is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_structure_current_uses_lightweight_scan(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "child1"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])
        expand_to(qtbot, tree, normalize_path(tmpdir))

        monkeypatch.setattr(foldertree_module, "_has_subfolders_bg", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("_has_subfolders_bg should not be used by is_structure_current")))

        assert structure_is_current(tree.structure_snapshot(), [tmpdir], []) is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_deferred_reload_runs_after_editing_ends(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        editing = {"value": True}
        calls = []
        monkeypatch.setattr(tree, "is_editing", lambda: editing["value"])

        assert tree.defer_reload_if_editing(lambda: calls.append("reload")) is True
        assert tree.has_pending_reload() is True

        editing["value"] = False
        tree._schedule_pending_reload()

        qtbot.waitUntil(lambda: calls == ["reload"], timeout=3000)
        assert tree.has_pending_reload() is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_deferred_reload_prefers_strong_request(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        editing = {"value": True}
        calls = []
        monkeypatch.setattr(tree, "is_editing", lambda: editing["value"])

        assert tree.defer_reload_if_editing(lambda: calls.append("weak")) is True
        assert tree.defer_reload_if_editing(lambda: calls.append("strong"), strong=True) is True
        assert tree.has_pending_reload() is True

        editing["value"] = False
        tree._schedule_pending_reload()

        qtbot.waitUntil(lambda: calls == ["strong"], timeout=3000)
        assert tree.has_pending_reload() is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_deferred_reload_coalesces_multiple_weak_requests(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        editing = {"value": True}
        calls = []
        monkeypatch.setattr(tree, "is_editing", lambda: editing["value"])

        assert tree.defer_reload_if_editing(lambda: calls.append("first")) is True
        assert tree.defer_reload_if_editing(lambda: calls.append("second")) is True
        assert tree.has_pending_reload() is True

        editing["value"] = False
        tree._schedule_pending_reload()

        qtbot.waitUntil(lambda: calls == ["second"], timeout=3000)
        assert tree.has_pending_reload() is False
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_is_editing_detects_live_inline_editor_when_view_state_is_not_editing(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.show()
        tree.model_._build_roots([tmpdir])
        expand_to(qtbot, tree, normalize_path(tmpdir))
        index = index_of(tree, normalize_path(os.path.join(tmpdir, "A")))

        tree.openPersistentEditor(index)
        qtbot.waitUntil(lambda: tree.findChild(QtWidgets.QLineEdit) is not None, timeout=3000)
        editor = tree.findChild(QtWidgets.QLineEdit)
        editor.setFocus()
        qtbot.waitUntil(lambda: editor.hasFocus(), timeout=3000)

        monkeypatch.setattr(tree, "state", lambda: QtWidgets.QAbstractItemView.NoState)

        assert tree.is_editing() is True
        assert tree.defer_reload_if_editing(lambda: None) is True
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_reload_tree_defers_while_editing(qtbot, monkeypatch):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        editing = {"value": True}
        monkeypatch.setattr(tree, "is_editing", lambda: editing["value"])

        tree.reload_tree()

        assert tree.has_pending_reload() is True
        editing["value"] = False
        tree._schedule_pending_reload()
        qtbot.waitUntil(lambda: tree.has_pending_reload() is False, timeout=3000)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_cancel_pending_expands(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        from wafer.qt.common.dispatcher import CancelToken

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
        expand_to(qtbot, tree, tmpdir)
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
        child_item = item_of(tree, a_child_path)
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


def test_expand_and_select_paths_filters_ignore_pattern(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "cache_dir"), exist_ok=True)
        ignore_pattern_re = compile_ignore_patterns(["*cache*"])
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[], ignore_pattern_re=ignore_pattern_re)
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = os.path.join(tmpdir, "A")
        done = []
        tree.expand_and_select_paths([path_a], on_complete=lambda: done.append(True))
        qtbot.waitUntil(lambda: bool(done), timeout=3000)

        assert item_of(tree, normalize_path(path_a)) is not None
        assert item_of(tree, normalize_path(os.path.join(tmpdir, "cache_dir"))) is None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_folder_emits_after_selection(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, tmpdir)
        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_b = normalize_path(os.path.join(tmpdir, "B"))
        tree.setCurrentIndex(index_of(tree, path_a))
        emitted = []
        tree.folder_selected.connect(lambda: emitted.append(list(tree.get_selected_paths())))

        assert tree.navigate_next_folder() == path_b
        qtbot.waitUntil(lambda: bool(emitted), timeout=3000)

        assert emitted == [[path_b]]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_folder_can_skip_search_emit(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, tmpdir)
        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_b = normalize_path(os.path.join(tmpdir, "B"))
        tree.setCurrentIndex(index_of(tree, path_a))
        emitted = []
        done = []
        tree.folder_selected.connect(lambda: emitted.append(True))
        tree.current_path_changed.connect(lambda _path: done.append(True))

        assert tree.navigate_next_folder(trigger_search=False) == path_b
        qtbot.waitUntil(lambda: bool(done), timeout=3000)

        assert emitted == []
        assert tree.get_selected_paths() == [path_b]
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_prev_folder_stay_with_siblings(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_a1 = normalize_path(os.path.join(tmpdir, "A", "A1"))
        path_b = normalize_path(os.path.join(tmpdir, "B"))
        expand_to(qtbot, tree, path_a1)
        a_index = index_of(tree, path_a)
        a1_index = index_of(tree, path_a1)
        b_index = index_of(tree, path_b)

        tree.collapse(a_index)
        tree.setCurrentIndex(a_index)
        assert tree.navigate_next_folder() == path_b
        assert not tree.isExpanded(a_index)

        tree.setCurrentIndex(b_index)
        assert tree.navigate_prev_folder() == path_a
        assert not tree.isExpanded(a_index)

        tree.setCurrentIndex(a1_index)
        assert tree.navigate_next_folder() is None
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_parent_selects_parent_without_expanding(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_a1 = normalize_path(os.path.join(tmpdir, "A", "A1"))
        expand_to(qtbot, tree, path_a1)
        a_index = index_of(tree, path_a)
        a1_index = index_of(tree, path_a1)
        tree.collapse(a_index)
        tree.setCurrentIndex(a1_index)

        assert tree.navigate_parent() == path_a
        assert tree.get_selected_paths() == [path_a]
        assert not tree.isExpanded(a_index)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_parent_can_collapse_selected_parent(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1", "deep"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_a1 = normalize_path(os.path.join(tmpdir, "A", "A1"))
        expand_to(qtbot, tree, path_a1)
        a_index = index_of(tree, path_a)
        a1_index = index_of(tree, path_a1)
        tree._programmatic_expand += 1
        try:
            tree.expand(a_index)
        finally:
            tree._programmatic_expand -= 1
        assert tree.isExpanded(a_index)

        tree.setCurrentIndex(a1_index)
        assert tree.navigate_parent(collapse=True) == path_a
        assert tree.get_selected_paths() == [path_a]
        assert not tree.isExpanded(a_index)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_child_expands_current_only(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1", "deep"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        expand_to(qtbot, tree, tmpdir)
        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_a1 = normalize_path(os.path.join(tmpdir, "A", "A1"))
        a_index = index_of(tree, path_a)
        tree.collapse(a_index)
        tree.setCurrentIndex(a_index)

        assert tree.navigate_child() is None
        qtbot.waitUntil(lambda: tree.get_selected_paths() == [path_a1], timeout=3000)
        a1_index = index_of(tree, path_a1)
        assert tree.get_selected_paths() == [path_a1]
        assert tree.isExpanded(a_index)
        assert not tree.isExpanded(a1_index)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_dfs_does_not_expand_target(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "A1", "deep"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[])
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_index = expand_to(qtbot, tree, tmpdir)
        tree.setCurrentIndex(root_index)
        path_a = normalize_path(os.path.join(tmpdir, "A"))
        path_a1 = normalize_path(os.path.join(tmpdir, "A", "A1"))

        assert tree.navigate_next_dfs() == path_a
        qtbot.waitUntil(lambda: tree.get_selected_paths() == [path_a], timeout=3000)
        a_index = index_of(tree, path_a)
        assert not tree.isExpanded(a_index)

        assert tree.navigate_next_dfs() == path_a1
        qtbot.waitUntil(lambda: tree.get_selected_paths() == [path_a1], timeout=3000)
        a1_index = index_of(tree, path_a1)
        assert tree.isExpanded(a_index)
        assert not tree.isExpanded(a1_index)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_next_dfs_skips_ignore_pattern_folder(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "cache_dir", "inside"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "keep"), exist_ok=True)
        ignore_pattern_re = compile_ignore_patterns(["*cache*"])
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[], ignore_pattern_re=ignore_pattern_re)
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        root_index = expand_to(qtbot, tree, tmpdir)
        tree.setCurrentIndex(root_index)
        path_keep = normalize_path(os.path.join(tmpdir, "keep"))

        assert tree.navigate_next_dfs() == path_keep
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def test_navigate_prev_dfs_skips_ignore_pattern_folder(qtbot):
    tmpdir = tempfile.mkdtemp()
    try:
        os.makedirs(os.path.join(tmpdir, "A", "keep"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "A", "zz_cache"), exist_ok=True)
        os.makedirs(os.path.join(tmpdir, "B"), exist_ok=True)
        ignore_pattern_re = compile_ignore_patterns(["*cache*"])
        tree = LazyFolderTreeView(roots=[tmpdir], excluded=[], ignore_pattern_re=ignore_pattern_re)
        qtbot.addWidget(tree)
        tree.model_._build_roots([tmpdir])

        path_b = normalize_path(os.path.join(tmpdir, "B"))
        expand_to(qtbot, tree, tmpdir)
        b_index = index_of(tree, path_b)
        tree.setCurrentIndex(b_index)
        path_a_keep = normalize_path(os.path.join(tmpdir, "A", "keep"))

        assert tree.navigate_prev_dfs() == path_a_keep
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

    def scan_children(path, _excluded, _ignore_pattern_re=None):
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

    root_index = index_of(tree, root)
    tree.expand_recursive(root_index)
    qtbot.waitUntil(lambda: root not in tree.model_._pending_expands, timeout=3000)

    assert len(drains) >= 2
    assert applied[:3] == [root, path_a, path_b]
    assert item_of(tree, path_a1) is not None
    assert item_of(tree, path_b1) is not None


def test_expand_recursive_filters_ignore_pattern(qtbot, tmp_path):
    root = normalize_path(str(tmp_path))
    path_a = normalize_path(os.path.join(root, "A"))
    os.makedirs(os.path.join(root, "A", "keep"), exist_ok=True)
    os.makedirs(os.path.join(root, "A", "cache_dir"), exist_ok=True)

    ignore_pattern_re = compile_ignore_patterns(["*cache*"])
    tree = LazyFolderTreeView(roots=[root], excluded=[], ignore_pattern_re=ignore_pattern_re)
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])

    root_index = index_of(tree, root)
    tree.expand_recursive(root_index)
    qtbot.waitUntil(lambda: root not in tree.model_._pending_expands, timeout=3000)

    assert item_of(tree, path_a) is not None
    assert item_of(tree, os.path.join(root, "A", "keep")) is not None
    assert item_of(tree, os.path.join(root, "A", "cache_dir")) is None


def test_expand_recursive_cancel_clears_job(qtbot, monkeypatch, tmp_path):
    root = normalize_path(str(tmp_path))
    path_a = normalize_path(os.path.join(root, "A"))

    def scan_children(path, _excluded, _ignore_pattern_re=None):
        return [(path_a, True)] if normalize_path(path) == root else []

    tree = LazyFolderTreeView(roots=[root], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])
    monkeypatch.setattr(foldertree_module, "_scan_children", scan_children)
    monkeypatch.setattr(foldertree_module, "EXPAND_RECURSIVE_DRAIN_MS", 0.0)

    root_index = index_of(tree, root)
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

    def scan_children(path, _excluded, _ignore_pattern_re=None):
        if normalize_path(path) == root:
            started.set()
            released.wait(2.0)
            return [(path_a, False)]
        return []

    tree = LazyFolderTreeView(roots=[root], excluded=[])
    qtbot.addWidget(tree)
    tree.model_._build_roots([root])
    monkeypatch.setattr(foldertree_module, "_scan_children", scan_children)

    root_index = index_of(tree, root)
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


class ExtraColumnsModel(foldertree_module.LazyFolderTreeModel):
    EXTRA_COLUMNS = ("A",)


class ExtraColumnsTreeView(LazyFolderTreeView):
    MODEL_CLASS = ExtraColumnsModel
    BINDING_SCOPE = "ExtraColumnsTree"


def make_extra_columns_tree(qtbot, tmp_path):
    root = tmp_path / "root"
    (root / "A" / "A1").mkdir(parents=True)
    (root / "B").mkdir()
    tree = ExtraColumnsTreeView(roots=[str(root)], excluded=[], instance_name="ExtraColumnsTree")
    qtbot.addWidget(tree)
    tree.set_folders([str(root)])
    return tree, root


def test_subclass_registers_under_its_own_name(qtbot):
    from wafer.qt.commands.binding.instance_registry import InstanceRegistry

    main = LazyFolderTreeView(roots=[], excluded=[])
    qtbot.addWidget(main)
    other = ExtraColumnsTreeView(roots=[], excluded=[], instance_name="Other")
    qtbot.addWidget(other)
    registry = InstanceRegistry.instance()

    assert main in registry.get_all("FolderTree")
    assert other not in registry.get_all("FolderTree")
    assert other in registry.get_all("Other")
    assert main.binding_scope() == "FolderTree"
    assert other.binding_scope() == "ExtraColumnsTree"
    assert isinstance(other.model_, ExtraColumnsModel)


def test_extra_columns_add_non_editable_cells(qtbot, tmp_path):
    tree, root = make_extra_columns_tree(qtbot, tmp_path)
    model = tree.model_

    assert model.columnCount() == 2
    assert [model.headerData(c, QtCore.Qt.Horizontal) for c in range(2)] == ["Folders", "A"]
    root_index = index_of(tree, str(root))
    extra = root_index.siblingAtColumn(1)
    assert extra.isValid()
    extra_flags = model.flags(extra)
    for flag in (QtCore.Qt.ItemIsEditable, QtCore.Qt.ItemIsDragEnabled, QtCore.Qt.ItemIsDropEnabled):
        assert not extra_flags & flag
        assert model.flags(root_index) & flag
    assert extra.data(foldertree_module.USER_ROLE_PATH) is None


def test_extra_columns_follow_children_added_roots_and_reload(qtbot, tmp_path):
    tree, root = make_extra_columns_tree(qtbot, tmp_path)
    model = tree.model_
    other_root = tmp_path / "other"
    other_root.mkdir()

    expand_to(qtbot, tree, str(root / "A"))
    tree.add_root(str(other_root))
    for path in (root / "A", root / "A" / "A1", other_root):
        index = index_of(tree, str(path))
        assert index.siblingAtColumn(1).isValid(), path

    reload_and_wait(qtbot, tree)
    assert model.columnCount() == 2
    assert model.headerData(1, QtCore.Qt.Horizontal) == "A"
    assert index_of(tree, str(root / "A")).siblingAtColumn(1).isValid()


def test_set_folders_emits_folders_set(qtbot, tmp_path):
    tree = LazyFolderTreeView(roots=[], excluded=[])
    qtbot.addWidget(tree)

    with qtbot.waitSignal(tree.folders_set, timeout=1000):
        tree.set_folders([str(tmp_path)])


def test_default_tree_keeps_one_column(qtbot, tmp_path):
    (tmp_path / "A").mkdir()
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(tmp_path)])
    expand_to(qtbot, tree, str(tmp_path))

    assert tree.model_.columnCount() == 1
    assert tree.isHeaderHidden()
    assert index_of(tree, str(tmp_path / "A")).siblingAtColumn(1).isValid() is False
    reload_and_wait(qtbot, tree)
    assert tree.model_.columnCount() == 1


def test_subclass_registers_under_its_binding_scope_by_default(qtbot):
    from wafer.qt.commands.binding.instance_registry import InstanceRegistry

    tree = ExtraColumnsTreeView(roots=[], excluded=[])
    qtbot.addWidget(tree)
    registry = InstanceRegistry.instance()

    assert tree in registry.get_all("ExtraColumnsTree")
    assert tree not in registry.get_all("FolderTree")


def show_extra_columns_tree(qtbot, tmp_path):
    tree, root = make_extra_columns_tree(qtbot, tmp_path)
    tree.resize(480, 240)
    tree.show()
    expand_to(qtbot, tree, str(root))
    QtWidgets.QApplication.processEvents()
    return tree, root


def test_navigation_from_an_extra_cell_uses_its_folder(qtbot, tmp_path):
    tree, root = show_extra_columns_tree(qtbot, tmp_path)
    model = tree.model_
    try:
        a_extra = index_of(tree, str(root / "A")).siblingAtColumn(1)
        tree.setCurrentIndex(a_extra)
        assert tree.currentIndex().column() == 1
        assert tree.current_path() == normalize_path(str(root / "A"))

        emitted = []
        tree.current_path_changed.connect(emitted.append)
        tree.navigate_child(trigger_search=False)
        qtbot.waitUntil(lambda: emitted == [normalize_path(str(root / "A" / "A1"))], timeout=3000)
        assert model.itemFromIndex(a_extra).rowCount() == 0
        assert all(p.startswith(normalize_path(str(root))) for p in model.path_item_map)
        assert emitted == [normalize_path(str(root / "A" / "A1"))]

        tree.setCurrentIndex(index_of(tree, str(root / "A")).siblingAtColumn(1))
        assert tree.navigate_next_folder(trigger_search=False) == normalize_path(str(root / "B"))
        tree.setCurrentIndex(index_of(tree, str(root / "B")).siblingAtColumn(1))
        assert tree.navigate_prev_folder(trigger_search=False) == normalize_path(str(root / "A"))
        tree.setCurrentIndex(index_of(tree, str(root / "A")).siblingAtColumn(1))
        assert tree.navigate_parent(trigger_search=False) == normalize_path(str(root))
    finally:
        tree.close()


def test_context_on_an_extra_cell_resolves_its_folder(qtbot, tmp_path, monkeypatch):
    from wafer.builtins.commands import foldertree as foldertree_commands

    tree, root = show_extra_columns_tree(qtbot, tmp_path)
    try:
        a_extra = index_of(tree, str(root / "A")).siblingAtColumn(1)
        pos = tree.visualRect(a_extra).center()
        assert tree.indexAt(pos).column() == 1
        captured = {}
        monkeypatch.setattr(foldertree_commands, "show_context_menu", lambda ctx: captured.setdefault("ctx", ctx))
        original = foldertree_module.Context.create_menu_context
        monkeypatch.setattr(
            foldertree_module.Context,
            "create_menu_context",
            staticmethod(lambda widget, scope, **kwargs: captured.setdefault("scope", scope) and original(widget, scope, **kwargs)),
        )

        tree.show_context_menu(pos)

        assert captured["scope"] == "ExtraColumnsTree"
        assert captured["ctx"].extras["path"] == normalize_path(str(root / "A"))
    finally:
        tree.close()


def make_deep_tree(qtbot, tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    (root / "z").mkdir()
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(root)])
    return tree, normalize_path(str(root))


def is_expanded(tree, path):
    item = tree.model_.path_item_map.get(path)
    return item is not None and tree.isExpanded(tree.model_.indexFromItem(item))


def test_expand_paths_async_expands_without_touching_selection_or_scroll(qtbot, tmp_path):
    tree, root = make_deep_tree(qtbot, tmp_path)
    z = expand_to(qtbot, tree, f"{root}/z")
    tree.selectionModel().select(z, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
    tree.selectionModel().setCurrentIndex(z, QtCore.QItemSelectionModel.NoUpdate)
    scrolled = []
    tree.scrollTo = lambda *args: scrolled.append(args)
    done = []

    tree.expand_paths_async([root, f"{root}/a"], on_complete=lambda: done.append(True))

    qtbot.waitUntil(lambda: bool(done))
    assert is_expanded(tree, root) and is_expanded(tree, f"{root}/a")
    assert not is_expanded(tree, f"{root}/a/b")
    assert tree.get_selected_paths() == [f"{root}/z"]
    assert tree.current_path() == f"{root}/z"
    assert scrolled == []


def test_expand_paths_async_empty_completes_immediately(qtbot, tmp_path):
    tree, _root = make_deep_tree(qtbot, tmp_path)
    done = []
    tree.expand_paths_async([], on_complete=lambda: done.append(True))
    assert done


def test_load_paths_async_skips_loaded_folders_only_when_asked(qtbot, tmp_path, monkeypatch):
    tree, root = make_deep_tree(qtbot, tmp_path)
    expand_to(qtbot, tree, f"{root}/a")
    scanned = []
    original = foldertree_module._scan_children
    monkeypatch.setattr(foldertree_module, "_scan_children", lambda path, *args: (scanned.append(path), original(path, *args))[1])
    done = []

    tree.load_paths_async([f"{root}/a/b"], lambda: done.append(True), skip_loaded=True)
    qtbot.waitUntil(lambda: len(done) == 1)
    assert scanned == [f"{root}/a/b"]

    scanned.clear()
    tree.load_paths_async([f"{root}/a/b"], lambda: done.append(True))
    qtbot.waitUntil(lambda: len(done) == 2)
    assert scanned == [root, f"{root}/a", f"{root}/a/b"]


def test_set_state_async_fills_a_tree_reloaded_before_apply(qtbot, tmp_path):
    tree, root = make_deep_tree(qtbot, tmp_path)
    expand_to(qtbot, tree, f"{root}/a")
    done = []

    tree.set_state_async(([root, f"{root}/a"], [f"{root}/a/b"]), on_complete=lambda: done.append(True))
    tree.set_folders([root])

    qtbot.waitUntil(lambda: bool(done))
    assert is_expanded(tree, root) and is_expanded(tree, f"{root}/a")
    assert tree.get_selected_paths() == [f"{root}/a/b"]


def test_expand_and_select_paths_fills_a_tree_reloaded_before_apply(qtbot, tmp_path):
    tree, root = make_deep_tree(qtbot, tmp_path)
    expand_to(qtbot, tree, root)
    done = []

    tree.expand_and_select_paths([f"{root}/a/b"], on_complete=lambda: done.append(True), emit_selected=False)
    tree.reload_tree()

    qtbot.waitUntil(lambda: bool(done))
    assert is_expanded(tree, f"{root}/a")
    assert tree.get_selected_paths() == [f"{root}/a/b"]


def root_labels(tree):
    return [item.text() for item in foldertree_module.iter_root_items(tree.model_)]


def child_labels(tree, path):
    item = item_of(tree, path)
    return [item.child(i).text() for i in range(item.rowCount())]


def test_reload_tree_scans_folders_off_the_main_thread(qtbot, tmp_path, monkeypatch):
    create_fs_tree(str(tmp_path))
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(tmp_path)])
    expand_to(qtbot, tree, tmp_path / "A")
    on_main = []
    for name in ("_scan_child_paths", "_has_subfolders_bg"):
        original = getattr(foldertree_module, name)
        monkeypatch.setattr(foldertree_module, name, lambda *args, _original=original: (on_main.append(threading.current_thread() is threading.main_thread()), _original(*args))[1])

    tree.reload_tree()
    assert on_main == []
    reload_and_wait(qtbot, tree)

    assert on_main and not any(on_main)
    assert item_of(tree, tmp_path / "A" / "A1") is not None


def test_destroying_the_view_cancels_its_background_work(qtbot, tmp_path):
    import shiboken6

    create_fs_tree(str(tmp_path))
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    tree.set_folders([str(tmp_path)])
    job_token = foldertree_module.CancelToken()
    tree._recursive_expand_jobs["job"] = foldertree_module.RecursiveExpandJob("job", job_token)
    expand_token = foldertree_module.CancelToken()
    tree.model_._pending_expands["expand"] = expand_token

    shiboken6.delete(tree)

    assert job_token.is_cancelled()
    assert expand_token.is_cancelled()


def test_drag_keeps_folders_on_the_same_row_of_different_parents(qtbot, tmp_path):
    for parent in ("A", "B"):
        (tmp_path / parent / "x").mkdir(parents=True)
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(tmp_path)])
    indexes = [expand_to(qtbot, tree, tmp_path / parent / "x") for parent in ("A", "B")]
    assert indexes[0].row() == indexes[1].row()

    mime = tree.model_.mimeData(indexes + indexes)

    paths = bytes(mime.data(tree.model_._mime_type)).decode("utf-8").split("\n")
    assert paths == [normalize_path(tmp_path / "A" / "x"), normalize_path(tmp_path / "B" / "x")]


def test_roots_follow_the_natural_folder_order_and_match_the_structure_check(qtbot, tmp_path):
    names = ["img10", "Beta", "img2", "alpha"]
    for name in names:
        (tmp_path / name).mkdir()
    roots = [str(tmp_path / name) for name in names]
    tree = LazyFolderTreeView(roots=roots, excluded=[])
    qtbot.addWidget(tree)

    tree.set_folders(roots)

    assert root_labels(tree) == ["alpha", "Beta", "img2", "img10"]
    assert structure_is_current(tree.structure_snapshot(), roots, []) is True


def test_add_root_keeps_the_natural_order_of_loaded_children(qtbot, tmp_path):
    root = tmp_path / "root"
    for name in ("b", "A", "c10", "c9"):
        (root / name).mkdir(parents=True)
    other = tmp_path / "Other"
    other.mkdir()
    tree = LazyFolderTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(root)])
    expand_to(qtbot, tree, root)

    tree.add_root(str(other))

    assert root_labels(tree) == ["Other", "root"]
    assert child_labels(tree, root) == ["A", "b", "c9", "c10"]


def test_late_expand_result_keeps_children_loaded_meanwhile(qtbot, tmp_path):
    create_fs_tree(str(tmp_path))
    tree = LazyFolderTreeView(roots=[str(tmp_path)], excluded=[])
    qtbot.addWidget(tree)
    tree.set_folders([str(tmp_path)])
    root = normalize_path(tmp_path)
    expand_to(qtbot, tree, tmp_path / "A")
    a_item = item_of(tree, tmp_path / "A")
    root_item = item_of(tree, root)

    tree.model_._apply_expanded_children(root_item, root, [(normalize_path(tmp_path / "A"), False)])

    assert item_of(tree, tmp_path / "A") is a_item
    assert child_labels(tree, root) == ["A", "B"]

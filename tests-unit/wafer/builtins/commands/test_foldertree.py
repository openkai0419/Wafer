import os

from PySide6 import QtWidgets

from wafer.core.commands.bridge import Menu
from wafer.core.commands.command.core import CommandRegistry
from wafer.utils.paths import normalize_path
from wafer.builtins.commands.foldertree import (
    FolderTreeCommands,
    _ctx_normalized_path,
    _ctx_normalized_paths,
    _ctx_dir_path,
    next_folder_visible,
    remove_from_view,
    ignore_folder,
    show_context_menu,
)


def test_foldertree_commands_register_paths(qtbot):
    FolderTreeCommands.register()
    assert CommandRegistry.instance().has_command("ft.reload_tree")
    assert CommandRegistry.instance().has_command("ft.next_folder_dfs")
    assert CommandRegistry.instance().has_command("ft.prev_folder_dfs")
    assert CommandRegistry.instance().has_command("ft.next_folder_visible")
    assert CommandRegistry.instance().has_command("ft.prev_folder_visible")
    assert CommandRegistry.instance().has_command("ft.parent_folder")
    assert CommandRegistry.instance().has_command("ft.child_folder")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["ft.reload_tree"]).build()
    assert m is not None
    assert m.actions()


class _FakeCtx:
    def __init__(self, path=None, paths=None, widget=None):
        self._path = path
        self._paths = paths
        self._widget = widget

    def get(self, key):
        if key == "path":
            return self._path
        if key == "paths":
            return self._paths
        if key == "widget":
            return self._widget
        return None

    def get_instance(self, name):
        return None


def test_ctx_normalized_path_returns_path_for_nonexistent_folder(tmp_path):
    missing = str(tmp_path / "nonexistent")
    ctx = _FakeCtx(path=missing)
    result = _ctx_normalized_path(ctx)
    assert result is not None
    assert "nonexistent" in result


def test_ctx_dir_path_returns_none_for_nonexistent_folder(tmp_path):
    missing = str(tmp_path / "nonexistent")
    ctx = _FakeCtx(path=missing)
    result = _ctx_dir_path(ctx)
    assert result is None


def test_ctx_normalized_path_returns_path_for_existing_folder(tmp_path):
    ctx = _FakeCtx(path=str(tmp_path))
    result = _ctx_normalized_path(ctx)
    assert result == normalize_path(str(tmp_path))


class _FakeSettingDB:
    def __init__(self):
        self.removed = []
        self.ignored = []

    def remove_parent_folder(self, path):
        self.removed.append(path)

    def add_ignore_folder(self, path):
        self.ignored.append(path)


class _FakeRoot:
    def __init__(self):
        self.setting_db = _FakeSettingDB()


class _FakeTree(QtWidgets.QWidget):
    def __init__(self, roots, excluded=None, parent=None):
        super().__init__(parent)
        self.roots = set(roots)
        self.excluded = excluded or set()
        self._removed = []
        self._added_excluded = []
        self._root = _FakeRoot()
        self.folder_selected = type("Sig", (), {"emit": lambda self_: None})()

    def get_selected_paths(self):
        return list(self.roots)

    def remove_root(self, path):
        self._removed.append(path)
        self.roots.discard(path)

    def add_excluded(self, path):
        self._added_excluded.append(path)
        self.excluded.add(path)

    def window(self):
        return self._root


def test_remove_from_view_nonexistent_root(tmp_path, qtbot, monkeypatch):
    missing = normalize_path(str(tmp_path / "gone"))
    tree = _FakeTree(roots={missing})
    qtbot.addWidget(tree)
    monkeypatch.setattr(
        "wafer.builtins.commands.foldertree.ConfirmDialog.ask",
        staticmethod(lambda *a, **kw: "Remove"),
    )
    ctx = _FakeCtx(path=str(tmp_path / "gone"), widget=tree)
    remove_from_view(ctx)
    assert missing in tree._removed
    assert missing in tree._root.setting_db.removed


def test_ignore_folder_nonexistent(tmp_path, qtbot, monkeypatch):
    existing_root = normalize_path(str(tmp_path))
    missing = normalize_path(str(tmp_path / "sub" / "gone"))
    tree = _FakeTree(roots={existing_root})
    qtbot.addWidget(tree)
    monkeypatch.setattr(
        "wafer.builtins.commands.foldertree.ConfirmDialog.ask",
        staticmethod(lambda *a, **kw: "Ignore"),
    )
    ctx = _FakeCtx(path=str(tmp_path / "sub" / "gone"), widget=tree)
    ignore_folder(ctx)
    assert missing in tree._added_excluded
    assert missing in tree._root.setting_db.ignored


def test_ignore_folder_multiple_paths(tmp_path, qtbot, monkeypatch):
    root_path = normalize_path(str(tmp_path))
    sub_a = normalize_path(str(tmp_path / "a"))
    sub_b = normalize_path(str(tmp_path / "b"))
    tree = _FakeTree(roots={root_path})
    qtbot.addWidget(tree)
    monkeypatch.setattr(
        "wafer.builtins.commands.foldertree.ConfirmDialog.ask",
        staticmethod(lambda *a, **kw: "Ignore"),
    )
    ctx = _FakeCtx(
        path=str(tmp_path / "a"),
        paths=[str(tmp_path / "a"), str(tmp_path / "b")],
        widget=tree,
    )
    ignore_folder(ctx)
    assert sub_a in tree._added_excluded
    assert sub_b in tree._added_excluded
    assert sub_a in tree._root.setting_db.ignored
    assert sub_b in tree._root.setting_db.ignored


def test_ignore_folder_multiple_skips_roots(tmp_path, qtbot, monkeypatch):
    root_path = normalize_path(str(tmp_path))
    sub_a = normalize_path(str(tmp_path / "a"))
    tree = _FakeTree(roots={root_path})
    qtbot.addWidget(tree)
    monkeypatch.setattr(
        "wafer.builtins.commands.foldertree.ConfirmDialog.ask",
        staticmethod(lambda *a, **kw: "Ignore"),
    )
    ctx = _FakeCtx(
        path=str(tmp_path),
        paths=[str(tmp_path), str(tmp_path / "a")],
        widget=tree,
    )
    ignore_folder(ctx)
    assert root_path not in tree._added_excluded
    assert sub_a in tree._added_excluded


def test_ctx_normalized_paths_from_paths(tmp_path):
    p1 = str(tmp_path / "a")
    p2 = str(tmp_path / "b")
    ctx = _FakeCtx(paths=[p1, p2])
    result = _ctx_normalized_paths(ctx)
    assert len(result) == 2
    assert normalize_path(os.path.abspath(p1)) in result
    assert normalize_path(os.path.abspath(p2)) in result


def test_ctx_normalized_paths_fallback_to_single(tmp_path):
    p = str(tmp_path / "single")
    ctx = _FakeCtx(path=p)
    result = _ctx_normalized_paths(ctx)
    assert len(result) == 1
    assert normalize_path(os.path.abspath(p)) == result[0]


def test_navigation_command_delegates_search_emit_to_tree(qtbot):
    class FakeSignal:
        def __init__(self):
            self.count = 0

        def emit(self):
            self.count += 1

    class FakeTree(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.folder_selected = FakeSignal()
            self.trigger_search = None

        def get_selected_paths(self):
            return []

        def navigate_next_visible(self, trigger_search=True):
            self.trigger_search = trigger_search
            return "selected"

    tree = FakeTree()
    qtbot.addWidget(tree)
    ctx = _FakeCtx(widget=tree)

    assert next_folder_visible(ctx, trigger_search=True) == "selected"
    assert tree.trigger_search is True
    assert tree.folder_selected.count == 0

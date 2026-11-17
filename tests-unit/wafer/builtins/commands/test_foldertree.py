import os

from PySide6 import QtWidgets

from wafer.qt.commands.bridge import Menu
from wafer.qt.commands.command.core import CommandRegistry
from wafer.core.common.paths import normalize_path
from wafer.builtins.commands import foldertree as foldertree_module
from wafer.builtins.commands.foldertree import (
    folder_file_items,
    run_on_folder_files,
    show_in_tree,
    FolderTreeCommands,
    _ctx_normalized_path,
    _ctx_normalized_paths,
    next_folder,
    parent_folder,
    remove_from_view,
    ignore_folder,
    show_context_menu,
)


def test_foldertree_commands_register_paths(qtbot):
    FolderTreeCommands.register()
    assert CommandRegistry.instance().has_command("ft.reload_tree")
    assert CommandRegistry.instance().has_command("ft.next_folder")
    assert CommandRegistry.instance().has_command("ft.prev_folder")
    assert CommandRegistry.instance().has_command("ft.next_folder_dfs")
    assert CommandRegistry.instance().has_command("ft.prev_folder_dfs")
    assert CommandRegistry.instance().has_command("ft.parent_folder")
    assert CommandRegistry.instance().has_command("ft.child_folder")
    assert not CommandRegistry.instance().has_command("ft.next_folder_visible")
    assert not CommandRegistry.instance().has_command("ft.prev_folder_visible")
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

        def navigate_next_folder(self, trigger_search=True):
            self.trigger_search = trigger_search
            return "selected"

    tree = FakeTree()
    qtbot.addWidget(tree)
    ctx = _FakeCtx(widget=tree)

    assert next_folder(ctx, trigger_search=True) == "selected"
    assert tree.trigger_search is True
    assert tree.folder_selected.count == 0


def test_parent_folder_command_passes_collapse_flag(qtbot):
    class FakeTree(QtWidgets.QWidget):
        def __init__(self):
            super().__init__()
            self.trigger_search = None
            self.collapse = None

        def get_selected_paths(self):
            return []

        def navigate_parent(self, trigger_search=True, collapse=False):
            self.trigger_search = trigger_search
            self.collapse = collapse
            return "parent"

    tree = FakeTree()
    qtbot.addWidget(tree)
    ctx = _FakeCtx(widget=tree)

    assert parent_folder(ctx, trigger_search=True, collapse=True) == "parent"
    assert tree.trigger_search is True
    assert tree.collapse is True


class _FilesCtx(_FakeCtx):
    def __init__(self, paths, db_path="x.db", filter_entries=None, instances=None):
        super().__init__(path=paths[0] if paths else None, paths=paths)
        self._db_path = db_path
        self._filter_entries = filter_entries
        self._instances = instances if instances is not None else {"MainWindow": type("W", (), {"database_path": db_path})()}

    def get(self, key):
        if key == "filter_entries":
            return self._filter_entries
        return super().get(key)

    def get_instance(self, name):
        return self._instances.get(name)


def _capture(monkeypatch, sources):
    calls = {"sources": [], "invoke": [], "notices": []}

    def fake_sources(db_path, folders, recursive, filter_entries=()):
        calls["sources"].append((db_path, list(folders), recursive, list(filter_entries)))
        return list(sources)

    monkeypatch.setattr(foldertree_module, "folder_sources", fake_sources)
    monkeypatch.setattr(
        foldertree_module.Command, "invoke", lambda command_id, extras=None, **kw: calls["invoke"].append((command_id, extras))
    )
    monkeypatch.setattr(foldertree_module.Notifier, "info", lambda text: calls["notices"].append(text))
    return calls


def test_files_in_folder_commands_are_registered(qtbot):
    FolderTreeCommands.register()
    registry = CommandRegistry.instance()
    for command_id in ("ft.files.cut_direct", "ft.files.copy_direct", "ft.files.cut_all", "ft.files.copy_all", "ft.show_in_tree"):
        assert registry.has_command(command_id)


def test_cut_all_invokes_file_cut_with_folder_sources(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png", "b.png"])
    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert calls["invoke"] == [("file.cut", {"sources": ["a.png", "b.png"], "paths": ["a.png", "b.png"]})]
    assert calls["sources"][0][:3] == ("x.db", [normalize_path(str(tmp_path))], True)


def test_direct_passes_recursive_false(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.copy", False)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert calls["sources"][0][2] is False
    assert calls["invoke"][0][0] == "file.copy"


def test_query_entries_from_ctx_are_passed_through(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    entries = [("FilterCls", {"k": 1}, None)]
    run_on_folder_files(_FilesCtx([str(tmp_path)], filter_entries=entries), "file.cut", True)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert calls["sources"][0][3] == entries


def test_no_files_shows_notice_and_skips_command(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, [])
    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    qtbot.waitUntil(lambda: bool(calls["notices"]), timeout=3000)
    assert calls["notices"] == ["No files"]
    assert calls["invoke"] == []


def test_no_database_or_folders_does_nothing(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    run_on_folder_files(_FilesCtx([str(tmp_path)], db_path=None), "file.cut", True)
    run_on_folder_files(_FilesCtx([]), "file.cut", True)
    assert calls["sources"] == []
    assert calls["invoke"] == []


def test_show_in_tree_selects_path(tmp_path):
    selected = []
    tree = type("T", (), {"expand_and_select_path": lambda self, p: selected.append(p)})()
    show_in_tree(_FilesCtx([str(tmp_path)], instances={"FolderTree": tree}))
    assert selected == [normalize_path(str(tmp_path))]


def test_folder_file_items_include_files_in_folder_and_no_ignore():
    items = folder_file_items()
    assert "Files in Folder/ft.files.cut_all" in items
    assert "Files in Folder/ft.files.copy_direct" in items
    assert all("ignore" not in str(i) and "remove_from_view" not in str(i) for i in items)


def test_context_menu_contains_files_in_folder(qtbot, tmp_path, monkeypatch):
    seen = {}

    class FakeSession:
        def menu(self, items):
            seen["items"] = items
            return type("M", (), {"exec": lambda self: None})()

    monkeypatch.setattr(foldertree_module.Menu, "from_context", lambda ctx: FakeSession())
    tree = _FakeTree(roots=set())
    qtbot.addWidget(tree)
    show_context_menu(_FakeCtx(path=str(tmp_path), widget=tree))
    assert "Files in Folder/ft.files.cut_all" in seen["items"]

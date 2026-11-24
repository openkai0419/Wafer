import os
import threading

from PySide6 import QtWidgets

from wafer.qt.commands.bridge import Menu
from wafer.qt.commands.command.core import CommandRegistry
from wafer.core.common.paths import normalize_path
from wafer.builtins.commands import foldertree as foldertree_module
from wafer.builtins.commands.foldertree import (
    folder_menu_sections,
    menu_sections,
    cut_all_files,
    copy_direct_files,
    run_on_disk_files,
    run_on_folder_files,
    FolderFilesCommands,
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
    def __init__(self, paths, instances=None):
        super().__init__(path=paths[0] if paths else None, paths=paths)
        self._instances = instances if instances is not None else {}

    def get_instance(self, name):
        return self._instances.get(name)


def _capture(monkeypatch, sources):
    calls = {"sources": [], "invoke": [], "notices": []}

    def fake_disk_files(folders, recursive, cancel=None):
        calls["sources"].append((list(folders), recursive))
        return list(sources)

    monkeypatch.setattr(foldertree_module, "disk_files", fake_disk_files)
    monkeypatch.setattr(
        foldertree_module.Command, "invoke", lambda command_id, extras=None, **kw: calls["invoke"].append((command_id, extras))
    )
    monkeypatch.setattr(foldertree_module.Notifier, "info", lambda text: calls["notices"].append(text))
    return calls


def test_files_in_folder_commands_are_registered(qtbot):
    FolderTreeCommands.register()
    FolderFilesCommands.register()
    registry = CommandRegistry.instance()
    for command_id in ("ft.files.cut_direct", "ft.files.copy_direct", "ft.files.cut_all", "ft.files.copy_all"):
        assert registry.has_command(command_id)
    assert not registry.has_command("ft.show_in_tree")


def command_paths(group):
    return [getattr(item, "path", item) for item in group.commands()]


def test_files_in_folder_commands_are_available_everywhere():
    assert FolderFilesCommands.SCOPE == "*"
    assert FolderFilesCommands.NAME == FolderTreeCommands.NAME
    files = ["ft.files.cut_direct", "ft.files.copy_direct", "ft.files.cut_all", "ft.files.copy_all"]
    assert [path for path in command_paths(FolderFilesCommands) if path in files] == files
    assert not set(files) & set(command_paths(FolderTreeCommands))
    assert "ft.show_in_tree" not in command_paths(FolderTreeCommands)
    assert command_paths(FolderFilesCommands)[0] == ":All files on disk"
    assert FolderTreeCommands.SCOPE != "*"


def test_files_in_folder_takes_every_file_on_disk_without_a_database(qtbot, monkeypatch, tmp_path):
    invoked = []
    monkeypatch.setattr(foldertree_module.Command, "invoke", lambda command_id, extras=None, **kw: invoked.append((command_id, extras)))
    for name in ("a.png", "notes.txt", "excluded/b.png", "sub/deep/c.png"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"x")
    root = normalize_path(str(tmp_path))

    cut_all_files(_FilesCtx([str(tmp_path)]))
    qtbot.waitUntil(lambda: len(invoked) == 1, timeout=3000)
    copy_direct_files(_FilesCtx([str(tmp_path)]))
    qtbot.waitUntil(lambda: len(invoked) == 2, timeout=3000)
    every = sorted(f"{root}/{name}" for name in ("a.png", "notes.txt", "excluded/b.png", "sub/deep/c.png"))
    assert invoked[0][0] == "file.cut" and sorted(invoked[0][1]["sources"]) == every
    assert invoked[1][0] == "file.copy" and sorted(invoked[1][1]["sources"]) == [f"{root}/a.png", f"{root}/notes.txt"]
    assert invoked[1][1]["paths"] == invoked[1][1]["sources"]


def test_cut_all_invokes_file_cut_with_disk_files(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png", "b.png"])
    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert calls["invoke"] == [("file.cut", {"sources": ["a.png", "b.png"], "paths": ["a.png", "b.png"]})]
    assert calls["sources"] == [([normalize_path(str(tmp_path))], True)]


def test_direct_passes_recursive_false(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.copy", False)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert calls["sources"][0][1] is False
    assert calls["invoke"][0][0] == "file.copy"


def test_folder_files_are_collected_off_the_main_thread(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, [])
    threads = []
    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.cut", lambda folders, cancel: threads.append((threading.current_thread(), folders)) or ["x.png"])
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert threads[0][0] is not threading.main_thread()
    assert threads[0][1] == [normalize_path(str(tmp_path))]
    assert calls["invoke"] == [("file.cut", {"sources": ["x.png"], "paths": ["x.png"]})]


def test_a_new_request_cancels_the_one_still_collecting(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, [])
    timers = capture_notice_timer(monkeypatch)
    started, release = threading.Event(), threading.Event()
    tokens = []

    def slow(folders, cancel):
        tokens.append(cancel)
        started.set()
        release.wait(5)
        return ["old.png"]

    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.cut", slow)
    assert started.wait(5)
    run_on_folder_files(_FilesCtx([str(tmp_path)]), "file.copy", lambda folders, cancel: ["new.png"])
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    assert tokens[0].is_cancelled()
    timers[0][1]()
    release.set()
    for _ in range(50):
        qtbot.wait(10)
    assert calls["invoke"] == [("file.copy", {"sources": ["new.png"], "paths": ["new.png"]})]
    assert calls["notices"] == []


def test_disk_requests_hand_their_cancel_token_to_the_walk(qtbot, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(foldertree_module, "disk_files", lambda folders, recursive, cancel=None: seen.append(cancel) or [])
    monkeypatch.setattr(foldertree_module.Notifier, "info", lambda text: None)
    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    qtbot.waitUntil(lambda: bool(seen), timeout=3000)
    assert callable(getattr(seen[0], "is_cancelled", None)) and not seen[0].is_cancelled()


def test_no_files_shows_notice_and_skips_command(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, [])
    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    qtbot.waitUntil(lambda: bool(calls["notices"]), timeout=3000)
    assert calls["notices"] == ["No files"]
    assert calls["invoke"] == []


def test_no_folders_does_nothing(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    run_on_disk_files(_FilesCtx([]), "file.cut", True)
    assert calls["sources"] == []
    assert calls["invoke"] == []


def capture_notice_timer(monkeypatch):
    timers = []
    monkeypatch.setattr(foldertree_module.QtCore.QTimer, "singleShot", lambda ms, callback: timers.append((ms, callback)))
    return timers


def test_slow_collection_tells_the_user_it_is_collecting(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    timers = capture_notice_timer(monkeypatch)
    release = threading.Event()
    real_sources = foldertree_module.disk_files
    monkeypatch.setattr(foldertree_module, "disk_files", lambda *args: release.wait(5) and real_sources(*args))

    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.cut", True)
    assert [ms for ms, _callback in timers] == [foldertree_module.COLLECTING_NOTICE_MS]
    timers[0][1]()
    assert calls["notices"] == ["Collecting files…"]
    release.set()
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)


def test_quick_collection_shows_no_collecting_notice(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, ["a.png"])
    timers = capture_notice_timer(monkeypatch)
    run_on_disk_files(_FilesCtx([str(tmp_path)]), "file.copy", False)
    qtbot.waitUntil(lambda: bool(calls["invoke"]), timeout=3000)
    timers[0][1]()
    assert calls["notices"] == []


def test_folder_menu_sections_follow_the_viewer_menu(tmp_path):
    sections = folder_menu_sections(str(tmp_path))
    assert list(sections) == ["File", "Selection", "FolderTree"]
    assert "file.cut" in sections["File"] and "file.select_path" in sections["Selection"]
    assert sections["FolderTree"] == ["Files in Folder/:All files on disk", *[f"Files in Folder/ft.files.{key}" for key in ("cut_direct", "copy_direct", "cut_all", "copy_all")]]
    assert all("ignore" not in str(i) and "remove_from_view" not in str(i) for items in sections.values() for i in items)


def test_folder_menu_sections_offer_only_copy_path_for_a_missing_folder(tmp_path):
    assert folder_menu_sections(str(tmp_path / "gone")) == {"File": ["file.copy_path"]}


def test_menu_sections_put_a_titled_separator_before_each_nonempty_section():
    assert menu_sections([("A", ["a"]), ("Empty", []), ("B", ["b", "-", "c"])]) == [":A", "a", "-", ":B", "b", "-", "c"]


def capture_folder_menu(qtbot, monkeypatch, path, roots):
    seen = {}

    class FakeSession:
        def menu(self, items):
            seen["items"] = items
            return type("M", (), {"exec": lambda self: None})()

    monkeypatch.setattr(foldertree_module.Menu, "from_context", lambda ctx: FakeSession())
    tree = _FakeTree(roots=roots)
    qtbot.addWidget(tree)
    show_context_menu(_FakeCtx(path=path, widget=tree))
    return seen["items"]


def test_context_menu_puts_folder_tree_items_last_and_exclude_apart(qtbot, tmp_path, monkeypatch):
    items = capture_folder_menu(qtbot, monkeypatch, str(tmp_path), roots=set())
    headers = [i for i in items if isinstance(i, str) and i.startswith(":")]
    assert headers == [":File", ":Selection", ":FolderTree", ":Exclude"]
    assert "Files in Folder/ft.files.cut_all" in items
    assert items[-3:-1] == ["-", ":Exclude"]
    assert items[-1].path == "inline.folder.ignore"


def test_context_menu_on_a_root_offers_remove_from_view_under_exclude(qtbot, tmp_path, monkeypatch):
    path = normalize_path(str(tmp_path))
    items = capture_folder_menu(qtbot, monkeypatch, path, roots={path})
    assert items[-3:-1] == ["-", ":Exclude"]
    assert items[-1].path == "inline.folder.remove_from_view"
    assert not any(getattr(i, "path", "") == "inline.folder.ignore" for i in items)


def test_files_in_folder_tells_the_panel_that_asked(qtbot, monkeypatch, tmp_path):
    calls = _capture(monkeypatch, [])
    timers = capture_notice_timer(monkeypatch)
    release = threading.Event()
    real_sources = foldertree_module.disk_files
    monkeypatch.setattr(foldertree_module, "disk_files", lambda *args: release.wait(5) and real_sources(*args))
    told = []

    class PanelCtx(_FilesCtx):
        def get(self, key):
            if key == "notify":
                return told.append
            return super().get(key)

    run_on_disk_files(PanelCtx([str(tmp_path)]), "file.cut", True)
    timers[0][1]()
    release.set()

    qtbot.waitUntil(lambda: len(told) == 2, timeout=3000)
    assert told == ["Collecting files…", "No files"]
    assert calls["notices"] == []

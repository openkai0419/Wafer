import os
import shutil
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtGui, QtWidgets

from wafer.app.viewer.widgets import foldertree as foldertree_module
from wafer.app.viewer.widgets.foldertree import USER_ROLE_PATH, LazyFolderTreeView
from wafer.builtins.filters import TextFilter
from wafer.builtins.folder_manager import view as view_module
from wafer.builtins.folder_manager.rules import Condition, HighlightRule
from wafer.builtins.folder_manager.stats import DiskTree
from wafer.builtins.folder_manager.view import BadgeDelegate, FolderManagerTreeView, FolderStatsModel
from wafer.core.common.paths import data_db_path, normalize_path
from wafer.plugin.query.handler import filter_registry
from wafer.qt.commands.binding.instance_registry import InstanceRegistry


@pytest.fixture
def text_filter():
    filter_registry.register(TextFilter)
    return TextFilter


MENU_HEAD = ["folder_manager.expand_matches", "folder_manager.select_matches", "folder_manager.matches_only", "folder_manager.collapse_all"]


def make_view(qtbot, tmp_path):
    root = tmp_path / "root"
    (root / "a" / "b" / "c").mkdir(parents=True)
    (root / "d").mkdir()
    view = FolderManagerTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(view)
    view.set_folders([str(root)])
    return view, normalize_path(str(root))


def cell_text(view, column, row=0):
    index = view.model_.index(row, column)
    return view.model_.disk_text(index.siblingAtColumn(0).data(USER_ROLE_PATH), column)


def path_of(root, *parts):
    return normalize_path("/".join([root, *parts]))


def rule(name, color, *conditions, enabled=True, bars=None):
    return HighlightRule(name, color, enabled=enabled, bars=bars or [], conditions=[Condition(*c) for c in conditions])


def test_ancestors_stop_at_the_current_drive_root():
    root = os.path.splitdrive(os.getcwd())[0] + "/"
    assert view_module.ancestors_within_roots(f"{root}a/b", [root]) == [root, f"{root}a"]
    assert view_module.ancestors_within_roots(f"{root}a", [root]) == [root]


def test_model_declares_count_columns():
    assert FolderStatsModel.EXTRA_COLUMNS == ("Files", "All files", "Folders", "All folders")


def test_header_names_the_folder_column_in_singular(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    labels = [view.model_.headerData(column, QtCore.Qt.Horizontal) for column in range(5)]
    assert labels == ["Folder", "Files", "All files", "Folders", "All folders"]
    assert foldertree_module.LazyFolderTreeModel([]).headerData(0, QtCore.Qt.Horizontal) == "Folders"


def test_columns_show_disk_counts(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    model = view.model_
    child = path_of(root, "a")
    disk = DiskTree([root])
    disk.add(root, [child], 1)
    disk.add(child, [], 2)
    model.disk = disk

    assert [cell_text(view, c) for c in (1, 2, 3, 4)] == ["1", "", "1", ""]

    disk.finish()
    model.refresh_stats()
    assert [cell_text(view, c) for c in (1, 2, 3, 4)] == ["1", "3", "1", "1"]
    assert model.index(0, 2).data(QtCore.Qt.ToolTipRole) == "Count on disk"
    assert model.headerData(2, QtCore.Qt.Horizontal, QtCore.Qt.ToolTipRole) == "Count on disk"
    assert model.index(0, 0).data(QtCore.Qt.DisplayRole) == "root"


def test_columns_are_empty_without_disk_values(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    model = view.model_
    assert cell_text(view, 1) == ""
    model.disk = DiskTree([root])
    assert cell_text(view, 1) == ""


def test_count_delegate_paints_the_count_of_the_row_folder(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    asked = []
    delegate = view_module.CountDelegate(lambda path, column: asked.append((path, column)) or "88,888", view)
    image = QtGui.QImage(120, 24, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#000000"))
    option = QtWidgets.QStyleOptionViewItem()
    view.initViewItemOption(option)
    option.rect = QtCore.QRect(0, 0, 120, 24)
    option.palette.setColor(QtGui.QPalette.Text, QtGui.QColor("#ffffff"))
    painter = QtGui.QPainter(image)
    delegate.paint(painter, option, view.model_.index(0, 2))
    painter.end()

    assert asked == [(root, 2)]
    lit = [x for x in range(120) for y in range(24) if image.pixelColor(x, y).lightness() > 128]
    assert lit and min(lit) > 40
    assert isinstance(view.itemDelegateForColumn(3), view_module.CountDelegate)


def test_badges_follow_rule_order_and_only_matching_rules(qtbot):
    model = FolderStatsModel([], [])
    folder = "D:/x"
    first = rule("First", "#111111", ("files", ">=", 1))
    off = rule("Off", "#222222", ("files", ">=", 1), enabled=False)
    miss = rule("Miss", "#333333", ("all_files", ">=", 100))
    last = rule("Last", "#444444", ("all_files", ">=", 5))
    model.rule_counts = [(last, {folder: (2, 5)}), (off, {folder: (2, 5)}), (miss, {folder: (2, 5)}), (first, {folder: (2, 5)})]

    assert model.badges(folder) == [("#444444", "2"), ("#111111", "2")]
    assert model.badges("D:/other") == []


def test_folder_only_rule_badge_has_no_number(qtbot):
    model = FolderStatsModel([], [])
    disk = DiskTree(["D:/x"])
    disk.add("D:/x", ["D:/x/y"], 0)
    disk.add("D:/x/y", [], 0)
    disk.finish()
    model.disk = disk
    model.rule_counts = [(rule("Folders", "#123456", ("folders", ">=", 1)), {})]

    assert model.badges("D:/x") == [("#123456", None)]
    assert model.badges("D:/x/y") == []
    assert model.badges("D:/missing") == []


def test_view_does_not_replace_main_folder_tree_instance(qtbot):
    main = LazyFolderTreeView(roots=[], excluded=[])
    qtbot.addWidget(main)
    manager = FolderManagerTreeView(roots=[], excluded=[])
    qtbot.addWidget(manager)
    registry = InstanceRegistry.instance()

    assert main in registry.get_all("FolderTree")
    assert manager not in registry.get_all("FolderTree")
    assert manager in registry.get_all("FolderManagerTree")
    assert manager.binding_scope() == "FolderManagerTree"
    assert not manager.isHeaderHidden()
    assert isinstance(manager.itemDelegateForColumn(0), BadgeDelegate)


def capture_menu(monkeypatch):
    seen = {}

    class FakeSpec:
        def exec(self, *args, **kwargs):
            seen["executed"] = True

    class FakeSession:
        def menu(self, items):
            seen["items"] = items
            return FakeSpec()

    monkeypatch.setattr(view_module.Menu, "session", staticmethod(lambda *args, **kwargs: FakeSession()))
    return seen


def test_context_menu_lists_rule_actions_only_for_rules_with_query(qtbot, tmp_path, monkeypatch, text_filter):
    seen = capture_menu(monkeypatch)
    calls = []
    monkeypatch.setattr(view_module, "run_on_folder_files", lambda ctx, command_id, recursive: calls.append((ctx.get("filter_entries"), ctx.get("paths"), command_id, recursive)))
    view, root = make_view(qtbot, tmp_path)
    view.show_in_tree_available = lambda: True
    view.resize(480, 240)
    view.show()
    bar = {"filter": "text", "params": {"q": "cat"}, "op": "and", "enabled": True}
    queried = rule("Cats", "#111111", ("files", ">=", 1), bars=[bar])
    view.set_rules_source(
        lambda: [
            rule("Plain", "#222222", ("files", ">=", 1)),
            queried,
            rule("Off", "#333333", ("files", ">=", 1), enabled=False, bars=[bar]),
        ]
    )
    index = view.model_.index(0, 0)
    view.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)

    view.show_context_menu(view.visualRect(index).center())

    items = seen["items"]
    assert items[:6] == ["ft.show_in_tree", *MENU_HEAD, "-"]
    assert "Files in Folder/ft.files.cut_all" in items
    assert not any("ignore" in str(i) or "remove_from_view" in str(i) for i in items)
    actions = [i for i in items if not isinstance(i, str)]
    assert [a.display for a in actions] == ["Cats · Cut direct files", "Cats · Copy direct files", "Cats · Cut all files below", "Cats · Copy all files below"]
    assert all(a.path.startswith("Files in Folder/inline.") and "Cats" not in a.path and not a.translate for a in actions)
    first = items.index(actions[0])
    assert items[first - 1] == "Files in Folder/-"
    assert items[first - 2] == "Files in Folder/ft.files.copy_all"
    assert seen["executed"]

    from wafer.qt.commands.bridge import Context

    for action in actions:
        ctx = Context.create_menu_context(view, view.binding_scope(), extras={"paths": [root]})
        action.func(ctx)
    entries = queried.filter_entries()
    assert calls == [
        (entries, [root], "file.cut", False),
        (entries, [root], "file.copy", False),
        (entries, [root], "file.cut", True),
        (entries, [root], "file.copy", True),
    ]
    view.close()


def test_rule_names_never_reach_translation(qtbot, tmp_path, monkeypatch, text_filter):
    from wafer.qt.commands.bridge import Menu
    from wafer.qt.commands.command import menu_builder

    translated = []
    original_t = menu_builder.t
    monkeypatch.setattr(menu_builder, "t", lambda text, **kwargs: (translated.append(text), original_t(text, **kwargs))[1])
    view, _root = make_view(qtbot, tmp_path)
    bar = {"filter": "text", "params": {"q": "cat"}, "op": "and", "enabled": True}
    view.set_rules_source(lambda: [rule("Secret Rule Name", "#111111", ("files", ">=", 1), bars=[bar])])

    menu = Menu.session(view).menu(["ft.show_in_tree", *view.rule_file_actions()]).build()

    assert menu is not None
    assert translated
    assert not any("Secret Rule Name" in text for text in translated)


def test_rule_actions_keep_empty_and_duplicate_names_distinct(qtbot, tmp_path, text_filter):
    view, _root = make_view(qtbot, tmp_path)
    bar = {"filter": "text", "params": {"q": "cat"}, "op": "and", "enabled": True}
    view.set_rules_source(
        lambda: [
            rule("", "#111111", ("files", ">=", 1), bars=[bar]),
            rule("Same", "#222222", ("files", ">=", 1), bars=[bar]),
            rule("Same", "#333333", ("files", ">=", 1), bars=[bar]),
        ]
    )

    actions = [a for a in view.rule_file_actions() if not isinstance(a, str)]

    labels = [a.display.split(" · ")[0] for a in actions[::4]]
    assert labels == ["Rule 1", "Same", "Same (3)"]
    assert len({a.path for a in actions}) == 12


def test_context_menu_for_a_vanished_folder_offers_only_safe_items(qtbot, tmp_path, monkeypatch, text_filter):
    seen = capture_menu(monkeypatch)
    view, root = make_view(qtbot, tmp_path)
    view.show_in_tree_available = lambda: True
    view.resize(480, 240)
    view.show()
    bar = {"filter": "text", "params": {"keys": ["Comment"], "keywords": "cat"}, "op": None, "enabled": True}
    view.set_rules_source(lambda: [rule("Cats", "#111111", ("files", ">=", 1), bars=[bar])])
    index = view.model_.index(0, 0)
    view.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
    shutil.rmtree(tmp_path / "root")

    view.show_context_menu(view.visualRect(index).center())

    assert seen["items"] == ["ft.show_in_tree", *MENU_HEAD, "-", "file.copy_path", "-"]
    view.close()


def open_menu_on_first_row(view):
    view.resize(480, 240)
    view.show()
    index = view.model_.index(0, 0)
    view.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
    view.show_context_menu(view.visualRect(index).center())


def test_context_menu_shows_show_in_tree_only_for_the_window_database(qtbot, tmp_path, monkeypatch):
    seen = capture_menu(monkeypatch)
    view, _root = make_view(qtbot, tmp_path)
    assert view.show_in_tree_available() is False

    open_menu_on_first_row(view)
    assert seen["items"][:5] == [*MENU_HEAD, "-"]
    assert "file.select_path" not in seen["items"]

    view.show_in_tree_available = lambda: True
    open_menu_on_first_row(view)
    assert seen["items"][:5] == ["ft.show_in_tree", *MENU_HEAD]
    assert "file.select_path" in seen["items"]
    view.close()


def test_context_carries_the_panel_database(qtbot, tmp_path):
    from wafer.qt.commands.bridge import Context

    view, root = make_view(qtbot, tmp_path)
    assert view.database_name == ""
    view.database_name = "main"
    view.resize(480, 240)
    view.show()
    index = view.model_.index(0, 0)
    ctx = Context.create_menu_context(view, view.binding_scope(), pos=view.visualRect(index).center())

    context = view.extend_context(ctx, None, source="menu")

    assert context["database_name"] == "main"
    assert context["database_path"] == data_db_path("main")
    assert context["path"] == root
    view.close()


def test_rules_whose_query_matches_every_file_add_no_actions(qtbot, tmp_path, text_filter):
    view, _root = make_view(qtbot, tmp_path)
    empty = {"filter": "text", "params": {"keys": ["path"], "keywords": ""}, "op": None, "enabled": True}
    blank = {"filter": "text", "params": {"keys": ["path"], "keywords": "  "}, "op": "AND", "enabled": True}
    view.set_rules_source(lambda: [rule("Empty", "#111111", ("files", ">=", 1), bars=[empty, blank])])

    assert view.rule_file_actions() == []


def test_context_menu_without_folder_does_nothing(qtbot, tmp_path, monkeypatch):
    seen = capture_menu(monkeypatch)
    view, _root = make_view(qtbot, tmp_path)
    view.resize(480, 240)
    view.show()
    view.clearSelection()

    view.show_context_menu(QtCore.QPoint(5, view.viewport().height() - 2))

    assert "items" not in seen
    view.close()


def test_folders_to_open_lists_each_ancestor_once_parents_first():
    roots = ["D:/lib", "E:/"]
    paths = ["D:/lib/a/b/c", "D:/lib/a/x", "E:/p/q", "F:/elsewhere/x", "D:/lib"]
    assert view_module.folders_to_open(paths, roots) == ["D:/lib", "D:/lib/a", "D:/lib/a/b", "E:/", "E:/p"]


def test_expand_folders_opens_folders_in_batches(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(view_module, "EXPAND_RECURSIVE_BATCH_SIZE", 1)
    view, root = make_view(qtbot, tmp_path)
    selected = view.model_.index(0, 0)
    view.selectionModel().select(selected, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
    view.selectionModel().setCurrentIndex(selected, QtCore.QItemSelectionModel.NoUpdate)
    calls = []
    original = view.load_paths_async
    monkeypatch.setattr(view, "load_paths_async", lambda paths, on_loaded, **kwargs: (calls.append(list(paths)), original(paths, on_loaded, **kwargs)))
    scrolled = []
    monkeypatch.setattr(view, "scrollTo", lambda *args: scrolled.append(args))
    target = path_of(root, "a", "b", "c")

    view.expand_folders(view_module.folders_to_open([target, path_of(root, "a", "b")], [root]))
    view.clearSelection()

    def expanded(path):
        item = view.model_.path_item_map.get(path)
        return item is not None and view.isExpanded(view.model_.indexFromItem(item))

    qtbot.waitUntil(lambda: all(expanded(p) for p in (root, path_of(root, "a"), path_of(root, "a", "b"))))
    assert calls == [[root], [path_of(root, "a")], [path_of(root, "a", "b")]]
    assert not expanded(target)
    assert view.get_selected_paths() == []
    assert view.current_path() == root
    assert scrolled == []


def test_expand_folders_without_folders_does_nothing(qtbot, tmp_path, monkeypatch):
    view, _root = make_view(qtbot, tmp_path)
    calls = []
    monkeypatch.setattr(view, "load_paths_async", lambda paths, on_loaded, **kwargs: calls.append(paths))

    view.expand_folders([])

    assert calls == []


def test_set_column_visible_hides_and_shows(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    view.set_column_visible(4, False)
    assert view.isColumnHidden(4)
    view.set_column_visible(4, True)
    assert not view.isColumnHidden(4)
    view.set_column_visible(0, False)
    assert not view.isColumnHidden(0)


def test_hidden_columns_and_layout_survive_reload(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    view.set_column_visible(4, False)

    view.set_folders([root])
    assert view.isColumnHidden(4)
    view.reload_tree()
    assert view.isColumnHidden(4)
    assert not view.isColumnHidden(1)
    assert view.header().sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch


def fake_paste_ok(monkeypatch):
    def paste(plans, **kwargs):
        return [SimpleNamespace(status="ok", dst=str(plans[0].dst_default))]

    monkeypatch.setattr(foldertree_module, "execute_paste_plans_with_ui", paste)


def test_rename_emits_parent_folder(qtbot, tmp_path, monkeypatch):
    fake_paste_ok(monkeypatch)
    view, root = make_view(qtbot, tmp_path)
    view.expand_path(path_of(root, "a"))
    with qtbot.waitSignal(view.model_.paths_changed) as blocker:
        assert view.rename_path(path_of(root, "a", "b"), "renamed")
    assert blocker.args == [[path_of(root, "a")]]


def test_rename_to_same_name_does_not_emit(qtbot, tmp_path, monkeypatch):
    fake_paste_ok(monkeypatch)
    view, root = make_view(qtbot, tmp_path)
    view.expand_path(root)
    emitted = []
    view.model_.paths_changed.connect(emitted.append)
    assert view.rename_path(path_of(root, "a"), "a")
    assert emitted == []


def test_failed_rename_does_not_emit(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(foldertree_module, "execute_paste_plans_with_ui", lambda plans, **kwargs: [])
    view, root = make_view(qtbot, tmp_path)
    view.expand_path(root)
    emitted = []
    view.model_.paths_changed.connect(emitted.append)
    assert not view.rename_path(path_of(root, "a"), "x")
    assert emitted == []


def test_move_emits_source_and_destination_parents(qtbot, tmp_path, monkeypatch):
    fake_paste_ok(monkeypatch)
    view, root = make_view(qtbot, tmp_path)
    view.expand_path(path_of(root, "a"))
    with qtbot.waitSignal(view.model_.paths_changed) as blocker:
        assert view.move_paths([path_of(root, "a", "b")], path_of(root, "d"))
    assert blocker.args == [[path_of(root, "a"), path_of(root, "d")]]


def test_badge_delegate_paints_without_error(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    delegate = BadgeDelegate(lambda path: [("#ff0000", "12"), ("#00ff00", None)], view)
    index = view.model_.index(0, 0)
    assert index.data(USER_ROLE_PATH)
    image = QtGui.QImage(400, 24, QtGui.QImage.Format_ARGB32)
    image.fill(QtGui.QColor("#000000"))
    option = QtWidgets.QStyleOptionViewItem()
    option.rect = QtCore.QRect(0, 0, 400, 24)
    option.font = view.font()
    option.fontMetrics = view.fontMetrics()
    painter = QtGui.QPainter(image)
    delegate.paint(painter, option, index)
    painter.end()

    pixels = {(x, y): image.pixelColor(x, y) for x in range(400) for y in range(24)}
    red = [xy for xy, c in pixels.items() if c.name() == "#ff0000"]
    assert red
    assert any(c.name() == "#00ff00" for c in pixels.values())
    left, right = min(x for x, _ in red), max(x for x, _ in red)
    top, bottom = min(y for _, y in red), max(y for _, y in red)
    whitish = [c for (x, y), c in pixels.items() if left <= x <= right and top <= y <= bottom and min(c.red(), c.green(), c.blue()) > 180]
    assert whitish


def test_badge_delegate_skips_rows_without_badges(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    index = view.model_.index(0, 0)

    def paint_with(delegate):
        image = QtGui.QImage(200, 24, QtGui.QImage.Format_ARGB32)
        image.fill(QtGui.QColor("#000000"))
        option = QtWidgets.QStyleOptionViewItem()
        option.rect = QtCore.QRect(0, 0, 200, 24)
        painter = QtGui.QPainter(image)
        delegate.paint(painter, option, index)
        painter.end()
        return image

    asked = []
    badge_image = paint_with(BadgeDelegate(lambda path: asked.append(path) or [], view))
    assert asked == [index.data(USER_ROLE_PATH)]
    assert badge_image == paint_with(QtWidgets.QStyledItemDelegate(view))


def test_folder_rules_show_no_badge_until_disk_values_are_known(qtbot):
    model = FolderStatsModel([], [])
    few_folders = rule("Few", "#111111", ("all_folders", "<=", 3))
    flat = rule("Flat", "#222222", ("folders", "==", 0))
    files = rule("Files", "#333333", ("files", "<=", 0))
    model.rule_counts = [(few_folders, {}), (flat, {}), (files, {})]

    assert model.badges("D:/x") == [("#333333", "0")]

    disk = DiskTree(["D:/x"])
    disk.add("D:/x", [], 2)
    model.disk = disk
    model.refresh_stats()
    assert model.badges("D:/x") == [("#222222", None), ("#333333", "0")]

    disk.finish()
    model.refresh_stats()
    assert model.badges("D:/x") == [("#111111", None), ("#222222", None), ("#333333", "0")]


def test_disk_values_are_cached_until_refresh(qtbot, tmp_path, monkeypatch):
    view, root = make_view(qtbot, tmp_path)
    model = view.model_
    disk = DiskTree([root])
    disk.add(root, [], 4)
    disk.finish()
    model.disk = disk
    model.rule_counts = [(rule("Files", "#111111", ("files", ">=", 0)), {})]
    asked = []
    original = disk.values
    monkeypatch.setattr(disk, "values", lambda path: (asked.append(path), original(path))[1])

    for column in (1, 2, 3, 4):
        cell_text(view, column)
    model.badges(root)
    assert asked == [root]

    disk.add(root, [], 9)
    disk.finish()
    with qtbot.waitSignal(model.stats_changed):
        model.refresh_stats()
    assert cell_text(view, 1) == "9"
    assert asked == [root, root]


def test_count_columns_have_a_fixed_width_that_fits_large_counts(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    header = view.header()
    assert header.sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch
    for column in (1, 2, 3, 4):
        assert header.sectionResizeMode(column) == QtWidgets.QHeaderView.Interactive
        label = view.model_.headerData(column, QtCore.Qt.Horizontal)
        assert view.columnWidth(column) >= view.fontMetrics().horizontalAdvance("99,999,999")
        assert view.columnWidth(column) >= header.fontMetrics().horizontalAdvance(label)
    width = view.columnWidth(1)
    view.reload_tree()
    assert view.columnWidth(1) == width


def test_counts_are_not_measured_row_by_row(qtbot, tmp_path, monkeypatch):
    root = tmp_path / "root"
    for number in range(300):
        (root / f"d{number:03}").mkdir(parents=True)
    view = FolderManagerTreeView(roots=[str(root)], excluded=[])
    qtbot.addWidget(view)
    view.resize(600, 200)
    view.show()
    view.set_folders([str(root)])
    normalized = normalize_path(str(root))
    disk = DiskTree([normalized])
    disk.add(normalized, [f"{normalized}/d{number:03}" for number in range(300)], 1)
    for number in range(300):
        disk.add(f"{normalized}/d{number:03}", [], number)
    disk.finish()
    view.model_.disk = disk
    calls = []
    original = FolderStatsModel.data
    monkeypatch.setattr(FolderStatsModel, "data", lambda self, index, role=QtCore.Qt.DisplayRole: (calls.append(index.column()), original(self, index, role))[1])

    view.expand_path(normalized)
    for _ in range(5):
        view.model_.refresh_stats()
    QtWidgets.QApplication.processEvents()

    assert len([column for column in calls if column > 0]) < 100
    assert len(calls) < 1000
    view.close()


def test_folder_count_rule_uses_the_listing_before_children_are_walked(qtbot):
    model = FolderStatsModel([], [])
    disk = DiskTree(["D:/x"])
    disk.add("D:/x", ["D:/x/sub"], 0)
    model.disk = disk
    model.rule_counts = [(rule("Leaf", "#111111", ("folders", "==", 0)), {}), (rule("Parent", "#222222", ("folders", ">=", 1)), {})]

    assert model.badges("D:/x") == [("#222222", None)]


def test_expand_folders_calls_on_complete_after_the_last_batch(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(view_module, "EXPAND_RECURSIVE_BATCH_SIZE", 1)
    view, root = make_view(qtbot, tmp_path)
    done = []

    def on_complete():
        item = view.model_.path_item_map[path_of(root, "a")]
        done.append(view.isExpanded(view.model_.indexFromItem(item)))

    view.expand_folders([root, path_of(root, "a")], on_complete=on_complete)

    qtbot.waitUntil(lambda: bool(done))
    assert done == [True]


def test_expand_folders_without_folders_still_completes(qtbot, tmp_path):
    view, _root = make_view(qtbot, tmp_path)
    done = []

    view.expand_folders([], on_complete=lambda: done.append(True))

    assert done == [True]


def test_select_folders_selects_loaded_folders_and_skips_unknown_ones(qtbot, tmp_path, monkeypatch):
    view, root = make_view(qtbot, tmp_path)
    view.expand_folders([root])
    qtbot.waitUntil(lambda: path_of(root, "d") in view.model_.path_item_map)
    loaded = []
    monkeypatch.setattr(view.model_, "load_children", lambda item: loaded.append(item))
    scrolled = []
    monkeypatch.setattr(view, "scrollTo", lambda *args: scrolled.append(args))

    view.select_folders([path_of(root, "d"), path_of(root, "a"), path_of(root, "missing")])

    assert sorted(view.get_selected_paths()) == [path_of(root, "a"), path_of(root, "d")]
    assert view.current_path() == path_of(root, "d")
    assert len(scrolled) == 1
    assert loaded == []


def row_hidden(view, path):
    index = view.model_.indexFromItem(view.model_.path_item_map[path])
    return view.isRowHidden(index.row(), index.parent())


def test_row_filter_hides_loaded_rows_and_restores_only_those(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    view.expand_folders([root])
    qtbot.waitUntil(lambda: path_of(root, "d") in view.model_.path_item_map)

    view.apply_row_filter({root, path_of(root, "a")})

    assert row_hidden(view, path_of(root, "d"))
    assert not row_hidden(view, root) and not row_hidden(view, path_of(root, "a"))

    view.apply_row_filter({root, path_of(root, "d")})

    assert row_hidden(view, path_of(root, "a")) and not row_hidden(view, path_of(root, "d"))

    view.apply_row_filter(None)

    assert not row_hidden(view, path_of(root, "a")) and not row_hidden(view, path_of(root, "d"))


def test_rows_loaded_while_filtered_are_hidden(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    view.apply_row_filter({root, path_of(root, "a"), path_of(root, "a", "b")})

    view.expand_folders([root, path_of(root, "a")])

    qtbot.waitUntil(lambda: path_of(root, "a", "b") in view.model_.path_item_map)
    assert row_hidden(view, path_of(root, "d"))
    assert not row_hidden(view, path_of(root, "a")) and not row_hidden(view, path_of(root, "a", "b"))

    view.apply_row_filter(None)
    view.expand_folders([path_of(root, "a", "b")])
    qtbot.waitUntil(lambda: path_of(root, "a", "b", "c") in view.model_.path_item_map)
    assert not row_hidden(view, path_of(root, "a", "b", "c")) and not row_hidden(view, path_of(root, "d"))


def test_reloading_the_folders_keeps_filtering_the_new_rows(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    view.apply_row_filter({path_of(root, "x")})

    view.set_folders([root])

    assert row_hidden(view, root)
    view.apply_row_filter(None)
    assert not row_hidden(view, root)


def test_collapse_all_stops_expanding_and_collapses(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(view_module, "EXPAND_RECURSIVE_BATCH_SIZE", 1)
    view, root = make_view(qtbot, tmp_path)
    view.expand_folders([root])
    qtbot.waitUntil(lambda: view.isExpanded(view.model_.index(0, 0)))
    loaded = []
    original = view.load_paths_async
    monkeypatch.setattr(view, "load_paths_async", lambda paths, on_loaded, **kwargs: original(paths, lambda: (on_loaded(), loaded.append(list(paths))), **kwargs))

    view.expand_folders([path_of(root, "a"), path_of(root, "a", "b")])
    view.collapse_all()

    assert not view.isExpanded(view.model_.index(0, 0))
    qtbot.waitUntil(lambda: bool(loaded))
    for _ in range(20):
        QtCore.QCoreApplication.processEvents()
    assert loaded == [[path_of(root, "a")]]
    assert not any(view.isExpanded(view.model_.indexFromItem(item)) for item in view.model_.path_item_map.values())


def test_expand_channels_do_not_cancel_each_other_and_collapse_all_stops_both(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    done = []

    view.expand_folders([root], on_complete=lambda: done.append("expand"))
    view.expand_folders([root, path_of(root, "a")], on_complete=lambda: done.append("filter"), channel="filter")

    qtbot.waitUntil(lambda: sorted(done) == ["expand", "filter"])
    view.expand_folders([path_of(root, "a", "b")], on_complete=lambda: done.append("late expand"))
    view.expand_folders([path_of(root, "a", "b")], on_complete=lambda: done.append("late filter"), channel="filter")
    view.collapse_all()
    for _ in range(50):
        QtCore.QCoreApplication.processEvents()
    assert sorted(done) == ["expand", "filter"]


def placeholder_hidden(view, path):
    index = view.model_.indexFromItem(view.model_.path_item_map[path])
    assert not view.model_.index(0, 0, index).data(USER_ROLE_PATH)
    return view.isRowHidden(0, index)


def test_row_filter_hides_the_arrow_of_kept_folders_that_are_not_ancestors(qtbot, tmp_path):
    view, root = make_view(qtbot, tmp_path)
    view.expand_folders([root])
    qtbot.waitUntil(lambda: path_of(root, "a") in view.model_.path_item_map)

    view.apply_row_filter({root, path_of(root, "a")}, {root})
    assert placeholder_hidden(view, path_of(root, "a"))

    view.apply_row_filter({root, path_of(root, "a"), path_of(root, "a", "b")}, {root, path_of(root, "a")})
    assert not placeholder_hidden(view, path_of(root, "a"))

    view.apply_row_filter({root, path_of(root, "a")}, {root})
    view.apply_row_filter(None)
    assert not placeholder_hidden(view, path_of(root, "a"))

import os
import shutil
import threading

import pytest
from PySide6 import QtCore

from wafer.app.viewer.widgets.foldertree import LazyFolderTreeView
from wafer.builtins.filters import TextFilter
from wafer.builtins.folder_manager import widget as widget_module
from wafer.builtins.folder_manager.rules import Condition, HighlightRule
from wafer.builtins.folder_manager.rule_editor import describe_rule
from wafer.builtins.folder_manager.stats import DiskTree, FolderValues
from wafer.builtins.folder_manager.widget import FolderManagerWidget
from wafer.core.common.paths import normalize_path
from wafer.plugin.query.handler import filter_registry
from wafer.qt.commands.bridge import Menu
from wafer.qt.common import rate_limit
from wafer.qt.common.dpi import dpix

DEFAULT_COLUMNS = {"files": True, "all_files": True, "folders": True, "all_folders": False}


class QueryLog(list):
    sources: list[str] = []


@pytest.fixture
def query_calls(monkeypatch):
    filter_registry.register(TextFilter)
    calls = QueryLog()
    calls.sources = []
    lock = threading.Lock()

    def fake_query_sources(db_path, entries):
        with lock:
            calls.append([params.get("keywords") for _cls, params, _op in entries])
        return list(calls.sources)

    monkeypatch.setattr(widget_module, "query_sources", fake_query_sources)
    monkeypatch.setattr(widget_module, "RULE_EDIT_DELAY_MS", 0)
    return calls


@pytest.fixture
def immediate_debounce(monkeypatch):
    monkeypatch.setattr(rate_limit.qt_debounce_manager, "debounce", lambda key, delay, callback, *args, **kwargs: callback(*args, **kwargs))


def make_folders(base, layout):
    for relative, files in layout.items():
        folder = base / relative if relative else base
        folder.mkdir(parents=True, exist_ok=True)
        for number in range(files):
            (folder / f"f{number}.png").write_bytes(b"x")
    return normalize_path(str(base))


def make_panel(qtbot, width=600, height=500):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.resize(width, height)
    panel.show()
    qtbot.waitExposed(panel)
    return panel


def make_tree(qtbot):
    tree = LazyFolderTreeView(instance_name="FolderManagerTestSourceTree")
    qtbot.addWidget(tree)
    return tree


def bind(qtbot, panel, roots):
    tree = make_tree(qtbot)
    panel.bind_folder_tree(tree, lambda: "test.db")
    tree.set_folders(roots)
    qtbot.waitUntil(lambda: panel.model.disk is not None and panel.model.disk.finished and not panel.scanning, timeout=5000)
    return tree


def watch_finish(monkeypatch, disk):
    calls = []
    real_finish = disk.finish
    monkeypatch.setattr(disk, "finish", lambda: calls.append(1) or real_finish())
    return calls


def fresh_totals(disk):
    fresh = DiskTree(disk.roots)
    for path, (child_dirs, file_count) in disk.nodes.items():
        fresh.add(path, child_dirs, file_count)
    fresh.finish()
    return fresh.totals


def rule_dict(name, color, bars=(), conditions=(("files", ">=", 1),), enabled=True):
    return HighlightRule(name, color, enabled=enabled, bars=list(bars), conditions=[Condition(*c) for c in conditions]).to_dict()


def text_bar(text):
    return {"filter": "text", "params": {"keywords": text}, "op": None, "enabled": True}


def test_state_round_trip_keeps_rules_and_columns(qtbot):
    state = {
        "rules": [
            rule_dict("Mixed", "#1D9E75", conditions=(("files", ">=", 1), ("folders", ">=", 1))),
            rule_dict("Cats", "#D85A30", bars=[text_bar("cat")], conditions=(("all_files", "<=", 3),), enabled=False),
        ],
        "columns": {"files": False, "all_files": True, "folders": True, "all_folders": True},
    }
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.restore_state(state)
    assert panel.save_state() == state
    assert panel.view.isColumnHidden(1) and not panel.view.isColumnHidden(4)

    other = FolderManagerWidget()
    qtbot.addWidget(other)
    other.restore_state(panel.save_state())
    assert other.save_state() == state
    assert [rule.name for rule in other.rules] == ["Mixed", "Cats"]


def test_empty_state_starts_with_mixed_and_default_columns(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.restore_state({})
    assert [rule.name for rule in panel.rules] == ["Mixed"]
    assert panel.save_state()["columns"] == DEFAULT_COLUMNS
    assert [panel.view.isColumnHidden(column) for column in (1, 2, 3, 4)] == [False, False, False, True]


def test_restore_skips_malformed_rules_and_keeps_a_deliberate_empty_list(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.restore_state({"rules": [{"color": "#000000"}, rule_dict("Kept", "#378ADD")]})
    assert [rule.name for rule in panel.rules] == ["Kept"]
    panel.restore_state({"rules": []})
    assert panel.rules == []
    panel.restore_state({"rules": [{"name": "Odd", "color": "#000", "bars": ["text", {"filter": "text", "params": "x"}]}], "columns": "all"})
    assert [rule.name for rule in panel.rules] == ["Odd"] and panel.rules[0].bars == []
    assert panel.save_state()["columns"] == DEFAULT_COLUMNS
    panel.restore_state({"rules": "Mixed"})
    assert [rule.name for rule in panel.rules] == ["Mixed"]


def test_summary_of_an_empty_query_reads_every_file():
    rule = HighlightRule("Mixed", "#000", conditions=[Condition("files", ">=", 1), Condition("folders", ">=", 1)])
    assert describe_rule(rule) == "Every file · Files ≥ 1 and Folders ≥ 1"


def test_scan_fills_disk_counts(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"": 1, "a": 2, "b": 1, "b/c": 3})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    assert disk.values(root) == FolderValues(1, 7, 2, 3)
    assert disk.values(f"{root}/b") == FolderValues(1, 4, 1, 1)
    assert panel.status_label.isHidden()
    assert panel.view.model_.index(0, 2).data() == "7"


def test_switching_folders_discards_the_running_scan(qtbot, tmp_path, monkeypatch, query_calls):
    first = make_folders(tmp_path / "first", {"": 1, "x": 1})
    second = make_folders(tmp_path / "second", {"": 2, "y": 1})
    real_walk = widget_module.walk_disk
    release = threading.Event()
    delivered = threading.Event()

    def slow_walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size=256):
        if list(roots) == [first]:
            release.wait(5)
            on_batch([(first, [f"{first}/x"], 1), (f"{first}/x", [], 1)])
            delivered.set()
            return
        real_walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size)

    monkeypatch.setattr(widget_module, "walk_disk", slow_walk)
    panel = make_panel(qtbot)
    tree = make_tree(qtbot)
    panel.bind_folder_tree(tree, lambda: "test.db")
    tree.set_folders([first])
    qtbot.waitUntil(lambda: panel.scanning)
    tree.set_folders([second])
    qtbot.waitUntil(lambda: panel.model.disk.finished and not panel.scanning, timeout=5000)
    release.set()
    qtbot.waitUntil(delivered.is_set, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert set(panel.model.disk.nodes) == {second, f"{second}/y"}
    assert panel.model.disk.finished
    assert panel.model.disk.values(second) == FolderValues(2, 3, 1, 1)


def test_editing_one_rule_recounts_only_that_rule(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"": 1})
    panel = make_panel(qtbot)
    panel.restore_state({"rules": [rule_dict("One", "#1D9E75", bars=[text_bar("dog")]), rule_dict("Two", "#D85A30", bars=[text_bar("cat")])]})
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)
    assert sorted(query_calls) == [["cat"], ["dog"]]

    row = panel.rule_list.rows[1]
    row.set_expanded(True)
    row.search.apply_bars([text_bar("bird")])
    qtbot.waitUntil(lambda: len(query_calls) == 3, timeout=5000)
    assert query_calls[2] == ["bird"]
    assert panel.rules[1].bars[0]["params"]["keywords"] == "bird"

    assert not row.search.sortable and not row.search._sort_button.isVisibleTo(row.search)

    panel.rules[0].conditions[0].value = 2
    panel.rule_list.rows[0].emit_edited()
    disabled = panel.rules[1]
    assert id(disabled) in panel.counts
    row.enabled_check.setChecked(False)
    qtbot.waitUntil(lambda: id(disabled) not in panel.counts, timeout=5000)
    assert len(query_calls) == 3


def test_files_changed_rescans_only_parent_folders(qtbot, tmp_path, monkeypatch, query_calls, immediate_debounce):
    root = make_folders(tmp_path / "root", {"a": 1, "b": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1, timeout=5000)
    finishes = watch_finish(monkeypatch, panel.model.disk)
    listed = []
    real_list = widget_module.list_folder
    monkeypatch.setattr(widget_module, "list_folder", lambda path, *args: listed.append(path) or real_list(path, *args))
    (tmp_path / "root" / "a" / "new.png").write_bytes(b"x")
    (tmp_path / "root" / "b" / "unreported.png").write_bytes(b"x")

    panel.on_files_changed("", {"modified": [f"{root}/a/new.png"], "removed": []})
    qtbot.waitUntil(lambda: panel.model.disk.values(f"{root}/a").files == 2, timeout=5000)
    assert listed == [f"{root}/a"]
    assert panel.model.disk.finished and finishes == []
    assert panel.model.disk.totals == fresh_totals(panel.model.disk)
    assert panel.model.disk.values(root) == FolderValues(0, 3, 2, 2)
    assert panel.model.disk.values(f"{root}/b").files == 1
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)


def test_a_file_in_a_new_folder_adds_that_folder(qtbot, tmp_path, monkeypatch, query_calls, immediate_debounce):
    root = make_folders(tmp_path / "root", {"a": 1, "b": 1, "b/old": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    finishes = watch_finish(monkeypatch, disk)
    walked = []
    real_walk = widget_module.walk_disk
    monkeypatch.setattr(widget_module, "walk_disk", lambda roots, *args: walked.append(list(roots)) or real_walk(roots, *args))
    make_folders(tmp_path / "root" / "a" / "2026-11" / "sub", {"": 2})

    panel.on_files_changed("", {"modified": [f"{root}/a/2026-11/sub/f0.png", f"{root}/a/2026-11/sub/f1.png"], "removed": []})
    qtbot.waitUntil(lambda: disk.values(f"{root}/a/2026-11/sub") is not None and not panel.scanning, timeout=5000)
    assert walked == [[f"{root}/a/2026-11"]]
    assert disk.values(f"{root}/a") == FolderValues(1, 3, 1, 2)
    assert disk.values(root) == FolderValues(0, 5, 2, 5)
    assert disk.finished and finishes == []
    assert disk.totals == fresh_totals(disk)

    shutil.rmtree(tmp_path / "root" / "b" / "old")
    panel.on_files_changed("", {"modified": [], "removed": [f"{root}/b/old/f0.png"]})
    qtbot.waitUntil(lambda: disk.values(f"{root}/b/old") is None, timeout=5000)
    assert disk.values(f"{root}/b") == FolderValues(1, 1, 0, 0)
    assert disk.totals == fresh_totals(disk) and finishes == []


def test_parents_on_the_current_drive_root_stay_on_that_drive(qtbot):
    root = os.path.splitdrive(os.getcwd())[0] + "/"
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.model.roots = [root]
    panel.model.disk = DiskTree([root])
    panel.model.disk.add(root, [f"{root}a"], 1)
    panel.model.disk.add(f"{root}a", [], 0)
    panel.model.disk.finish()
    panel.on_files_changed("", {"modified": [f"{root}file.png", f"{root}a/new/deep/f.png"], "removed": []})
    assert panel.stale_parents == {root, f"{root}a/new/deep"}
    assert panel.nearest_known(f"{root}a/new/deep") == f"{root}a"
    assert panel.nearest_known(f"{root}never/listed") == root
    panel.model.disk = DiskTree([root])
    assert panel.nearest_known(f"{root}a/b") is None


def test_notifications_for_another_db_are_ignored(qtbot, tmp_path, query_calls, immediate_debounce):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1, timeout=5000)
    panel.on_db_content_updated("some_other_db")
    QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 1
    panel.on_db_content_updated("")
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)


def test_hidden_panel_waits_until_shown(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    tree = make_tree(qtbot)
    panel.bind_folder_tree(tree, lambda: "test.db")
    tree.set_folders([root])
    QtCore.QCoreApplication.processEvents()
    assert panel.model.disk is None and query_calls == []
    panel.show()
    qtbot.waitUntil(lambda: panel.model.disk is not None and panel.model.disk.finished and len(query_calls) == 1, timeout=5000)


def test_moving_inside_a_root_rescans_that_folder(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1, "a/b": 2})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    finishes = watch_finish(monkeypatch, disk)
    (tmp_path / "root" / "a" / "b" / "c").mkdir()
    (tmp_path / "root" / "a" / "b" / "c" / "f.png").write_bytes(b"x")

    panel.model.paths_changed.emit([f"{root}/a"])
    assert disk.finished and disk.values(root) == FolderValues(0, 3, 1, 2)
    qtbot.waitUntil(lambda: not panel.scanning and disk.values(root).all_folders == 3, timeout=5000)
    assert panel.model.disk is disk and disk.finished and finishes == []
    assert disk.values(f"{root}/a") == FolderValues(1, 4, 1, 2)
    assert disk.totals == fresh_totals(disk)

    panel.model.paths_changed.emit([normalize_path(str(tmp_path))])
    qtbot.waitUntil(lambda: panel.model.disk is not disk and panel.model.disk.finished, timeout=5000)


def test_expand_to_matches_collects_badged_folders(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 1, "a": 1, "a/b": 1, "c": 0})
    query_calls.sources = [f"{root}/f0.png", f"{root}/a/f0.png", f"{root}/a/b/f0.png"]
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: bool(panel.model.badges(root)), timeout=5000)
    expanded = []
    monkeypatch.setattr(panel.view, "expand_to", lambda paths: expanded.append(sorted(paths)))
    panel.expand_button.click()
    qtbot.waitUntil(lambda: bool(expanded), timeout=5000)
    assert expanded == [sorted([root, f"{root}/a"])]


def test_column_menu_toggles_columns(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.set_column_visible("all_folders", True)
    panel.set_column_visible("files", False)
    assert panel.save_state()["columns"] == {"files": False, "all_files": True, "folders": True, "all_folders": True}
    assert panel.view.isColumnHidden(1) and not panel.view.isColumnHidden(4)
    assert len([item for item in panel.column_menu_items() if not isinstance(item, str)]) == 4
    assert Menu.session(panel).menu(panel.column_menu_items()).build() is not None


def test_add_and_remove_rule_updates_the_model(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.add_rule_button.click()
    assert [rule.name for rule in panel.rules] == ["Mixed", "Rule 1"]
    assert [rule.name for rule, _counts in panel.model.rule_counts] == ["Mixed", "Rule 1"]
    panel.rule_list.move_rule(1, 0)
    assert [rule.name for rule, _counts in panel.model.rule_counts] == ["Rule 1", "Mixed"]
    panel.rule_list.rows[0].remove_button.click()
    assert [rule.name for rule, _counts in panel.model.rule_counts] == ["Mixed"]


def test_panel_bar_stays_one_row(qtbot):
    panel = make_panel(qtbot)
    panel.scanning = True
    panel.update_status()
    row = panel.flow.single_line_size()
    panel.resize(row.width() + dpix(30), 600)
    qtbot.waitUntil(lambda: panel.bar.width() >= row.width(), timeout=2000)
    assert panel.bar.height() <= row.height() + dpix(4)
    used = panel.bar.height() + panel.rules_area.height()
    assert panel.view.height() >= panel.height() - used - dpix(24)
    assert panel.view.width() >= panel.width() - dpix(24)


def test_panel_can_be_made_short(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    assert panel.minimumSizeHint().height() <= dpix(150)

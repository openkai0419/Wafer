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
from wafer.builtins.folder_manager.widget import FolderManagerPlugin, FolderManagerWidget
from wafer.core.common.paths import normalize_path
from wafer.plugin.query.handler import filter_registry
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.commands.bridge import Menu
from wafer.qt.common import rate_limit
from wafer.qt.common.dpi import dpix

DEFAULT_COLUMNS = {"files": True, "all_files": True, "folders": True, "all_folders": False}
REAL_FINISH = DiskTree.finish


class QueryLog(list):
    sources: list[str] = []


@pytest.fixture
def text_filter_registered():
    filter_registry.register(TextFilter)
    return TextFilter


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
def immediate_flush(monkeypatch):
    monkeypatch.setattr(rate_limit._qt_throttle_manager, "throttle", lambda key, throttle_ms, idle_ms, callback, *args, **kwargs: callback(*args, **kwargs))


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


@pytest.fixture
def finish_threads(monkeypatch):
    threads = []
    real_finish = DiskTree.finish

    def finish(self):
        threads.append(threading.current_thread())
        real_finish(self)

    monkeypatch.setattr(DiskTree, "finish", finish)
    return threads


def finished_on_main(threads):
    return [thread for thread in threads if thread is threading.main_thread()]


def gated_walk(monkeypatch, gated_roots):
    real_walk = widget_module.walk_disk
    release = threading.Event()
    delivered = threading.Event()

    def walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size=256):
        if list(roots) != gated_roots:
            return real_walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size)

        def deliver_then_wait(batch):
            on_batch(batch)
            delivered.set()
            release.wait(5)

        real_walk(roots, excluded, ignore_pattern_re, cancel, deliver_then_wait, 1)

    monkeypatch.setattr(widget_module, "walk_disk", walk)
    return release, delivered


def fresh_totals(disk):
    fresh = DiskTree(disk.roots)
    for path, (child_dirs, file_count) in disk.nodes.items():
        fresh.add(path, child_dirs, file_count)
    REAL_FINISH(fresh)
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


def test_summary_of_a_query_that_matches_every_file_reads_every_file(text_filter_registered):
    blank = {"filter": "text", "params": {"keys": ["path"], "keywords": ""}, "op": None, "enabled": True}
    rule = HighlightRule("Blank", "#000", bars=[blank], conditions=[Condition("files", ">=", 1)])
    assert describe_rule(rule) == "Every file · Files ≥ 1"
    rule.bars = [{**blank, "params": {"keys": ["path"], "keywords": "cat"}}]
    assert describe_rule(rule) == 'Text "cat" · Files ≥ 1'


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


def test_full_scan_totals_are_computed_off_the_main_thread_and_swapped_in(qtbot, tmp_path, query_calls, finish_threads):
    root = make_folders(tmp_path / "root", {"": 1, "a": 2, "a/b": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    assert finish_threads and finished_on_main(finish_threads) == []
    first = panel.model.disk
    swapped = []
    panel.model.stats_changed.connect(lambda: swapped.append(panel.model.disk))

    panel.refresh()
    assert panel.model.disk is first and first.values(root) == FolderValues(1, 4, 1, 2)
    qtbot.waitUntil(lambda: not panel.scanning, timeout=5000)
    assert panel.model.disk is not first and panel.model.disk.finished
    assert panel.model.disk.values(root) == FolderValues(1, 4, 1, 2)
    assert finished_on_main(finish_threads) == []
    assert all(disk is first for disk in swapped[:-1])
    qtbot.waitUntil(lambda: first.nodes == {}, timeout=5000)


def test_a_rescan_keeps_the_previous_counts_until_it_ends(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 1, "a": 2})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    first = panel.model.disk
    release, delivered = gated_walk(monkeypatch, [root])
    (tmp_path / "root" / "new.png").write_bytes(b"x")

    panel.refresh()
    qtbot.waitUntil(delivered.is_set, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert panel.scanning and panel.model.disk is first
    assert panel.view.model_.index(0, 2).data() == "3"
    release.set()
    qtbot.waitUntil(lambda: not panel.scanning, timeout=5000)
    assert panel.model.disk.values(root) == FolderValues(2, 4, 1, 1)


def test_the_first_scan_shows_direct_counts_while_walking(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 3, "a": 2})
    release, delivered = gated_walk(monkeypatch, [root])
    panel = make_panel(qtbot)
    tree = make_tree(qtbot)
    panel.bind_folder_tree(tree, lambda: "test.db")
    tree.set_folders([root])
    qtbot.waitUntil(lambda: panel.model.disk is not None and panel.model.disk.values(root) is not None, timeout=5000)
    assert panel.model.disk.values(root) == FolderValues(3, -1, 1, -1)
    release.set()
    qtbot.waitUntil(lambda: not panel.scanning, timeout=5000)
    assert panel.model.disk.values(root) == FolderValues(3, 5, 1, 1)


def test_files_changed_rescans_only_parent_folders(qtbot, tmp_path, monkeypatch, query_calls, immediate_flush, finish_threads):
    root = make_folders(tmp_path / "root", {"a": 1, "b": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1, timeout=5000)
    finish_threads.clear()
    listed = []
    real_list = widget_module.list_folder
    monkeypatch.setattr(widget_module, "list_folder", lambda path, *args: listed.append(path) or real_list(path, *args))
    (tmp_path / "root" / "a" / "new.png").write_bytes(b"x")
    (tmp_path / "root" / "b" / "unreported.png").write_bytes(b"x")

    panel.on_files_changed("", {"modified": [f"{root}/a/new.png"], "removed": []})
    qtbot.waitUntil(lambda: panel.model.disk.values(f"{root}/a").files == 2, timeout=5000)
    assert listed == [f"{root}/a"]
    assert panel.model.disk.finished and finish_threads == []
    assert panel.model.disk.totals == fresh_totals(panel.model.disk)
    assert panel.model.disk.values(root) == FolderValues(0, 3, 2, 2)
    assert panel.model.disk.values(f"{root}/b").files == 1
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)


def test_a_file_in_a_new_folder_adds_that_folder(qtbot, tmp_path, monkeypatch, query_calls, immediate_flush, finish_threads):
    root = make_folders(tmp_path / "root", {"a": 1, "b": 1, "b/old": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    walked = []
    real_walk = widget_module.walk_disk
    monkeypatch.setattr(widget_module, "walk_disk", lambda roots, *args: walked.append(list(roots)) or real_walk(roots, *args))
    make_folders(tmp_path / "root" / "a" / "2026-11" / "sub", {"": 2})

    panel.on_files_changed("", {"modified": [f"{root}/a/2026-11/sub/f0.png", f"{root}/a/2026-11/sub/f1.png"], "removed": []})
    qtbot.waitUntil(lambda: disk.values(f"{root}/a/2026-11/sub") is not None and not panel.scanning, timeout=5000)
    assert walked == [[f"{root}/a/2026-11"]]
    assert disk.values(f"{root}/a") == FolderValues(1, 3, 1, 2)
    assert disk.values(root) == FolderValues(0, 5, 2, 5)
    assert disk.finished and finished_on_main(finish_threads) == []
    assert disk.totals == fresh_totals(disk)

    shutil.rmtree(tmp_path / "root" / "b" / "old")
    panel.on_files_changed("", {"modified": [], "removed": [f"{root}/b/old/f0.png"]})
    qtbot.waitUntil(lambda: disk.values(f"{root}/b/old") is None, timeout=5000)
    assert disk.values(f"{root}/b") == FolderValues(1, 1, 0, 0)
    assert disk.totals == fresh_totals(disk) and finished_on_main(finish_threads) == []


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


def test_notifications_for_another_db_are_ignored(qtbot, tmp_path, query_calls, immediate_flush):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1, timeout=5000)
    panel.on_db_content_updated("some_other_db")
    QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 1
    panel.on_db_content_updated("")
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)


def test_updates_during_a_count_queue_one_more_count(qtbot, tmp_path, monkeypatch, query_calls, immediate_flush):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)
    started = threading.Event()
    release = threading.Event()
    tokens = []
    real_count = widget_module.count_sources_by_folder

    def slow_count(sources, roots, cancel):
        tokens.append(cancel)
        started.set()
        release.wait(5)
        return real_count(sources, roots, cancel)

    monkeypatch.setattr(widget_module, "count_sources_by_folder", slow_count)
    panel.on_db_content_updated("")
    qtbot.waitUntil(started.is_set, timeout=5000)
    for _ in range(5):
        panel.on_db_content_updated("")
        QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 2
    assert not tokens[0].is_cancelled()
    release.set()
    qtbot.waitUntil(lambda: len(query_calls) == 3 and not panel.counting, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 3


def test_editing_a_rule_restarts_its_running_count(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)
    started = threading.Event()
    release = threading.Event()
    tokens = []
    real_count = widget_module.count_sources_by_folder

    def slow_count(sources, roots, cancel):
        tokens.append(cancel)
        if len(tokens) == 1:
            started.set()
            release.wait(5)
        return real_count(sources, roots, cancel)

    monkeypatch.setattr(widget_module, "count_sources_by_folder", slow_count)
    rule = panel.rules[0]
    panel.recount([rule])
    qtbot.waitUntil(started.is_set, timeout=5000)
    rule.bars = [text_bar("cat")]
    panel.recount([rule])
    assert tokens[0].is_cancelled()
    release.set()
    qtbot.waitUntil(lambda: len(tokens) == 2 and not panel.counting, timeout=5000)
    assert id(rule) in panel.counts


def test_a_burst_of_updates_recounts_once_per_interval(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)
    for _ in range(4):
        panel.on_db_content_updated("")
        qtbot.waitUntil(lambda: not panel.counting, timeout=5000)
        QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 2


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


def test_renaming_a_folder_walks_only_the_renamed_folder(qtbot, tmp_path, monkeypatch, query_calls, finish_threads):
    root = make_folders(tmp_path / "root", {"a": 1, "a/b": 2, "a/b/c": 1, "d": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    walked, listed = [], []
    real_walk = widget_module.walk_disk
    real_list = widget_module.list_folder
    monkeypatch.setattr(widget_module, "walk_disk", lambda roots, *args: walked.append(list(roots)) or real_walk(roots, *args))
    monkeypatch.setattr(widget_module, "list_folder", lambda path, *args: listed.append(path) or real_list(path, *args))
    (tmp_path / "root" / "a").rename(tmp_path / "root" / "renamed")

    panel.model.paths_changed.emit([root])
    qtbot.waitUntil(lambda: disk.values(f"{root}/renamed") is not None and not panel.scanning, timeout=5000)
    qtbot.waitUntil(lambda: not disk.orphans, timeout=5000)
    assert listed == [root]
    assert walked == [[f"{root}/renamed"]]
    assert panel.model.disk is disk and disk.finished
    assert disk.values(f"{root}/a") is None and disk.values(f"{root}/a/b/c") is None
    assert disk.values(root) == FolderValues(0, 5, 2, 4)
    assert disk.values(f"{root}/renamed") == FolderValues(1, 4, 1, 2)
    assert disk.totals == fresh_totals(disk)
    assert finished_on_main(finish_threads) == []


def test_moving_a_folder_relists_both_parents(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"a/b": 2, "d": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    walked = []
    real_walk = widget_module.walk_disk
    monkeypatch.setattr(widget_module, "walk_disk", lambda roots, *args: walked.append(list(roots)) or real_walk(roots, *args))
    (tmp_path / "root" / "a" / "b").rename(tmp_path / "root" / "d" / "b")

    panel.model.paths_changed.emit([f"{root}/a", f"{root}/d"])
    qtbot.waitUntil(lambda: disk.values(f"{root}/d/b") is not None and not panel.scanning, timeout=5000)
    assert walked == [[f"{root}/d/b"]]
    assert disk.values(f"{root}/a") == FolderValues(0, 0, 0, 0)
    assert disk.values(f"{root}/d") == FolderValues(1, 3, 1, 1)
    assert disk.totals == fresh_totals(disk)


def test_a_second_change_keeps_the_parents_of_the_first(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1, "b": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    real_list = widget_module.list_folder
    entered = threading.Event()
    release = threading.Event()

    def list_folder(path, *args):
        if path == f"{root}/a" and not entered.is_set():
            entered.set()
            release.wait(5)
        return real_list(path, *args)

    monkeypatch.setattr(widget_module, "list_folder", list_folder)
    (tmp_path / "root" / "a" / "x.png").write_bytes(b"x")
    (tmp_path / "root" / "b" / "y.png").write_bytes(b"x")

    panel.model.paths_changed.emit([f"{root}/a"])
    qtbot.waitUntil(entered.is_set, timeout=5000)
    panel.model.paths_changed.emit([f"{root}/b"])
    release.set()
    qtbot.waitUntil(lambda: disk.values(f"{root}/a").files == 2 and disk.values(f"{root}/b").files == 2, timeout=5000)


def test_changes_outside_the_roots_are_ignored(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    disk = panel.model.disk
    panel.model.paths_changed.emit([normalize_path(str(tmp_path))])
    QtCore.QCoreApplication.processEvents()
    assert panel.model.disk is disk and not panel.scanning


def test_expand_to_matches_collects_badged_folders(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 1, "a": 1, "a/b": 1, "c": 0})
    query_calls.sources = [f"{root}/f0.png", f"{root}/a/f0.png", f"{root}/a/b/f0.png"]
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: bool(panel.model.badges(root)), timeout=5000)
    expanded = []
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders: expanded.append(list(folders)))
    panel.expand_button.click()
    qtbot.waitUntil(lambda: bool(expanded), timeout=5000)
    assert expanded == [[root]]


def test_expand_to_matches_scans_in_slices_and_finds_ancestors_off_the_main_thread(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 1, "a": 1, "a/b": 1, "a/b/c": 1, "a/b/c/d": 0})
    query_calls.sources = [f"{root}/f0.png", f"{root}/a/f0.png", f"{root}/a/b/f0.png", f"{root}/a/b/c/f0.png"]
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: bool(panel.model.badges(f"{root}/a/b/c")), timeout=5000)
    monkeypatch.setattr(widget_module, "EXPAND_SLICE_SECONDS", -1)
    monkeypatch.setattr(widget_module, "EXPAND_DEADLINE_CHECK", 1)
    threads = []
    real_folders_to_open = widget_module.folders_to_open
    monkeypatch.setattr(widget_module, "folders_to_open", lambda *args: threads.append(threading.current_thread()) or real_folders_to_open(*args))
    expanded = []
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders: expanded.append(list(folders)))
    cached = len(panel.model.values_cache)

    panel.expand_to_matches()
    assert expanded == [] and threads == []
    qtbot.waitUntil(lambda: bool(expanded), timeout=5000)
    assert expanded == [[root, f"{root}/a", f"{root}/a/b"]]
    assert threads and threading.main_thread() not in threads
    assert len(panel.model.values_cache) == cached

    panel.expand_to_matches()
    panel.expand_to_matches()
    qtbot.waitUntil(lambda: len(expanded) == 2, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert len(expanded) == 2


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


class HostWindow:
    def __init__(self, folder_view, database_path):
        self.folder_view = folder_view
        self.database_path = database_path


def test_plugin_keeps_state_until_the_widget_exists(qtbot):
    plugin = FolderManagerPlugin()
    plugin.restore_ui_state({"rules": [], "columns": {"files": False}})
    widget = plugin.create_widget()
    qtbot.addWidget(widget)
    assert widget.rules == []
    assert widget.columns["files"] is False
    assert plugin.save_ui_state()["columns"]["files"] is False


def test_plugin_without_host_window_creates_unbound_widget(qtbot, monkeypatch):
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: None)
    widget = FolderManagerPlugin().create_widget()
    qtbot.addWidget(widget)
    assert widget.source_tree is None


def test_plugin_binds_host_folder_tree_and_db_path(qtbot, monkeypatch):
    tree = make_tree(qtbot)
    host = HostWindow(tree, "db.sqlite")
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: host)
    widget = FolderManagerPlugin().create_widget()
    qtbot.addWidget(widget)
    assert widget.source_tree is tree
    assert widget.db_path_getter() == "db.sqlite"
    host.database_path = "other.sqlite"
    assert widget.db_path_getter() == "other.sqlite"

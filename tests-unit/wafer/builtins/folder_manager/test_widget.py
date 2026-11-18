import os
import shutil
import threading

import pytest
from PySide6 import QtCore

from wafer.builtins.filters import TextFilter
from wafer.builtins.folder_manager import widget as widget_module
from wafer.builtins.folder_manager.database import FolderSettings
from wafer.builtins.folder_manager.rules import Condition, HighlightRule
from wafer.builtins.folder_manager.rule_editor import describe_rule
from wafer.builtins.folder_manager.shared_settings import COLUMNS_KEY, DATABASE_KEY, RULES_KEY, load_columns, load_last_database, load_rules, save_last_database
from wafer.builtins.folder_manager.stats import DiskTree, FolderValues
from wafer.builtins.folder_manager.widget import FolderManagerPlugin, FolderManagerWidget
from wafer.core.common.paths import data_db_path, normalize_path
from wafer.core.store.settings import app_settings
from wafer.plugin.query.handler import filter_registry
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.commands.bridge import Menu
from wafer.qt.common import rate_limit
from wafer.qt.common.dpi import dpix

DEFAULT_COLUMNS = {"files": True, "all_files": True, "folders": True, "all_folders": False}
REAL_FINISH = DiskTree.finish
SERVED: dict[str, FolderSettings] = {}
GATES: list[threading.Event] = []


class QueryLog(list):
    sources: list[str] = []


def clear_shared_settings() -> None:
    app_settings.discard()
    for key in (RULES_KEY, COLUMNS_KEY, DATABASE_KEY):
        app_settings.settings.remove(key)
    app_settings.settings.sync()


@pytest.fixture(autouse=True)
def clean_shared_settings():
    clear_shared_settings()
    yield
    clear_shared_settings()


@pytest.fixture(autouse=True)
def release_gates():
    yield
    for event in GATES:
        event.set()
    GATES.clear()


def gate() -> threading.Event:
    event = threading.Event()
    GATES.append(event)
    return event


@pytest.fixture(autouse=True)
def served_folders(monkeypatch):
    SERVED.clear()
    reads = []

    def read(name):
        reads.append((name, threading.current_thread()))
        return SERVED.get(name, FolderSettings([], set(), None))

    monkeypatch.setattr(widget_module, "read_folder_settings", read)
    yield reads
    SERVED.clear()


@pytest.fixture
def immediate_save(monkeypatch):
    monkeypatch.setattr(FolderManagerWidget, "save_rules_later", FolderManagerWidget.save_rules_now)
    monkeypatch.setattr(FolderManagerWidget, "save_columns_later", FolderManagerWidget.save_columns_now)


@pytest.fixture
def saved_rules(monkeypatch):
    saved = []
    monkeypatch.setattr(widget_module, "save_rules", lambda rules: saved.append([rule.name for rule in rules]))
    return saved


@pytest.fixture
def saved_columns(monkeypatch):
    saved = []
    monkeypatch.setattr(widget_module, "save_columns", lambda columns: saved.append(dict(columns)))
    return saved


class FakeBridge:
    class Signal:
        def connect(self, slot):
            pass

    def __init__(self):
        self.db_content_updated = self.files_changed = self.folder_changed = self.Signal()


def without_viewer(monkeypatch):
    monkeypatch.setattr(widget_module.ViewerIpcBridge, "instance", staticmethod(lambda: None))


def in_viewer(monkeypatch):
    bridge = FakeBridge()
    monkeypatch.setattr(widget_module.ViewerIpcBridge, "instance", staticmethod(lambda: bridge))


@pytest.fixture(autouse=True)
def viewer_bridge(monkeypatch):
    in_viewer(monkeypatch)


def activate(panel):
    QtCore.QCoreApplication.sendEvent(panel, QtCore.QEvent(QtCore.QEvent.ActivationChange))


@pytest.fixture
def committed():
    sent = []
    app_settings.committed.connect(sent.append)
    yield sent
    app_settings.committed.disconnect(sent.append)


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


def serve(name, roots, excluded=None, pattern=None):
    SERVED[name] = FolderSettings(list(roots), set(excluded or ()), pattern)


def scanned(panel, roots):
    disk = panel.model.disk
    return list(panel.model.roots or ()) == list(roots) and disk is not None and disk.finished and not panel.scanning


def bind(qtbot, panel, roots):
    serve("test", roots)
    panel.set_database("test")
    qtbot.waitUntil(lambda: scanned(panel, roots), timeout=5000)


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
    release = gate()
    delivered = gate()

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


def test_a_fresh_panel_starts_with_mixed_and_default_columns(qtbot):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    assert [rule.name for rule in panel.rules] == ["Mixed"]
    assert panel.columns == DEFAULT_COLUMNS
    assert [panel.view.isColumnHidden(column) for column in (1, 2, 3, 4)] == [False, False, False, True]
    assert not hasattr(panel, "save_state") and not hasattr(panel, "restore_state")


def test_a_new_panel_reads_the_shared_rules_and_columns(qtbot):
    app_settings.save_immediate(RULES_KEY, [rule_dict("Cats", "#D85A30", bars=[text_bar("cat")])])
    app_settings.save_immediate(COLUMNS_KEY, {"files": False, "all_folders": True})
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    assert [rule.name for rule in panel.rules] == ["Cats"]
    assert panel.view.isColumnHidden(1) and not panel.view.isColumnHidden(4)


def test_rule_edits_are_saved_to_shared_settings(qtbot, immediate_save):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)

    panel.add_rule_button.click()
    assert [rule.name for rule in load_rules()] == ["Mixed", "Rule 1"]

    panel.rules[1].name = "Renamed"
    panel.rule_list.rows[1].emit_edited()
    assert [rule.name for rule in load_rules()] == ["Mixed", "Renamed"]

    panel.rule_list.move_rule(1, 0)
    assert [rule.name for rule in load_rules()] == ["Renamed", "Mixed"]

    panel.rule_list.rows[0].remove_button.click()
    assert [rule.name for rule in load_rules()] == ["Mixed"]

    panel.toggle_column("all_folders")
    assert load_columns()["all_folders"] is True and not panel.view.isColumnHidden(4)


def test_rule_edits_are_saved_once_after_a_pause(qtbot, monkeypatch, saved_rules):
    monkeypatch.setattr(widget_module, "SAVE_DELAY_MS", 0)
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    for _ in range(3):
        panel.rule_list.rows[0].emit_edited()
    assert saved_rules == []
    qtbot.waitUntil(lambda: saved_rules == [["Mixed"]], timeout=2000)
    QtCore.QCoreApplication.processEvents()
    assert saved_rules == [["Mixed"]]


def test_an_edit_right_before_closing_the_window_is_saved(qtbot, saved_rules, saved_columns):
    from wafer.qt.layout.standalone import open_standalone

    panel = open_standalone(FolderManagerWidget, "Folder Manager", "folder_manager_close_test")
    qtbot.waitExposed(panel)
    panel.add_rule_button.click()
    panel.toggle_column("all_folders")
    assert saved_rules == [] and saved_columns == []

    panel.window().close()

    assert saved_rules == [["Mixed", "Rule 1"]]
    assert saved_columns and saved_columns[-1]["all_folders"] is True


def test_pending_saves_are_written_when_the_app_quits(qtbot, saved_rules):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.add_rule_button.click()

    QtCore.QCoreApplication.instance().aboutToQuit.emit()

    assert saved_rules == [["Mixed", "Rule 1"]]
    panel.save_pending()
    assert saved_rules == [["Mixed", "Rule 1"]]


def test_a_remote_change_cancels_the_pending_save(qtbot, saved_rules):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.add_rule_button.click()

    app_settings.apply_remote({RULES_KEY: [rule_dict("Remote", "#378ADD")]})
    panel.save_pending()

    assert [rule.name for rule in panel.rules] == ["Remote"]
    assert saved_rules == []


def test_remote_changes_keep_the_counts_of_unchanged_queries(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    query_calls.sources = [f"{root}/a/f0.png"]
    panel = make_panel(qtbot)
    panel.apply_rules([HighlightRule.from_dict(rule_dict("Dogs", "#1D9E75", bars=[text_bar("dog")])), HighlightRule.from_dict(rule_dict("Cats", "#D85A30", bars=[text_bar("cat")]))])
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 2 and not panel.counting and len(panel.counts) == 2, timeout=5000)
    dogs = panel.counts[id(panel.rules[0])]

    app_settings.apply_remote({RULES_KEY: [rule_dict("Hounds", "#378ADD", bars=[text_bar("dog")]), rule_dict("Cats", "#D85A30", bars=[text_bar("kitten")])]})

    hounds, cats = panel.rules
    assert panel.counts[id(hounds)] is dogs
    assert dict(panel.model.rule_counts[0][1]) == dogs
    qtbot.waitUntil(lambda: len(query_calls) == 3 and not panel.counting and id(cats) in panel.counts, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert query_calls[2] == ["kitten"] and len(query_calls) == 3


def count_dogs_and_cats(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    query_calls.sources = [f"{root}/a/f0.png"]
    app_settings.save_immediate(RULES_KEY, [rule_dict("Dogs", "#1D9E75", bars=[text_bar("dog")]), rule_dict("Cats", "#D85A30", bars=[text_bar("cat")])])
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 2 and not panel.counting and len(panel.counts) == 2, timeout=5000)
    return panel, panel.counts[id(panel.rules[0])]


def changed_cats():
    return [rule_dict("Dogs", "#1D9E75", bars=[text_bar("dog")]), rule_dict("Cats", "#D85A30", bars=[text_bar("kitten")])]


def test_a_hidden_panel_recounts_only_the_changed_rules_when_shown(qtbot, tmp_path, query_calls):
    panel, dogs = count_dogs_and_cats(qtbot, tmp_path, query_calls)
    panel.hide()

    app_settings.apply_remote({RULES_KEY: changed_cats()})
    QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 2
    panel.show()

    qtbot.waitUntil(lambda: len(query_calls) == 3 and not panel.counting and id(panel.rules[1]) in panel.counts, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert query_calls[2:] == [["kitten"]]
    assert panel.counts[id(panel.rules[0])] is dogs
    panel.close()


def test_a_hidden_panel_still_recounts_everything_after_the_database_changes(qtbot, tmp_path, query_calls):
    panel, _dogs = count_dogs_and_cats(qtbot, tmp_path, query_calls)
    panel.hide()

    app_settings.apply_remote({RULES_KEY: changed_cats()})
    panel.on_db_content_updated("")
    panel.show()

    qtbot.waitUntil(lambda: len(query_calls) == 4 and not panel.counting, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert sorted(query_calls[2:]) == [["dog"], ["kitten"]]
    panel.close()


def test_the_tray_window_keeps_unchanged_counts_when_shown_again(qtbot, tmp_path, monkeypatch, query_calls):
    without_viewer(monkeypatch)
    panel, dogs = count_dogs_and_cats(qtbot, tmp_path, query_calls)
    panel.hide()

    app_settings.save_immediate(RULES_KEY, changed_cats())
    panel.show()

    assert [rule.bars[0]["params"]["keywords"] for rule in panel.rules] == ["dog", "kitten"]
    assert panel.counts[id(panel.rules[0])] is dogs
    qtbot.waitUntil(lambda: len(query_calls) == 3 and not panel.counting and id(panel.rules[1]) in panel.counts, timeout=5000)
    QtCore.QCoreApplication.processEvents()
    assert query_calls[2:] == [["kitten"]]
    panel.close()


def test_the_tray_window_rereads_shared_settings_when_activated(qtbot, monkeypatch):
    without_viewer(monkeypatch)
    panel = make_panel(qtbot)
    app_settings.save_immediate(RULES_KEY, [rule_dict("FromViewer", "#378ADD")])
    app_settings.save_immediate(COLUMNS_KEY, {"files": False})

    activate(panel)

    assert [rule.name for rule in panel.rules] == ["FromViewer"]
    assert panel.view.isColumnHidden(1)
    rules = list(panel.rules)
    activate(panel)
    assert all(a is b for a, b in zip(panel.rules, rules))
    panel.close()


def test_the_tray_window_saves_its_pending_edit_before_rereading(qtbot, monkeypatch):
    without_viewer(monkeypatch)
    panel = make_panel(qtbot)
    panel.add_rule_button.click()

    activate(panel)

    assert [rule.name for rule in load_rules()] == ["Mixed", "Rule 1"]
    assert [rule.name for rule in panel.rules] == ["Mixed", "Rule 1"]
    panel.close()


def test_a_viewer_panel_does_not_reread_on_activation(qtbot, monkeypatch):
    in_viewer(monkeypatch)
    panel = make_panel(qtbot)
    app_settings.save_immediate(RULES_KEY, [rule_dict("Elsewhere", "#378ADD")])

    activate(panel)

    assert [rule.name for rule in panel.rules] == ["Mixed"]
    panel.close()


def test_remote_rule_changes_are_applied(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)

    app_settings.apply_remote({RULES_KEY: [rule_dict("Dogs", "#378ADD", bars=[text_bar("dog")])], COLUMNS_KEY: {"files": False, "all_folders": True}})

    assert [rule.name for rule in panel.rules] == ["Dogs"]
    assert [rule.name for rule, _counts in panel.model.rule_counts] == ["Dogs"]
    assert panel.view.isColumnHidden(1) and not panel.view.isColumnHidden(4)
    qtbot.waitUntil(lambda: query_calls[-1:] == [["dog"]] and not panel.counting, timeout=5000)
    assert id(panel.rules[0]) in panel.counts


def test_own_changes_are_not_echoed(qtbot, immediate_save, committed):
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)

    panel.add_rule_button.click()
    rules = list(panel.rules)
    QtCore.QCoreApplication.processEvents()
    assert [list(update) for update in committed] == [[RULES_KEY]]
    assert panel.rules == rules and all(a is b for a, b in zip(panel.rules, rules))

    committed.clear()
    app_settings.apply_remote({RULES_KEY: [rule_dict("Remote", "#378ADD")], COLUMNS_KEY: {"files": False}})
    QtCore.QCoreApplication.processEvents()
    assert [rule.name for rule in panel.rules] == ["Remote"]
    assert committed == []


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
    assert panel.model.disk_text(root, 2) == "7"


def test_set_database_reads_its_folder_settings_and_scans(qtbot, tmp_path, query_calls, served_folders):
    root = make_folders(tmp_path / "root", {"": 1, "a": 2, "skip": 4})
    serve("main", [root], excluded=[f"{root}/skip"])
    panel = make_panel(qtbot)

    panel.set_database("main")

    qtbot.waitUntil(lambda: scanned(panel, [root]), timeout=5000)
    assert [name for name, _thread in served_folders] == ["main"]
    assert all(thread is not threading.main_thread() for _name, thread in served_folders)
    assert panel.database_name == "main"
    assert panel.database_path() == data_db_path("main")
    assert panel.view.database_path == data_db_path("main")
    assert panel.db_box.currentText() == "main"
    assert load_last_database() == "main"
    assert panel.model.disk.values(root) == FolderValues(1, 3, 1, 1)
    qtbot.waitUntil(lambda: len(query_calls) == 1, timeout=5000)


def test_switching_database_discards_the_previous_scan_and_counts(qtbot, tmp_path, monkeypatch, query_calls):
    first = make_folders(tmp_path / "first", {"": 1, "x": 1})
    second = make_folders(tmp_path / "second", {"": 2, "y": 1})
    serve("first", [first])
    serve("second", [second])
    query_calls.sources = [f"{first}/f0.png", f"{second}/f0.png", f"{second}/f1.png"]
    real_walk = widget_module.walk_disk
    real_count = widget_module.count_sources_by_folder
    release = gate()
    walk_started = gate()
    walk_done = gate()
    count_started = gate()
    count_done = gate()

    def slow_walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size=256):
        if list(roots) == [first]:
            walk_started.set()
            release.wait(5)
            on_batch([(first, [f"{first}/x"], 1), (f"{first}/x", [], 1)])
            walk_done.set()
            return
        real_walk(roots, excluded, ignore_pattern_re, cancel, on_batch, batch_size)

    def slow_count(sources, roots, cancel):
        if list(roots) == [first]:
            count_started.set()
            release.wait(5)
            counts = real_count(sources, roots, cancel)
            count_done.set()
            return counts
        return real_count(sources, roots, cancel)

    monkeypatch.setattr(widget_module, "walk_disk", slow_walk)
    monkeypatch.setattr(widget_module, "count_sources_by_folder", slow_count)
    panel = make_panel(qtbot)
    rule = panel.rules[0]
    panel.set_database("first")
    qtbot.waitUntil(lambda: walk_started.is_set() and count_started.is_set(), timeout=5000)

    panel.set_database("second")
    assert panel.model.disk is None and panel.counts == {}

    qtbot.waitUntil(lambda: scanned(panel, [second]) and id(rule) in panel.counts, timeout=5000)
    release.set()
    qtbot.waitUntil(lambda: walk_done.is_set() and count_done.is_set(), timeout=5000)
    QtCore.QCoreApplication.processEvents()
    QtCore.QCoreApplication.processEvents()
    assert set(panel.model.disk.nodes) == {second, f"{second}/y"}
    assert panel.model.disk.values(second) == FolderValues(2, 3, 1, 1)
    assert set(panel.counts[id(rule)]) == {second}
    assert panel.database_name == "second" and load_last_database() == "second"


def test_choosing_a_database_in_the_box_switches_to_it(qtbot, tmp_path, query_calls):
    first = make_folders(tmp_path / "first", {"": 1})
    second = make_folders(tmp_path / "second", {"": 2})
    serve("first", [first])
    serve("second", [second])
    panel = make_panel(qtbot)
    panel.set_database("first")
    qtbot.waitUntil(lambda: scanned(panel, [first]), timeout=5000)
    panel.db_box.addItem("second")

    panel.db_box.setCurrentText("second")

    qtbot.waitUntil(lambda: scanned(panel, [second]), timeout=5000)
    assert panel.database_name == "second"


def test_panel_without_databases_stays_empty(qtbot, monkeypatch, query_calls, served_folders):
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: None)
    monkeypatch.setattr(widget_module, "list_data_db_names", lambda: [])
    panel = FolderManagerPlugin().create_widget()
    qtbot.addWidget(panel)
    panel.show()
    qtbot.waitExposed(panel)

    panel.refresh()
    panel.on_db_content_updated("")
    QtCore.QCoreApplication.processEvents()

    assert panel.database_name == "" and panel.database_path() is None
    assert panel.db_box.currentText() == ""
    assert served_folders == [] and query_calls == []
    assert panel.model.disk is None and not panel.scanning
    assert panel.model.rowCount() == 0
    panel.close()


def test_notifications_follow_the_panel_database(qtbot, tmp_path, query_calls, immediate_flush, served_folders):
    root = make_folders(tmp_path / "root", {"a": 1})
    other = make_folders(tmp_path / "other", {"b": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)

    panel.on_db_content_updated("some_other_db")
    panel.on_folder_changed("some_other_db")
    panel.on_files_changed("some_other_db", {"modified": [f"{root}/a/f0.png"], "removed": []})
    QtCore.QCoreApplication.processEvents()
    assert len(query_calls) == 1 and len(served_folders) == 1 and not panel.stale_parents

    panel.on_db_content_updated("test")
    qtbot.waitUntil(lambda: len(query_calls) == 2, timeout=5000)

    serve("test", [other])
    panel.on_folder_changed("test")
    qtbot.waitUntil(lambda: scanned(panel, [other]), timeout=5000)
    assert len(served_folders) == 2


def test_editing_one_rule_recounts_only_that_rule(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"": 1})
    panel = make_panel(qtbot)
    panel.apply_rules([HighlightRule.from_dict(rule_dict("One", "#1D9E75", bars=[text_bar("dog")])), HighlightRule.from_dict(rule_dict("Two", "#D85A30", bars=[text_bar("cat")]))])
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
    qtbot.waitUntil(lambda: panel.model.disk is not first and not panel.scanning, timeout=5000)
    assert panel.model.disk is not first and panel.model.disk.finished
    assert panel.model.disk.values(root) == FolderValues(1, 4, 1, 2)
    assert finished_on_main(finish_threads) == []
    new = panel.model.disk
    swap = next(n for n, disk in enumerate(swapped) if disk is new)
    assert all(disk is first for disk in swapped[:swap]) and all(disk is new for disk in swapped[swap:])
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
    assert panel.model.disk_text(root, 2) == "3"
    release.set()
    qtbot.waitUntil(lambda: not panel.scanning, timeout=5000)
    assert panel.model.disk.values(root) == FolderValues(2, 4, 1, 1)


def test_the_first_scan_shows_direct_counts_while_walking(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 3, "a": 2})
    release, delivered = gated_walk(monkeypatch, [root])
    panel = make_panel(qtbot)
    serve("test", [root])
    panel.set_database("test")
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


def test_updates_during_a_count_queue_one_more_count(qtbot, tmp_path, monkeypatch, query_calls, immediate_flush):
    root = make_folders(tmp_path / "root", {"a": 1})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: len(query_calls) == 1 and not panel.counting, timeout=5000)
    started = gate()
    release = gate()
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
    started = gate()
    release = gate()
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
    serve("test", [root])
    panel.set_database("test")
    qtbot.waitUntil(lambda: panel.model.roots == [root], timeout=5000)
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
    entered = gate()
    release = gate()

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
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders, **_: expanded.append(list(folders)))
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
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders, **_: expanded.append(list(folders)))
    panel.view.hide()
    QtCore.QCoreApplication.processEvents()
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
    assert panel.columns == {"files": False, "all_files": True, "folders": True, "all_folders": True}
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
    def __init__(self, database_name):
        self.database_name = database_name


def test_plugin_opens_standalone_and_starts_on_the_host_database(qtbot, monkeypatch):
    assert FolderManagerPlugin.STANDALONE_AVAILABLE is True
    assert FolderManagerPlugin.STANDALONE_SIZE == (720, 900)
    assert "save_ui_state" not in vars(FolderManagerPlugin) and "restore_ui_state" not in vars(FolderManagerPlugin)
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: HostWindow("b"))
    monkeypatch.setattr(widget_module, "list_data_db_names", lambda: ["a", "b"])
    save_last_database("a")

    widget = FolderManagerPlugin().create_widget()
    qtbot.addWidget(widget)

    assert widget.database_name == "b"
    assert widget.db_box.currentText() == "b"


def test_plugin_without_host_starts_on_the_last_database(qtbot, monkeypatch):
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: None)
    monkeypatch.setattr(widget_module, "list_data_db_names", lambda: ["a", "b"])
    save_last_database("b")

    widget = FolderManagerPlugin().create_widget()
    qtbot.addWidget(widget)

    assert widget.database_name == "b"


def test_plugin_without_host_or_last_database_starts_on_the_first(qtbot, monkeypatch):
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: None)
    monkeypatch.setattr(widget_module, "list_data_db_names", lambda: ["a", "b"])

    widget = FolderManagerPlugin().create_widget()
    qtbot.addWidget(widget)

    assert widget.database_name == "a"


def test_show_in_tree_is_offered_only_when_the_window_shows_the_panel_database(qtbot, monkeypatch):
    host = HostWindow("main")
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: host)
    panel = FolderManagerWidget()
    qtbot.addWidget(panel)
    panel.set_database("main")
    assert panel.view.show_in_tree_available()
    host.database_name = "other"
    assert not panel.view.show_in_tree_available()
    monkeypatch.setattr(InstanceRegistry.instance(), "get_host_window", lambda: None)
    assert not panel.view.show_in_tree_available()


def test_expand_to_matches_only_looks_under_the_selected_folders(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 0, "a": 1, "a/s": 0, "c": 0, "c/x": 1, "c/x/s": 0})
    query_calls.sources = [f"{root}/a/f0.png", f"{root}/c/x/f0.png"]
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: bool(panel.model.badges(f"{root}/c/x")) and bool(panel.model.badges(f"{root}/a")), timeout=5000)
    expanded = []
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders, **_: expanded.append(list(folders)))
    monkeypatch.setattr(panel.view, "get_selected_paths", lambda: [f"{root}/c"])

    panel.expand_to_matches()

    qtbot.waitUntil(lambda: bool(expanded), timeout=5000)
    assert expanded == [[root, f"{root}/c"]]


def test_select_matches_selects_every_match_after_expanding(qtbot, tmp_path, query_calls):
    root = make_folders(tmp_path / "root", {"": 0, "a": 1, "a/b": 0, "a/b/c": 1, "a/b/c/s": 0, "d": 0})
    query_calls.sources = [f"{root}/a/f0.png", f"{root}/a/b/c/f0.png"]
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    qtbot.waitUntil(lambda: bool(panel.model.badges(f"{root}/a/b/c")), timeout=5000)

    panel.select_button.click()

    qtbot.waitUntil(lambda: sorted(panel.view.get_selected_paths()) == [f"{root}/a", f"{root}/a/b/c"], timeout=5000)


def test_expand_to_matches_without_matches_tells_the_user(qtbot, tmp_path, monkeypatch, query_calls):
    root = make_folders(tmp_path / "root", {"": 0, "a": 0})
    panel = make_panel(qtbot)
    bind(qtbot, panel, [root])
    notices = []
    monkeypatch.setattr(widget_module.Notifier, "info", lambda text, *args, **kwargs: notices.append(text))
    expanded = []
    monkeypatch.setattr(panel.view, "expand_folders", lambda folders, **_: expanded.append(list(folders)))

    panel.expand_to_matches(select=True)

    qtbot.waitUntil(lambda: bool(notices), timeout=5000)
    assert expanded == []


def test_panel_registers_itself_for_commands(qtbot):
    panel = make_panel(qtbot)
    assert panel in InstanceRegistry.instance().get_all(widget_module.INSTANCE_NAME)

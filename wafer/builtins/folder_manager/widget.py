import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from itertools import chain

from PySide6 import QtCore, QtWidgets

from wafer.app.viewer.ipc_bridge import ViewerIpcBridge
from wafer.builtins.commands.folder_files import query_sources
from wafer.core.common.paths import child_prefix, data_db_path, list_data_db_names, normalize_path, parent_folder
from wafer.core.common.virtual_paths import source_path
from wafer.core.db.path_scope import is_under
from wafer.core.lang.manager import t
from wafer.core.store.settings import app_settings
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.commands.bridge import UI, ActionKit, Menu
from wafer.qt.common.dispatcher import CancelSlot, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.notifier import Notifier
from wafer.qt.common.rate_limit import qt_throttle
from wafer.qt.common.thread import utility_pool
from wafer.qt.widgets.database_box import DatabaseBox
from wafer.qt.widgets.flow_layout import FlowLayout

from .database import FolderSettings, initial_database, read_folder_settings
from .rule_editor import METRIC_LABELS, RuleList, tool_button
from .rules import METRICS, HighlightRule, new_rule
from .shared_settings import COLUMNS_KEY, DEFAULT_COLUMNS, RULES_KEY, load_columns, load_last_database, load_rules, save_columns, save_last_database, save_rules
from .stats import DiskTree, count_sources_by_folder, list_folder, walk_disk
from .view import FolderManagerTreeView, folders_to_open

INSTANCE_NAME = "FolderManager"
RULE_EDIT_DELAY_MS = 400
SAVE_DELAY_MS = 300
STATS_REFRESH_MS = 100
REFRESH_INTERVAL_MS = 3000
REFRESH_IDLE_MS = 1000
EXPAND_SLICE_SECONDS = 0.015
EXPAND_DEADLINE_CHECK = 256
MATCHES_REFRESH_MS = 1000
MATCHES_ONLY_CHANNEL = "matches_only"
DISPOSE_BATCH = 20000


def existing_folder(path: str, roots: set[str]) -> str:
    while path not in roots and not os.path.isdir(path):
        parent = parent_folder(path)
        if len(parent) >= len(path):
            break
        path = parent
    return path


def outermost(paths: Iterable[str]) -> list[str]:
    kept: list[str] = []
    for path in sorted(set(paths), key=len):
        if not any(is_under(path, other) for other in kept):
            kept.append(path)
    return kept


@dataclass(frozen=True)
class MatchScan:
    matches: list[str]
    folders: list[str]
    visible: frozenset[str]
    ancestors: frozenset[str]


class RulesArea(QtWidgets.QScrollArea):
    def __init__(self, content: QtWidgets.QWidget, parent=None):
        super().__init__(parent)
        self.setWidget(content)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Preferred)
        content.installEventFilter(self)

    def eventFilter(self, source, event):
        if source is self.widget() and event.type() == QtCore.QEvent.LayoutRequest:
            self.updateGeometry()
        return super().eventFilter(source, event)

    def sizeHint(self):
        height = self.widget().sizeHint().height()
        parent = self.parentWidget()
        if parent is not None:
            height = min(height, parent.height() // 2)
        return QtCore.QSize(super().sizeHint().width(), height)

    def minimumSizeHint(self):
        return QtCore.QSize(0, 0)


class FolderManagerWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.dispatcher = Dispatcher(utility_pool, parent=self)
        bridge = ViewerIpcBridge.instance()
        self.follows_viewer = bridge is not None
        self.database_name = ""
        self.columns = dict(DEFAULT_COLUMNS)
        self.settings_slot = CancelSlot()
        self.disk_slot = CancelSlot()
        self.relist_slot = CancelSlot()
        self.count_slots: dict[int, CancelSlot] = {}
        self.counts: dict[int, dict[str, tuple[int, int]]] = {}
        self.counted_keys: dict[int, str | None] = {}
        self.pending_rule_ids: set[int] = set()
        self.stale_rule_ids: set[int] = set()
        self.counting: dict[int, tuple] = {}
        self.recount_after: set[int] = set()
        self.scanning = False
        self.scanned = 0
        self.walk_roots: list[str] | None = None
        self.stale_disk = False
        self.stale_rules = False
        self.stale_parents: set[str] = set()
        self.relisting: set[str] = set()
        self.expand_serial = 0
        self.matches_only = False
        self.matches_version = 0
        self.filter_serial = 0
        self.filtering = False
        self.found_matches: MatchScan | None = None
        self.found_version = -1
        self.opened_folders: frozenset[str] = frozenset()
        self.opening_folders: frozenset[str] = frozenset()
        self.collapses = 0
        self.build_ui()
        self.apply_rules(load_rules())
        self.apply_columns(load_columns())
        app_settings.key_changed.connect(self.on_setting_changed)
        QtCore.QCoreApplication.instance().aboutToQuit.connect(self.save_pending)
        UI.register_instance(INSTANCE_NAME, self)
        if bridge is not None:
            bridge.db_content_updated.connect(self.on_db_content_updated)
            bridge.files_changed.connect(self.on_files_changed)
            bridge.folder_changed.connect(self.on_folder_changed)

    def build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))
        layout.addWidget(self.build_bar())
        self.rule_list = RuleList()
        self.rule_list.rule_edited.connect(self.on_rule_edited)
        self.rule_list.rule_removed.connect(self.on_rule_removed)
        self.rule_list.order_changed.connect(self.on_order_changed)
        self.rules_area = RulesArea(self.rule_list)
        layout.addWidget(self.rules_area)
        self.view = FolderManagerTreeView()
        self.view.set_rules_source(lambda: self.rules)
        self.view.show_in_tree_available = self.host_shows_database
        self.model.paths_changed.connect(self.on_paths_changed)
        self.view.folders_set.connect(self.on_folders_set)
        layout.addWidget(self.view, 1)
        self.stats_timer = QtCore.QTimer(self)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.setInterval(STATS_REFRESH_MS)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.rule_timer = QtCore.QTimer(self)
        self.rule_timer.setSingleShot(True)
        self.rule_timer.timeout.connect(self.recount_pending_rules)
        self.filter_timer = QtCore.QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.timeout.connect(self.refilter)
        self.rules_saver = self.save_timer(self.save_rules_now)
        self.columns_saver = self.save_timer(self.save_columns_now)

    def save_timer(self, save) -> QtCore.QTimer:
        timer = QtCore.QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(SAVE_DELAY_MS)
        timer.timeout.connect(save)
        return timer

    def build_bar(self) -> QtWidgets.QWidget:
        self.bar = QtWidgets.QWidget()
        self.flow = FlowLayout(self.bar, margin=dpix(2), spacing=dpix(4))
        self.db_box = DatabaseBox()
        self.db_box.setToolTip(t("Database"))
        self.db_box.currentTextChanged.connect(self.set_database)
        self.status_label = QtWidgets.QLabel()
        self.status_label.hide()
        self.expand_button = tool_button("chevron_down", t("Open the tree to every folder a rule marks (only under the selected folders, if any)"), t("Expand to matches"))
        self.expand_button.clicked.connect(lambda: self.expand_to_matches())
        self.select_button = tool_button("check", t("Open the tree to every folder a rule marks and select them (only under the selected folders, if any)"), t("Select matches"))
        self.select_button.clicked.connect(lambda: self.expand_to_matches(select=True))
        self.matches_button = tool_button("query", t("Show only folders a rule marks"))
        self.matches_button.setCheckable(True)
        self.matches_button.toggled.connect(self.set_matches_only)
        self.collapse_button = tool_button("chevron_right", t("Collapse all"))
        self.collapse_button.clicked.connect(self.collapse_all)
        self.columns_button = tool_button("gear", t("Columns"))
        self.columns_button.clicked.connect(self.show_column_menu)
        self.refresh_button = tool_button("refresh", t("Scan again"))
        self.refresh_button.clicked.connect(self.refresh)
        self.add_rule_button = tool_button("plus", t("Add rule"), t("Add rule"))
        self.add_rule_button.clicked.connect(self.add_rule)
        for widget in (
            self.db_box,
            self.status_label,
            self.expand_button,
            self.select_button,
            self.matches_button,
            self.collapse_button,
            self.columns_button,
            self.refresh_button,
            self.add_rule_button,
        ):
            self.flow.addWidget(widget)
        return self.bar

    @property
    def model(self):
        return self.view.model_

    @property
    def rules(self) -> list[HighlightRule]:
        return self.rule_list.rules

    def apply_rules(self, rules: Sequence[HighlightRule]) -> None:
        finished = {self.counted_keys.get(id(rule)): self.counts[id(rule)] for rule in self.rules if id(rule) in self.counts and id(rule) not in self.counting}
        finished.pop(None, None)
        self.forget_counts()
        self.rule_list.set_rules(rules)
        changed = []
        for rule in self.rules:
            key = self.count_key(rule)
            if key in finished:
                self.counts[id(rule)] = finished[key]
                self.counted_keys[id(rule)] = key
            else:
                changed.append(rule)
        self.publish_counts()
        if not changed:
            return
        if self.isVisible():
            self.recount(changed)
        else:
            self.stale_rule_ids.update(map(id, changed))

    def apply_columns(self, columns: dict[str, bool]) -> None:
        for metric in METRICS:
            self.set_column_visible(metric, columns[metric])

    def on_setting_changed(self, key: str) -> None:
        if key == RULES_KEY:
            self.rules_saver.stop()
            self.apply_rules(load_rules())
        elif key == COLUMNS_KEY:
            self.columns_saver.stop()
            self.apply_columns(load_columns())

    def reload_shared_settings(self) -> None:
        self.save_pending()
        rules = load_rules()
        if [rule.to_dict() for rule in rules] != [rule.to_dict() for rule in self.rules]:
            self.apply_rules(rules)
        columns = load_columns()
        if columns != self.columns:
            self.apply_columns(columns)

    def save_rules_later(self) -> None:
        self.rules_saver.start()

    def save_columns_later(self) -> None:
        self.columns_saver.start()

    def save_rules_now(self) -> None:
        self.rules_saver.stop()
        save_rules(self.rules)

    def save_columns_now(self) -> None:
        self.columns_saver.stop()
        save_columns(self.columns)

    def save_pending(self) -> None:
        if self.rules_saver.isActive():
            self.save_rules_now()
        if self.columns_saver.isActive():
            self.save_columns_now()

    def forget_counts(self) -> None:
        for slot in self.count_slots.values():
            slot.cancel()
        self.count_slots.clear()
        self.counts.clear()
        self.counted_keys.clear()
        self.pending_rule_ids.clear()
        self.stale_rule_ids.clear()
        self.counting.clear()
        self.recount_after.clear()
        self.rule_timer.stop()

    def set_column_visible(self, metric: str, visible: bool) -> None:
        self.columns[metric] = visible
        self.view.set_column_visible(METRICS.index(metric) + 1, visible)

    def toggle_column(self, metric: str) -> None:
        self.set_column_visible(metric, not self.columns[metric])
        self.save_columns_later()

    def column_menu_items(self) -> list:
        uid = f"{id(self):x}"
        return [
            ":Columns",
            *(
                ActionKit.Action(
                    path=f"inline.folder_manager.{uid}.column.{metric}",
                    display=METRIC_LABELS[metric],
                    checked=lambda metric=metric: self.columns[metric],
                    func=lambda ctx, metric=metric: self.toggle_column(metric),
                )
                for metric in METRICS
            ),
        ]

    def show_column_menu(self) -> None:
        spec = Menu.session(self).menu(self.column_menu_items())
        if spec is not None:
            spec.exec(self.columns_button.mapToGlobal(QtCore.QPoint(0, self.columns_button.height())))

    def database_path(self) -> str | None:
        return data_db_path(self.database_name) if self.database_name else None

    def host_shows_database(self) -> bool:
        host = InstanceRegistry.instance().get_host_window()
        return host is not None and bool(self.database_name) and getattr(host, "database_name", None) == self.database_name

    def set_database(self, name: str) -> None:
        if name != self.database_name:
            self.database_name = name
            self.view.database_name = name
            if name:
                save_last_database(name)
            self.clear_folders()
        self.db_box.show_quietly(name)
        token = self.settings_slot.renew()
        if not name:
            return

        def task():
            settings = read_folder_settings(name)
            if not token.is_cancelled():
                self.dispatcher.invoke(lambda: self.apply_loaded_settings(token, settings))

        self.dispatcher.post(task, cancel=token)

    def apply_loaded_settings(self, token, settings: FolderSettings) -> None:
        if not token.is_cancelled():
            self.apply_folder_settings(settings)

    def clear_folders(self) -> None:
        self.disk_slot.cancel()
        self.relist_slot.cancel()
        self.forget_counts()
        self.scanning = False
        self.scanned = 0
        self.walk_roots = None
        self.relisting = set()
        self.stale_disk = False
        self.stale_parents.clear()
        self.expand_serial += 1
        self.filter_serial += 1
        self.filtering = False
        self.view.stop_expanding()
        self.stats_timer.stop()
        disk = self.model.disk
        self.model.disk = None
        if disk is not None:
            self.dispatcher.post(disk.clear)
        self.view.set_folders([])
        self.publish_counts()
        self.update_status()

    def apply_folder_settings(self, settings: FolderSettings) -> None:
        model = self.model
        current_pattern = model.ignore_pattern_re.pattern if model.ignore_pattern_re is not None else None
        new_pattern = settings.ignore_pattern_re.pattern if settings.ignore_pattern_re is not None else None
        if (settings.roots, settings.excluded, new_pattern) != (list(model.roots or ()), set(model.excluded or ()), current_pattern):
            state = self.view.get_state()
            self.view.set_folders(settings.roots, settings.excluded, settings.ignore_pattern_re)
            self.view.set_state_async(state)
        self.stale_disk = True
        self.stale_rules = True
        self.flush_if_visible()

    def is_my_db(self, db: str) -> bool:
        return not db or db == self.database_name

    def on_folder_changed(self, db: str) -> None:
        if self.is_my_db(db):
            self.set_database(self.database_name)

    def on_db_content_updated(self, db: str) -> None:
        if self.is_my_db(db):
            self.stale_rules = True
            self.flush_later_if_visible()

    def on_files_changed(self, db: str, payload: dict) -> None:
        if not self.is_my_db(db):
            return
        self.stale_rules = True
        for path in (*payload.get("modified", ()), *payload.get("removed", ())):
            self.stale_parents.add(parent_folder(normalize_path(source_path(path))))
        self.flush_later_if_visible()

    def showEvent(self, event):
        super().showEvent(event)
        if not self.follows_viewer:
            self.reload_shared_settings()
        self.flush()

    def hideEvent(self, event):
        super().hideEvent(event)
        self.save_pending()

    def event(self, event):
        if event.type() == QtCore.QEvent.WindowActivate and not self.follows_viewer:
            self.reload_shared_settings()
        elif event.type() == QtCore.QEvent.WindowDeactivate and not self.follows_viewer:
            self.save_pending()
        return super().event(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.rules_area.updateGeometry()

    def flush_if_visible(self) -> None:
        if self.isVisible():
            self.flush()

    def flush_later_if_visible(self) -> None:
        if self.isVisible():
            self.flush_later()

    @qt_throttle(REFRESH_INTERVAL_MS, REFRESH_IDLE_MS)
    def flush_later(self) -> None:
        self.flush_if_visible()

    def flush(self) -> None:
        if not self.database_name:
            return
        if self.stale_disk:
            self.stale_disk = False
            self.stale_parents.clear()
            self.rescan_all()
        elif self.stale_parents and not self.full_scan_running():
            parents, self.stale_parents = self.stale_parents, set()
            self.relist_parents(parents)
        if self.stale_rules:
            self.stale_rules = False
            self.stale_rule_ids.clear()
            self.recount(self.rules)
        elif self.stale_rule_ids:
            stale, self.stale_rule_ids = self.stale_rule_ids, set()
            self.recount([rule for rule in self.rules if id(rule) in stale])

    def refresh(self) -> None:
        self.set_database(self.database_name)

    def under_roots(self, path: str) -> bool:
        return any(is_under(path, root) for root in self.model.roots or ())

    def full_scan_running(self) -> bool:
        return self.scanning and self.walk_roots is None

    def rescan_all(self) -> None:
        roots = list(self.model.roots or [])
        if self.model.disk is None or not self.model.disk.finished:
            self.model.disk = DiskTree(roots)
        self.start_walk(roots, full=True)

    def rescan_paths(self, paths: Sequence[str]) -> None:
        paths = [normalize_path(path) for path in paths]
        disk = self.model.disk
        if disk is None or not disk.finished or self.full_scan_running() or not all(map(self.under_roots, paths)):
            self.rescan_all()
            return
        if self.scanning:
            paths = [*self.walk_roots, *paths]
        self.start_walk(outermost(paths), full=False)

    def start_walk(self, roots: list[str], full: bool) -> None:
        token = self.disk_slot.renew()
        if full:
            self.relist_slot.cancel()
            self.relisting.clear()
        preview = self.model.disk if full and not self.model.disk.finished else None
        excluded = set(self.model.excluded or ())
        pattern = self.model.ignore_pattern_re
        self.scanning = True
        self.scanned = 0
        self.walk_roots = None if full else roots
        self.refresh_stats()

        def task():
            walked = DiskTree(roots)

            def on_batch(batch):
                for entry in batch:
                    walked.add(*entry)
                self.dispatcher.invoke(lambda: self.apply_batch(preview, token, batch))

            walk_disk(roots, excluded, pattern, token, on_batch)
            if token.is_cancelled():
                return
            walked.finish()
            if not token.is_cancelled():
                self.dispatcher.invoke(lambda: self.finish_walk(token, walked, full))

        self.dispatcher.post(task, cancel=token)

    def apply_batch(self, preview: DiskTree | None, token, batch) -> None:
        if token.is_cancelled():
            return
        if preview is not None and preview is self.model.disk:
            for entry in batch:
                preview.add(*entry)
        self.scanned += len(batch)
        if not self.stats_timer.isActive():
            self.stats_timer.start()

    def finish_walk(self, token, walked: DiskTree, full: bool) -> None:
        if token.is_cancelled():
            return
        disk = self.model.disk
        if full:
            self.model.disk = walked
            if disk is not None:
                self.dispatcher.post(disk.clear)
        elif disk is not None and disk.finished:
            disk.merge(walked)
        self.scanning = False
        self.walk_roots = None
        self.stats_timer.stop()
        self.refresh_stats()
        if self.stale_parents:
            self.flush_if_visible()

    def on_paths_changed(self, paths: Sequence[str]) -> None:
        self.stale_parents.update(normalize_path(path) for path in paths)
        if not self.full_scan_running():
            parents, self.stale_parents = self.stale_parents, set()
            self.relist_parents(parents)

    def nearest_known(self, path: str) -> str | None:
        disk = self.model.disk
        if disk is None or not self.under_roots(path):
            return None
        while path not in disk.nodes:
            parent = parent_folder(path)
            if len(parent) >= len(path):
                return None
            path = parent
        return path

    def relist_parents(self, parents: Iterable[str]) -> None:
        disk = self.model.disk
        if disk is None:
            return
        targets = self.relisting | {path for path in map(self.nearest_known, parents) if path is not None}
        if not targets:
            return
        self.relisting = targets
        token = self.relist_slot.renew()
        roots = set(self.model.roots or ())
        excluded = set(self.model.excluded or ())
        pattern = self.model.ignore_pattern_re

        def task():
            listed: dict[str, tuple[list[str], int]] = {}
            for target in targets:
                if token.is_cancelled():
                    return
                path = existing_folder(target, roots)
                if path not in listed:
                    listed[path] = list_folder(path, excluded, pattern)
            self.dispatcher.invoke(lambda: self.apply_relist(disk, token, listed))

        self.dispatcher.post(task, cancel=token)

    def apply_relist(self, disk: DiskTree, token, listed: dict[str, tuple[list[str], int]]) -> None:
        if token.is_cancelled() or disk is not self.model.disk:
            return
        self.relisting = set()
        new_folders = []
        for path, (child_dirs, file_count) in listed.items():
            if path not in disk.nodes:
                continue
            disk.update_folder(path, child_dirs, file_count)
            new_folders.extend(child for child in child_dirs if child not in disk.nodes)
        self.dispose_orphans(disk)
        self.refresh_stats()
        if new_folders:
            self.rescan_paths(new_folders)

    def dispose_orphans(self, disk: DiskTree) -> None:
        if disk is self.model.disk and disk.dispose(DISPOSE_BATCH):
            QtCore.QTimer.singleShot(0, lambda: self.dispose_orphans(disk))

    def refresh_stats(self) -> None:
        self.model.refresh_stats()
        self.update_status()
        self.on_matches_changed()

    def update_status(self) -> None:
        self.status_label.setText(t("Scanning… {count}", count=f"{self.scanned:,}"))
        self.status_label.setVisible(self.scanning)

    def add_rule(self) -> None:
        rule = new_rule(self.rules)
        self.rule_list.append_row(rule)
        self.publish_counts()
        self.recount([rule])
        self.save_rules_later()

    def on_order_changed(self) -> None:
        self.publish_counts()
        self.save_rules_later()

    def on_rule_removed(self, rule: HighlightRule) -> None:
        slot = self.count_slots.pop(id(rule), None)
        if slot is not None:
            slot.cancel()
        self.counts.pop(id(rule), None)
        self.counted_keys.pop(id(rule), None)
        self.pending_rule_ids.discard(id(rule))
        self.counting.pop(id(rule), None)
        self.recount_after.discard(id(rule))
        self.publish_counts()
        self.save_rules_later()

    def on_rule_edited(self, rule: HighlightRule) -> None:
        if self.count_key(rule) != self.counted_keys.get(id(rule)):
            self.pending_rule_ids.add(id(rule))
            self.rule_timer.start(RULE_EDIT_DELAY_MS)
        self.publish_counts()
        self.save_rules_later()

    def recount_pending_rules(self) -> None:
        pending, self.pending_rule_ids = self.pending_rule_ids, set()
        self.recount([rule for rule in self.rules if id(rule) in pending])

    @staticmethod
    def count_key(rule: HighlightRule) -> str | None:
        if not rule.enabled or not rule.shows_count():
            return None
        return json.dumps(rule.bars, sort_keys=True, default=str)

    def recount(self, rules: Sequence[HighlightRule]) -> None:
        db_path = self.database_path()
        roots = list(self.model.roots or ())
        for rule in rules:
            rule_id = id(rule)
            slot = self.count_slots.setdefault(rule_id, CancelSlot())
            key = self.count_key(rule)
            self.counted_keys[rule_id] = key
            if key is None or not db_path or not roots:
                slot.cancel()
                self.counts.pop(rule_id, None)
                self.counting.pop(rule_id, None)
                self.recount_after.discard(rule_id)
                continue
            inputs = (db_path, tuple(roots), key)
            if self.counting.get(rule_id) == inputs:
                self.recount_after.add(rule_id)
                continue
            self.counting[rule_id] = inputs
            self.recount_after.discard(rule_id)
            self.post_count(rule_id, slot.renew(), db_path, rule.query_entries(), roots)
        self.publish_counts()

    def post_count(self, rule_id: int, token, db_path: str, entries: list[tuple], roots: list[str]) -> None:
        def task():
            counts = None
            try:
                sources = query_sources(db_path, entries)
                if not token.is_cancelled():
                    counts = count_sources_by_folder(sources, roots, token)
            finally:
                self.dispatcher.invoke(lambda: self.apply_counts(rule_id, token, counts))

        self.dispatcher.post(task, cancel=token)

    def apply_counts(self, rule_id: int, token, counts: dict[str, tuple[int, int]] | None) -> None:
        if token.is_cancelled():
            return
        self.counting.pop(rule_id, None)
        if counts is not None:
            self.counts[rule_id] = counts
            self.publish_counts()
        if rule_id in self.recount_after:
            self.recount_after.discard(rule_id)
            self.recount([rule for rule in self.rules if id(rule) == rule_id])

    def publish_counts(self) -> None:
        self.model.rule_counts = [(rule, self.counts.get(id(rule), {})) for rule in self.rules]
        self.model.refresh_stats()
        self.on_matches_changed()

    def scan_matches(self, scopes: Sequence[str], is_current: Callable[[], bool], on_found: Callable[[MatchScan], None]) -> None:
        disk = self.model.disk
        lists = [list(disk.nodes)] if disk is not None else []
        lists.extend(list(counts) for _rule, counts in self.model.rule_counts)
        candidates = chain.from_iterable(lists)
        roots = [normalize_path(root) for root in self.model.roots or ()]
        prefixes = tuple(child_prefix(scope) for scope in scopes)
        seen: set[str] = set()
        matches: list[str] = []

        def in_scope(path: str) -> bool:
            return not scopes or path in scopes or path.startswith(prefixes)

        def scan_slice() -> None:
            if not is_current():
                return
            deadline = time.perf_counter() + EXPAND_SLICE_SECONDS
            model = self.model
            for number, path in enumerate(candidates):
                if path not in seen:
                    seen.add(path)
                    current = model.disk
                    if in_scope(path) and model.badges_for(path, current.values(path) if current is not None else None):
                        matches.append(path)
                if number % EXPAND_DEADLINE_CHECK == 0 and time.perf_counter() >= deadline:
                    QtCore.QTimer.singleShot(0, scan_slice)
                    return
            self.dispatcher.post(find_folders)

        def find_folders() -> None:
            folders = folders_to_open(matches, roots)
            ancestors = frozenset(folders)
            found = MatchScan(matches, folders, ancestors.union(matches), ancestors)
            self.dispatcher.invoke(lambda: deliver(found))

        def deliver(found: MatchScan) -> None:
            if is_current():
                on_found(found)

        scan_slice()

    def expand_to_matches(self, select: bool = False) -> None:
        self.expand_serial += 1
        serial = self.expand_serial
        scopes = outermost(normalize_path(path) for path in self.view.get_selected_paths())
        self.scan_matches(scopes, lambda: serial == self.expand_serial, lambda found: self.open_matches(serial, found, select))

    def open_matches(self, serial: int, found: MatchScan, select: bool) -> None:
        if not found.matches:
            Notifier.info(t("No matching folders"))
            return

        def select_matches() -> None:
            if select and serial == self.expand_serial:
                self.view.select_folders(found.matches)

        self.view.expand_folders(found.folders, on_complete=select_matches)

    def collapse_all(self) -> None:
        self.expand_serial += 1
        self.collapses += 1
        self.opening_folders = frozenset()
        self.view.collapse_all()

    def set_matches_only(self, on: bool) -> None:
        if on == self.matches_only:
            return
        self.matches_only = on
        self.matches_button.setChecked(on)
        self.filter_serial += 1
        self.filtering = False
        self.opened_folders = self.opening_folders = frozenset()
        if not on:
            self.filter_timer.stop()
            self.view.stop_expanding(MATCHES_ONLY_CHANNEL)
            self.view.apply_row_filter(None)
            return
        if self.found_matches is not None:
            self.show_matches(self.found_matches)
        if self.found_version != self.matches_version:
            self.refilter()

    def on_matches_changed(self) -> None:
        self.matches_version += 1
        self.schedule_refilter()

    def schedule_refilter(self) -> None:
        if self.matches_only and not self.filtering and not self.filter_timer.isActive():
            self.filter_timer.start(MATCHES_REFRESH_MS)

    def refilter(self) -> None:
        if self.filtering or not self.matches_only:
            return
        self.filter_timer.stop()
        self.filtering = True
        serial = self.filter_serial
        version = self.matches_version
        collapses = self.collapses
        self.scan_matches([], lambda: serial == self.filter_serial, lambda found: self.on_filter_scanned(version, collapses, found))

    def on_filter_scanned(self, version: int, collapses: int, found: MatchScan) -> None:
        self.filtering = False
        self.found_matches = found
        self.found_version = version
        if collapses != self.collapses:
            self.opened_folders = self.opened_folders.union(found.folders)
        self.show_matches(found)
        if version != self.matches_version:
            self.schedule_refilter()

    def show_matches(self, found: MatchScan) -> None:
        self.view.apply_row_filter(found.visible, found.ancestors)
        pending = [folder for folder in found.folders if folder not in self.opened_folders or folder in self.opening_folders]
        if not pending:
            return
        self.opened_folders = self.opened_folders.union(pending)
        self.opening_folders = frozenset(pending)
        self.view.expand_folders(pending, on_complete=self.on_filter_folders_opened, channel=MATCHES_ONLY_CHANNEL)

    def on_filter_folders_opened(self) -> None:
        self.opening_folders = frozenset()

    def on_folders_set(self) -> None:
        self.opened_folders = self.opening_folders = frozenset()
        self.found_matches = None
        self.found_version = -1


class FolderManagerPlugin(BasePanelPlugin):
    NAME = "folder_manager"
    DISPLAY_NAME = "Folder Manager"
    PRIORITY = 0
    SOURCE = "Builtin"
    DEFAULT_ENABLED = True
    STANDALONE_AVAILABLE = True
    STANDALONE_SIZE = (720, 900)

    def create_widget(self) -> FolderManagerWidget:
        widget = FolderManagerWidget()
        host = InstanceRegistry.instance().get_host_window()
        widget.set_database(initial_database(getattr(host, "database_name", None), load_last_database(), list_data_db_names()))
        return widget

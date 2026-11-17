import json
import os
import time
from collections.abc import Callable, Iterable, Sequence
from itertools import chain

from PySide6 import QtCore, QtWidgets

from wafer.app.viewer.ipc_bridge import ViewerIpcBridge
from wafer.app.viewer.widgets.foldertree import LazyFolderTreeView
from wafer.builtins.commands.folder_files import query_sources
from wafer.core.common.paths import data_db_path, normalize_path, parent_folder
from wafer.core.common.virtual_paths import source_path
from wafer.core.db.path_scope import is_under
from wafer.core.lang.manager import t
from wafer.core.logs import AppLogger
from wafer.plugin.panel.base import BasePanelPlugin
from wafer.qt.commands.binding.instance_registry import InstanceRegistry
from wafer.qt.commands.bridge import ActionKit, Menu
from wafer.qt.common.dispatcher import CancelSlot, Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.rate_limit import qt_throttle
from wafer.qt.common.thread import utility_pool
from wafer.qt.widgets.flow_layout import FlowLayout

from .rule_editor import METRIC_LABELS, RuleList, tool_button
from .rules import METRICS, HighlightRule, default_rules, new_rule
from .stats import DiskTree, count_sources_by_folder, list_folder, walk_disk
from .view import FolderManagerTreeView, folders_to_open

DEFAULT_COLUMNS = {"files": True, "all_files": True, "folders": True, "all_folders": False}
RULE_EDIT_DELAY_MS = 400
STATS_REFRESH_MS = 100
REFRESH_INTERVAL_MS = 3000
REFRESH_IDLE_MS = 1000
EXPAND_SLICE_SECONDS = 0.015
EXPAND_DEADLINE_CHECK = 256
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
        self.source_tree: LazyFolderTreeView | None = None
        self.db_path_getter: Callable[[], str | None] | None = None
        self.columns = dict(DEFAULT_COLUMNS)
        self.disk_slot = CancelSlot()
        self.relist_slot = CancelSlot()
        self.count_slots: dict[int, CancelSlot] = {}
        self.counts: dict[int, dict[str, tuple[int, int]]] = {}
        self.counted_keys: dict[int, str | None] = {}
        self.pending_rule_ids: set[int] = set()
        self.counting: dict[int, tuple] = {}
        self.recount_after: set[int] = set()
        self.scanning = False
        self.scanned = 0
        self.walk_roots: list[str] | None = None
        self.stale_tree = False
        self.stale_disk = False
        self.stale_rules = False
        self.stale_parents: set[str] = set()
        self.relisting: set[str] = set()
        self.expand_serial = 0
        self.build_ui()
        self.restore_state({})
        bridge = ViewerIpcBridge.instance()
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
        self.rule_list.order_changed.connect(self.publish_counts)
        self.rules_area = RulesArea(self.rule_list)
        layout.addWidget(self.rules_area)
        self.view = FolderManagerTreeView()
        self.view.set_rules_source(lambda: self.rules)
        self.model.paths_changed.connect(self.on_paths_changed)
        layout.addWidget(self.view, 1)
        self.stats_timer = QtCore.QTimer(self)
        self.stats_timer.setSingleShot(True)
        self.stats_timer.setInterval(STATS_REFRESH_MS)
        self.stats_timer.timeout.connect(self.refresh_stats)
        self.rule_timer = QtCore.QTimer(self)
        self.rule_timer.setSingleShot(True)
        self.rule_timer.timeout.connect(self.recount_pending_rules)

    def build_bar(self) -> QtWidgets.QWidget:
        self.bar = QtWidgets.QWidget()
        self.flow = FlowLayout(self.bar, margin=dpix(2), spacing=dpix(4))
        self.status_label = QtWidgets.QLabel()
        self.status_label.hide()
        self.expand_button = tool_button("chevron_down", t("Open the tree to every folder a rule marks"), t("Expand to matches"))
        self.expand_button.clicked.connect(self.expand_to_matches)
        self.columns_button = tool_button("gear", t("Columns"))
        self.columns_button.clicked.connect(self.show_column_menu)
        self.refresh_button = tool_button("refresh", t("Scan again"))
        self.refresh_button.clicked.connect(self.refresh)
        self.add_rule_button = tool_button("plus", t("Add rule"), t("Add rule"))
        self.add_rule_button.clicked.connect(self.add_rule)
        for widget in (self.status_label, self.expand_button, self.columns_button, self.refresh_button, self.add_rule_button):
            self.flow.addWidget(widget)
        return self.bar

    @property
    def model(self):
        return self.view.model_

    @property
    def rules(self) -> list[HighlightRule]:
        return self.rule_list.rules

    def save_state(self) -> dict:
        return {"rules": [rule.to_dict() for rule in self.rules], "columns": dict(self.columns)}

    def restore_state(self, state: dict) -> None:
        saved_rules = state.get("rules")
        if saved_rules is not None and not isinstance(saved_rules, list):
            AppLogger.warning(f"[FolderManager] saved rules are not a list, starting from the default rules: {saved_rules!r}")
            saved_rules = None
        rules = []
        for data in saved_rules or []:
            try:
                rules.append(HighlightRule.from_dict(data))
            except (KeyError, TypeError, AttributeError) as exc:
                AppLogger.warning(f"[FolderManager] skipped a saved rule that could not be read: {data!r} ({exc!r})")
        if saved_rules is None:
            rules = default_rules()
        for slot in self.count_slots.values():
            slot.cancel()
        self.count_slots.clear()
        self.counts.clear()
        self.counted_keys.clear()
        self.pending_rule_ids.clear()
        self.counting.clear()
        self.recount_after.clear()
        self.rule_timer.stop()
        self.rule_list.set_rules(rules)
        saved_columns = state.get("columns", {})
        if not isinstance(saved_columns, dict):
            AppLogger.warning(f"[FolderManager] saved columns are not readable, showing the default columns: {saved_columns!r}")
            saved_columns = {}
        for metric in METRICS:
            self.set_column_visible(metric, bool(saved_columns.get(metric, DEFAULT_COLUMNS[metric])))
        self.publish_counts()
        self.stale_rules = True
        self.flush_if_visible()

    def set_column_visible(self, metric: str, visible: bool) -> None:
        self.columns[metric] = visible
        self.view.set_column_visible(METRICS.index(metric) + 1, visible)

    def column_menu_items(self) -> list:
        uid = f"{id(self):x}"
        return [
            ":Columns",
            *(
                ActionKit.Action(
                    path=f"inline.folder_manager.{uid}.column.{metric}",
                    display=METRIC_LABELS[metric],
                    checked=lambda metric=metric: self.columns[metric],
                    func=lambda ctx, metric=metric: self.set_column_visible(metric, not self.columns[metric]),
                )
                for metric in METRICS
            ),
        ]

    def show_column_menu(self) -> None:
        spec = Menu.session(self).menu(self.column_menu_items())
        if spec is not None:
            spec.exec(self.columns_button.mapToGlobal(QtCore.QPoint(0, self.columns_button.height())))

    def bind_folder_tree(self, tree: LazyFolderTreeView, db_path_getter: Callable[[], str | None]) -> None:
        self.source_tree = tree
        self.db_path_getter = db_path_getter
        tree.folders_set.connect(self.on_folders_set)
        self.stale_tree = True
        self.flush_if_visible()

    def is_my_db(self, db: str) -> bool:
        if not db:
            return True
        db_path = self.db_path_getter() if self.db_path_getter is not None else None
        return bool(db_path) and normalize_path(data_db_path(db)) == normalize_path(db_path)

    def on_folders_set(self) -> None:
        self.stale_tree = True
        self.flush_if_visible()

    def on_folder_changed(self, db: str) -> None:
        if self.is_my_db(db):
            self.stale_tree = True
            self.flush_later_if_visible()

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
        self.flush()

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
        if self.stale_tree:
            self.stale_tree = False
            self.sync_from_tree()
        if self.source_tree is None:
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
            self.recount(self.rules)

    def sync_from_tree(self) -> None:
        if self.source_tree is None:
            return
        source = self.source_tree.model_
        roots = [normalize_path(root) for root in source.roots or ()]
        excluded = {normalize_path(path) for path in source.excluded or ()}
        pattern = source.ignore_pattern_re
        model = self.model
        current_pattern = model.ignore_pattern_re.pattern if model.ignore_pattern_re is not None else None
        new_pattern = pattern.pattern if pattern is not None else None
        if (roots, excluded, new_pattern) != (list(model.roots or ()), set(model.excluded or ()), current_pattern):
            state = self.view.get_state()
            self.view.set_folders(roots, excluded, pattern)
            self.view.set_state_async(state)
        self.stale_disk = True
        self.stale_rules = True

    def refresh(self) -> None:
        self.stale_disk = True
        self.stale_rules = True
        self.flush()

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

    def update_status(self) -> None:
        self.status_label.setText(t("Scanning… {count}", count=f"{self.scanned:,}"))
        self.status_label.setVisible(self.scanning)

    def add_rule(self) -> None:
        rule = new_rule(self.rules)
        self.rule_list.append_row(rule)
        self.publish_counts()
        self.recount([rule])

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

    def on_rule_edited(self, rule: HighlightRule) -> None:
        if self.count_key(rule) != self.counted_keys.get(id(rule)):
            self.pending_rule_ids.add(id(rule))
            self.rule_timer.start(RULE_EDIT_DELAY_MS)
        self.publish_counts()

    def recount_pending_rules(self) -> None:
        pending, self.pending_rule_ids = self.pending_rule_ids, set()
        self.recount([rule for rule in self.rules if id(rule) in pending])

    @staticmethod
    def count_key(rule: HighlightRule) -> str | None:
        if not rule.enabled or not rule.shows_count():
            return None
        return json.dumps(rule.bars, sort_keys=True, default=str)

    def recount(self, rules: Sequence[HighlightRule]) -> None:
        db_path = self.db_path_getter() if self.db_path_getter is not None else None
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

    def expand_to_matches(self) -> None:
        self.expand_serial += 1
        serial = self.expand_serial
        disk = self.model.disk
        lists = [list(disk.nodes)] if disk is not None else []
        lists.extend(list(counts) for _rule, counts in self.model.rule_counts)
        candidates = chain.from_iterable(lists)
        roots = [normalize_path(root) for root in self.model.roots or ()]
        seen: set[str] = set()
        matches: list[str] = []

        def scan_slice() -> None:
            if serial != self.expand_serial:
                return
            deadline = time.perf_counter() + EXPAND_SLICE_SECONDS
            model = self.model
            for number, path in enumerate(candidates):
                if path not in seen:
                    seen.add(path)
                    current = model.disk
                    if model.badges_for(path, current.values(path) if current is not None else None):
                        matches.append(path)
                if number % EXPAND_DEADLINE_CHECK == 0 and time.perf_counter() >= deadline:
                    QtCore.QTimer.singleShot(0, scan_slice)
                    return
            self.dispatcher.post(lambda: find_folders())

        def find_folders() -> None:
            folders = folders_to_open(matches, roots)
            self.dispatcher.invoke(lambda: self.open_folders(serial, folders))

        scan_slice()

    def open_folders(self, serial: int, folders: list[str]) -> None:
        if serial == self.expand_serial:
            self.view.expand_folders(folders)


class FolderManagerPlugin(BasePanelPlugin):
    NAME = "folder_manager"
    DISPLAY_NAME = "Folder Manager"
    PRIORITY = 0
    SOURCE = "Builtin"
    DEFAULT_ENABLED = True
    STANDALONE_AVAILABLE = False

    def __init__(self):
        self.widget: FolderManagerWidget | None = None
        self.state: dict = {}

    def save_ui_state(self) -> dict:
        if self.widget is not None:
            try:
                self.state = self.widget.save_state()
            except RuntimeError as exc:
                AppLogger.warning("[FolderManager] save_state failed", exc=exc)
        return dict(self.state)

    def restore_ui_state(self, state: dict) -> None:
        self.state = dict(state)
        if self.widget is not None:
            try:
                self.widget.restore_state(self.state)
            except RuntimeError as exc:
                AppLogger.warning("[FolderManager] restore_state failed", exc=exc)

    def create_widget(self) -> FolderManagerWidget:
        widget = FolderManagerWidget()
        self.widget = widget
        widget.destroyed.connect(lambda *_: self.forget(widget))
        if self.state:
            widget.restore_state(self.state)
        host = InstanceRegistry.instance().get_host_window()
        tree = getattr(host, "folder_view", None)
        if tree is None:
            AppLogger.warning("[FolderManager] no folder tree is available, the panel stays empty")
        else:
            widget.bind_folder_tree(tree, lambda: host.database_path)
        return widget

    def forget(self, widget: FolderManagerWidget) -> None:
        if self.widget is widget:
            self.widget = None

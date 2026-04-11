from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from functools import partial

from PySide6 import QtWidgets, QtCore, QtGui

from wafer.plugin import BasePanelPlugin
from wafer.plugin.collector.base import BaseCollector
from wafer.utils.formatting import dpix
from wafer.utils.logs import AppLogger
from wafer.utils.notifier import Notifier
from wafer.utils.paths import list_setting_db_names, data_db_path
from wafer.core.db.db_utils import apply_read_pragmas
from wafer.core.qt.dispatcher import Dispatcher, CancelSlot
from .settings import MODE_BLACKLIST, MODE_WHITELIST, SORT_NAME, SORT_COUNT
from .settings import read_sort_config, write_sort_config

_CHECK_COL = 0
_KEY_COL = 1
_COUNT_COL = 2


class ExifSettingsPanelPlugin(BasePanelPlugin):
    NAME = "exiftool_settings"
    DISPLAY_NAME = "ExifTool Settings"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 50

    def create_widget(self) -> QtWidgets.QWidget:
        return ExifSettingsWidget()


class ExifSettingsWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher()
        self._cancel = CancelSlot()

        from .settings import read_filter_config

        self._filter_mode, self._filter_keys = read_filter_config()
        self._saved_mode = self._filter_mode
        self._saved_keys = set(self._filter_keys)

        self._mode_combo = QtWidgets.QComboBox()
        self._mode_combo.addItem("Blacklist (block selected)", MODE_BLACKLIST)
        self._mode_combo.addItem("Whitelist (use selected only)", MODE_WHITELIST)
        self._mode_combo.setCurrentIndex(0 if self._filter_mode == MODE_BLACKLIST else 1)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        tabs = QtWidgets.QTabWidget()
        self._key_browser = _KeyBrowserTab(self._filter_mode, self._filter_keys, self._dispatcher, self._cancel)
        self._sample_preview = _SamplePreviewTab(self._filter_mode, self._filter_keys, self._dispatcher, self._cancel)
        tabs.addTab(self._sample_preview, "Sample Preview")
        tabs.addTab(self._key_browser, "Key Browser")

        self._sample_preview.filter_keys_changed.connect(self._on_preview_keys_changed)
        self._key_browser.filter_keys_changed.connect(self._on_browser_keys_changed)

        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addWidget(QtWidgets.QLabel("Filter Mode:"))
        bottom_layout.addWidget(self._mode_combo)
        bottom_layout.addStretch()

        save_btn = QtWidgets.QPushButton("Save && Recollect (All DBs)")
        save_btn.clicked.connect(self._on_save)
        bottom_layout.addWidget(save_btn)

        reset_btn = QtWidgets.QPushButton("Cancel")
        reset_btn.clicked.connect(self._on_reset)
        bottom_layout.addWidget(reset_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom_layout)

        self._dirty = False
        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._refresh_key_browser)
        self._connect_bridge()

    def _connect_bridge(self):
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

        bridge = ViewerIpcBridge.instance()
        if bridge:
            bridge.db_content_updated.connect(self._on_db_updated)

    def _on_db_updated(self, db: str):
        if self.isVisible():
            self._debounce_timer.start()
        else:
            self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty:
            self._dirty = False
            self._refresh_key_browser()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._debounce_timer.stop()

    @QtCore.Slot()
    def _refresh_key_browser(self):
        self._key_browser.refresh()

    def _on_mode_changed(self, index: int):
        new_mode = self._mode_combo.itemData(index)
        if new_mode == self._filter_mode:
            return
        all_keys = self._key_browser.all_known_keys()
        if all_keys:
            self._filter_keys = all_keys - self._filter_keys
        self._filter_mode = new_mode
        self._key_browser.set_filter(new_mode, self._filter_keys)
        self._sample_preview.set_filter(new_mode, self._filter_keys)

    def _on_preview_keys_changed(self, new_keys: set):
        self._filter_keys = new_keys
        self._key_browser.set_filter_keys(new_keys)

    def _on_browser_keys_changed(self, new_keys: set):
        self._filter_keys = new_keys
        self._sample_preview.set_filter_keys(new_keys)

    def _on_save(self):
        current_keys = self._key_browser.collect_filter_keys()
        has_changes = self._filter_mode != self._saved_mode or current_keys != self._saved_keys

        do_purge = False
        do_recollect = False
        if has_changes:
            dlg = _SaveConfirmDialog(parent=self)
            if dlg.exec() != QtWidgets.QDialog.Accepted:
                return
            do_purge = dlg.purge()
            do_recollect = dlg.recollect()

        self._filter_keys = current_keys
        from .settings import write_filter_config

        write_filter_config(self._filter_mode, self._filter_keys)
        BaseCollector.notify_to("exiftool")
        self._sample_preview.set_filter_keys(self._filter_keys)

        self._saved_mode = self._filter_mode
        self._saved_keys = set(self._filter_keys)

        if do_purge or do_recollect:
            db_names = list_setting_db_names()
            if db_names:
                purge_keys = self._compute_purge_keys() if do_purge else []
                self._send_purge_keys(
                    db_names,
                    purge_keys,
                    "exiftool",
                    re_collect=do_recollect,
                )

        if do_purge:
            action = "saved + purge & recollect" if do_recollect else "saved + purge"
        else:
            action = "saved"
        Notifier.info(f"ExifTool filter {action} ({self._filter_mode}, {len(self._filter_keys)} keys)")

    def _on_reset(self):
        self._filter_mode = self._saved_mode
        self._filter_keys = set(self._saved_keys)

        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0 if self._filter_mode == MODE_BLACKLIST else 1)
        self._mode_combo.blockSignals(False)

        self._key_browser.set_filter(self._filter_mode, self._filter_keys)
        self._sample_preview.set_filter(self._filter_mode, self._filter_keys)

        Notifier.info("ExifTool filter settings reverted")

    def _compute_purge_keys(self) -> list[str]:
        if self._filter_mode == MODE_BLACKLIST:
            return [f"exiftool.{k}" for k in self._filter_keys]
        all_keys = {k for k, _ in _query_all_keys_merged()}
        return [f"exiftool.{k}" for k in (all_keys - self._filter_keys)]

    @staticmethod
    def _send_purge_keys(
        db_names: list[str],
        keys: list[str],
        collector: str,
        *,
        re_collect: bool,
    ):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning("[ExifToolSettings] No IPC node available")
            return
        for db in db_names:
            node.send_reliable(
                "purge.keys",
                {"keys": keys, "collector": collector, "re_collect": re_collect},
                dst="indexer",
                db=db,
            )


class _KeyBrowserTab(QtWidgets.QWidget):
    filter_keys_changed = QtCore.Signal(set)

    def __init__(
        self,
        filter_mode: str,
        filter_keys: set[str],
        dispatcher: Dispatcher,
        cancel: CancelSlot,
        parent=None,
    ):
        super().__init__(parent)
        self._filter_mode = filter_mode
        self._filter_keys = set(filter_keys)
        self._dispatcher = dispatcher
        self._cancel = cancel
        self._sort_mode, self._sort_ascending = read_sort_config()

        self._check_all_btn = QtWidgets.QPushButton("Check All")
        self._check_all_btn.clicked.connect(self._on_check_all)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(self._check_all_btn)

        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Filter keys...")
        self._search.textChanged.connect(self._apply_filter)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels([self._check_header(), "Key", "Count"])
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.itemClicked.connect(self._on_item_clicked)
        h = self._tree.header()
        h.setStretchLastSection(False)
        h.setSectionResizeMode(_CHECK_COL, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionResizeMode(_KEY_COL, QtWidgets.QHeaderView.Stretch)
        h.setSectionResizeMode(_COUNT_COL, QtWidgets.QHeaderView.ResizeToContents)
        h.setSectionsClickable(True)
        h.sectionClicked.connect(self._on_header_sort)
        self._pre_click_selection: list[QtWidgets.QTreeWidgetItem] = []
        self._tree.viewport().installEventFilter(self)

        self._sample_header = QtWidgets.QLabel()
        self._sample_header.setWordWrap(True)
        self._sample_header.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._sample_header.setVisible(False)
        self._sample_table = QtWidgets.QTableWidget()
        self._sample_table.setColumnCount(3)
        self._sample_table.setHorizontalHeaderLabels(["DB", "File", "Value"])
        self._sample_table.horizontalHeader().setStretchLastSection(True)
        self._sample_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._sample_table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self._sample_table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._sample_table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._sample_table.verticalHeader().setVisible(False)
        self._sample_table.setVisible(False)

        self._placeholder = QtWidgets.QLabel("Click a key to see sample values")
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color: palette(mid); padding: {dpix(20)}px;")

        sample_widget = QtWidgets.QWidget()
        sample_layout = QtWidgets.QVBoxLayout(sample_widget)
        sample_layout.setContentsMargins(0, 0, 0, 0)
        sample_layout.setSpacing(dpix(2))
        sample_layout.addWidget(self._sample_header)
        sample_layout.addWidget(self._sample_table, 1)
        sample_layout.addWidget(self._placeholder, 1)
        self._sample_widget = sample_widget

        tree_container = QtWidgets.QWidget()
        tree_layout = QtWidgets.QVBoxLayout(tree_container)
        tree_layout.setContentsMargins(0, 0, 0, 0)
        tree_layout.setSpacing(dpix(4))
        tree_layout.addWidget(self._search)
        tree_layout.addWidget(self._tree, 1)

        self._splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self._splitter.addWidget(tree_container)
        self._splitter.addWidget(sample_widget)
        self._splitter.setStretchFactor(0, 6)
        self._splitter.setStretchFactor(1, 4)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))
        layout.addLayout(top_row)
        layout.addWidget(self._splitter, 1)

        self._key_data: list[tuple[str, int]] = []
        self._load_keys()

    def eventFilter(self, obj, event):
        if hasattr(self, "_tree") and obj is self._tree.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
            self._pre_click_selection = list(self._tree.selectedItems())
        return super().eventFilter(obj, event)

    def _check_header(self) -> str:
        return "Block" if self._filter_mode == MODE_BLACKLIST else "Use"

    def _on_check_all(self):
        all_keys = self.all_known_keys()
        if all_keys and self._filter_keys >= all_keys:
            self._filter_keys.clear()
        else:
            self._filter_keys = set(all_keys)
        self._update_check_all_label()
        self._build_tree()
        self.filter_keys_changed.emit(set(self._filter_keys))

    def _update_check_all_label(self):
        all_keys = self.all_known_keys()
        all_checked = all_keys and self._filter_keys >= all_keys
        self._check_all_btn.setText("Uncheck All" if all_checked else "Check All")

    def _on_header_sort(self, section: int):
        if section == _CHECK_COL:
            return
        new_mode = SORT_NAME if section == _KEY_COL else SORT_COUNT
        if new_mode == self._sort_mode:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_mode = new_mode
            self._sort_ascending = new_mode == SORT_NAME
        write_sort_config(self._sort_mode, self._sort_ascending)
        self._build_tree()

    def refresh(self):
        self._load_keys()

    def _load_keys(self):
        cancel = self._cancel.renew()

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_all_keys_merged()

        def _done(result):
            if cancel.is_cancelled():
                return
            self._key_data = result
            self._update_check_all_label()
            self._build_tree()

        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(_done, _bg())))

    def _sorted_entries(self, entries: list[tuple]) -> list[tuple]:
        if self._sort_mode == SORT_COUNT:
            return sorted(entries, key=lambda e: e[1], reverse=not self._sort_ascending)
        return sorted(entries, key=lambda e: e[0].lower(), reverse=not self._sort_ascending)

    def _build_tree(self):
        scrollbar = self._tree.verticalScrollBar()
        scroll_pos = scrollbar.value() if scrollbar else 0
        selected_keys = set()
        for item in self._tree.selectedItems():
            key = item.data(_KEY_COL, QtCore.Qt.UserRole)
            if key:
                selected_keys.add(key)
            elif item.childCount() > 0:
                selected_keys.add(item.text(_KEY_COL))
        self._tree.clear()
        key_label = "Key"
        count_label = "Count"
        if self._sort_mode == SORT_NAME:
            key_label += " \u25b2" if self._sort_ascending else " \u25bc"
        else:
            count_label += " \u25b2" if self._sort_ascending else " \u25bc"
        self._tree.setHeaderLabels([self._check_header(), key_label, count_label])
        db_keys = {k for k, _ in self._key_data}
        merged = list(self._key_data)
        for fk in sorted(self._filter_keys - db_keys):
            merged.append((fk, 0))
        groups: dict[str, list[tuple[str, int, str]]] = {}
        for key, freq in merged:
            parts = key.split("/", 1)
            group = parts[0] + "/" if len(parts) > 1 else ""
            leaf = parts[1] if len(parts) > 1 else parts[0]
            groups.setdefault(group, []).append((leaf, freq, key))

        ungrouped = groups.pop("", [])
        for leaf, freq, full_key in self._sorted_entries(ungrouped):
            item = self._make_leaf_item(leaf, freq, full_key)
            self._tree.addTopLevelItem(item)

        group_order = sorted(groups.keys())
        if self._sort_mode == SORT_COUNT:
            group_order = sorted(groups.keys(), key=lambda g: sum(f for _, f, _ in groups[g]), reverse=not self._sort_ascending)

        for group_name in group_order:
            entries = groups[group_name]
            group_item = QtWidgets.QTreeWidgetItem(["", group_name, ""])
            group_item.setFlags(group_item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate)
            total_freq = sum(f for _, f, _ in entries)
            group_item.setText(_COUNT_COL, f"{total_freq:,}")
            all_in = all(fk in self._filter_keys for _, _, fk in entries)
            all_out = all(fk not in self._filter_keys for _, _, fk in entries)
            if all_in:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.Checked)
            elif all_out:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.Unchecked)
            else:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.PartiallyChecked)
            for leaf, freq, full_key in self._sorted_entries(entries):
                child = self._make_leaf_item(leaf, freq, full_key)
                group_item.addChild(child)
            self._tree.addTopLevelItem(group_item)

        self._tree.expandAll()
        self._apply_filter(self._search.text())
        self._restore_selection(selected_keys)
        if scroll_pos:
            self._tree.verticalScrollBar().setValue(scroll_pos)

    def _restore_selection(self, selected_keys: set[str]):
        if not selected_keys:
            return
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            key = top.data(_KEY_COL, QtCore.Qt.UserRole)
            if (key and key in selected_keys) or (not key and top.text(_KEY_COL) in selected_keys):
                top.setSelected(True)
            for j in range(top.childCount()):
                child = top.child(j)
                ckey = child.data(_KEY_COL, QtCore.Qt.UserRole)
                if ckey and ckey in selected_keys:
                    child.setSelected(True)
        self._tree.blockSignals(False)

    def _make_leaf_item(self, label: str, freq: int, full_key: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(["", label, f"{freq:,}"])
        item.setData(_KEY_COL, QtCore.Qt.UserRole, full_key)
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        in_keys = full_key in self._filter_keys
        item.setCheckState(_CHECK_COL, QtCore.Qt.Checked if in_keys else QtCore.Qt.Unchecked)
        return item

    def _apply_filter(self, text: str):
        text_lower = text.lower()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.childCount() == 0:
                key = top.data(_KEY_COL, QtCore.Qt.UserRole) or top.text(_KEY_COL)
                top.setHidden(text_lower not in key.lower())
            else:
                any_visible = False
                for j in range(top.childCount()):
                    child = top.child(j)
                    key = child.data(_KEY_COL, QtCore.Qt.UserRole) or child.text(_KEY_COL)
                    hidden = text_lower not in key.lower()
                    child.setHidden(hidden)
                    if not hidden:
                        any_visible = True
                top.setHidden(not any_visible)

    def _sync_selected_checks(self, clicked: QtWidgets.QTreeWidgetItem):
        pre_selection = self._pre_click_selection
        if clicked not in pre_selection or len(pre_selection) < 2:
            return
        new_state = clicked.checkState(_CHECK_COL)
        self._tree.blockSignals(True)
        for item in pre_selection:
            if item is clicked:
                continue
            key = item.data(_KEY_COL, QtCore.Qt.UserRole)
            if key or item.childCount() > 0:
                item.setCheckState(_CHECK_COL, new_state)
        self._tree.blockSignals(False)

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int):
        if column == _CHECK_COL:
            self._sync_selected_checks(item)
            self._filter_keys = self.collect_filter_keys()
            self._update_check_all_label()
            self.filter_keys_changed.emit(set(self._filter_keys))
        full_key = item.data(_KEY_COL, QtCore.Qt.UserRole)
        if not full_key:
            return
        cancel = self._cancel.renew()

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_sample_values_all(f"exiftool.{full_key}")

        def _done(samples: list[tuple[str, str, str]]):
            if cancel.is_cancelled():
                return
            freq = 0
            for k, f in self._key_data:
                if k == full_key:
                    freq = f
                    break
            self._sample_header.setText(f"<b>Key:</b> exiftool.{full_key} &nbsp; <b>Affected:</b> {freq:,} files")
            self._sample_table.setRowCount(len(samples))
            for row, (db, file_path, value) in enumerate(samples):
                self._sample_table.setItem(row, 0, QtWidgets.QTableWidgetItem(db))
                self._sample_table.setItem(row, 1, QtWidgets.QTableWidgetItem(os.path.basename(file_path)))
                val_str = str(value) if value is not None else ""
                self._sample_table.setItem(row, 2, QtWidgets.QTableWidgetItem(val_str[:300]))
            self._placeholder.setVisible(False)
            self._sample_header.setVisible(True)
            self._sample_table.setVisible(True)

        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(_done, _bg())))

    def collect_filter_keys(self) -> set[str]:
        result: set[str] = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.childCount() == 0:
                if top.checkState(_CHECK_COL) == QtCore.Qt.Checked:
                    key = top.data(_KEY_COL, QtCore.Qt.UserRole)
                    if key:
                        result.add(key)
            else:
                for j in range(top.childCount()):
                    child = top.child(j)
                    if child.checkState(_CHECK_COL) == QtCore.Qt.Checked:
                        key = child.data(_KEY_COL, QtCore.Qt.UserRole)
                        if key:
                            result.add(key)
        return result

    def all_known_keys(self) -> set[str]:
        return {k for k, _ in self._key_data} | self._filter_keys

    def set_filter(self, mode: str, keys: set[str]):
        self._filter_mode = mode
        self._filter_keys = set(keys)
        self._update_check_all_label()
        self._build_tree()

    def set_filter_keys(self, keys: set[str]):
        self._filter_keys = set(keys)
        self._update_check_all_label()
        self._build_tree()


class _SamplePreviewTab(QtWidgets.QWidget):
    filter_keys_changed = QtCore.Signal(set)

    def __init__(self, filter_mode: str, filter_keys: set[str], dispatcher: Dispatcher, cancel: CancelSlot, parent=None):
        super().__init__(parent)
        self._filter_mode = filter_mode
        self._filter_keys = set(filter_keys)
        self._meta: dict[str, str] = {}
        self._current_path: str | None = None
        self._dispatcher = dispatcher
        self._cancel = cancel
        self.setAcceptDrops(True)

        self._drop_label = QtWidgets.QLabel("Drop a file here to preview ExifTool tags")
        self._drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self._drop_label.setMinimumHeight(dpix(60))
        self._drop_label.setStyleSheet(f"border: {dpix(2)}px dashed palette(mid); border-radius: {dpix(6)}px; padding: {dpix(12)}px;")

        self._thumb = QtWidgets.QLabel()
        self._thumb.setAlignment(QtCore.Qt.AlignCenter)
        self._thumb.setFixedWidth(dpix(240))
        self._thumb.setMinimumHeight(dpix(160))
        self._thumb.setScaledContents(False)

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(3)
        self._table.setHorizontalHeaderLabels([self._check_header(), "Key", "Value"])
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        self._table.horizontalHeader().setSectionResizeMode(1, QtWidgets.QHeaderView.Interactive)
        self._table.horizontalHeader().setSectionResizeMode(2, QtWidgets.QHeaderView.Stretch)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self._table.verticalHeader().setVisible(False)
        self._table.cellChanged.connect(self._on_cell_changed)

        content_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        content_splitter.addWidget(self._thumb)
        content_splitter.addWidget(self._table)
        content_splitter.setStretchFactor(0, 0)
        content_splitter.setStretchFactor(1, 1)
        self._content_splitter = content_splitter
        content_splitter.setVisible(False)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))
        layout.addWidget(self._drop_label)
        layout.addWidget(content_splitter, 1)

    def _check_header(self) -> str:
        return "Block" if self._filter_mode == MODE_BLACKLIST else "Use"

    def dragEnterEvent(self, event: QtGui.QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QtGui.QDragMoveEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QtGui.QDropEvent):
        urls = event.mimeData().urls()
        if not urls:
            return
        path = urls[0].toLocalFile()
        if path:
            self._preview_file(path)

    def _preview_file(self, path: str):
        cancel = self._cancel.renew()

        def task():
            if cancel.is_cancelled():
                return
            try:
                from .parser import ExifToolProcess, flatten
                from ._downloader import get_exiftool_path

                exe = get_exiftool_path()
                if exe is None:
                    self._dispatcher.invoke(lambda: Notifier.warning("ExifTool not found"))
                    return
                proc = ExifToolProcess(exe)
                proc.start()
                try:
                    data = proc.query(path)
                finally:
                    proc.stop()
                if data is None:
                    self._dispatcher.invoke(lambda: Notifier.warning("ExifTool returned no data"))
                    return
                meta, _ = flatten(data)
            except Exception as e:
                AppLogger.warning(f"[ExifToolSettings] Preview failed: {e}", exc=e)
                self._dispatcher.invoke(lambda: Notifier.warning(f"Preview failed: {e}"))
                return
            if cancel.is_cancelled():
                return
            pixmap = QtGui.QImage(path)
            if not pixmap.isNull():
                scaled = pixmap.scaled(
                    dpix(240),
                    dpix(240),
                    QtCore.Qt.KeepAspectRatio,
                    QtCore.Qt.SmoothTransformation,
                )
            else:
                scaled = None
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._apply_preview(path, meta, scaled, cancel))

        self._dispatcher.post(task)

    def _apply_preview(self, path: str, meta: dict, scaled_image, cancel):
        if cancel.is_cancelled():
            return
        self._current_path = path
        self._meta = meta
        if scaled_image is not None:
            self._thumb.setPixmap(QtGui.QPixmap.fromImage(scaled_image))
        else:
            self._thumb.clear()
        self._rebuild_table()
        self._content_splitter.setVisible(True)
        self._update_drop_label()

    def _blocked_count(self) -> int:
        if self._filter_mode == MODE_BLACKLIST:
            return sum(1 for k in self._meta if k in self._filter_keys)
        return sum(1 for k in self._meta if k not in self._filter_keys)

    def _update_drop_label(self):
        if self._current_path:
            self._drop_label.setText(f"Previewing: {Path(self._current_path).name} ({len(self._meta)} keys, {self._blocked_count()} blocked)")

    def _rebuild_table(self):
        from wafer.core.color.theme import ThemeManager

        palette = ThemeManager.instance().palette
        muted_fg = QtGui.QColor(palette.text_muted)

        self._table.blockSignals(True)
        self._table.setHorizontalHeaderLabels([self._check_header(), "Key", "Value"])
        self._table.setRowCount(0)
        self._table.setRowCount(len(self._meta))
        for row, (key, value) in enumerate(sorted(self._meta.items())):
            in_keys = key in self._filter_keys
            if self._filter_mode == MODE_BLACKLIST:
                blocked = in_keys
            else:
                blocked = not in_keys
            check_item = QtWidgets.QTableWidgetItem()
            check_item.setFlags(check_item.flags() | QtCore.Qt.ItemIsUserCheckable)
            check_item.setCheckState(QtCore.Qt.Checked if in_keys else QtCore.Qt.Unchecked)
            check_item.setData(QtCore.Qt.UserRole, key)
            key_item = QtWidgets.QTableWidgetItem(key)
            val_str = str(value) if value is not None else ""
            val_item = QtWidgets.QTableWidgetItem(val_str[:300])
            if blocked:
                for item in (key_item, val_item):
                    item.setForeground(muted_fg)
                    font = item.font()
                    font.setStrikeOut(True)
                    item.setFont(font)
            self._table.setItem(row, 0, check_item)
            self._table.setItem(row, 1, key_item)
            self._table.setItem(row, 2, val_item)
        self._table.blockSignals(False)

    def _on_cell_changed(self, row: int, column: int):
        if column != 0:
            return
        check_item = self._table.item(row, 0)
        if not check_item:
            return
        key = check_item.data(QtCore.Qt.UserRole)
        if not key:
            return
        checked = check_item.checkState() == QtCore.Qt.Checked
        if checked:
            self._filter_keys.add(key)
        else:
            self._filter_keys.discard(key)
        self._rebuild_table()
        self._update_drop_label()
        self.filter_keys_changed.emit(set(self._filter_keys))

    def set_filter(self, mode: str, keys: set[str]):
        self._filter_mode = mode
        self._filter_keys = set(keys)
        if self._meta:
            self._rebuild_table()
            self._update_drop_label()

    def set_filter_keys(self, keys: set[str]):
        self._filter_keys = set(keys)
        if self._meta:
            self._rebuild_table()
            self._update_drop_label()


class _SaveConfirmDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Save ExifTool Filter Settings")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))
        layout.addWidget(QtWidgets.QLabel("Filter settings have been modified.\nThis will apply to all databases."))

        self._purge_cb = QtWidgets.QCheckBox("Purge existing ExifTool data")
        self._purge_cb.setChecked(True)
        self._recollect_cb = QtWidgets.QCheckBox("Recollect after purge")
        self._recollect_cb.setChecked(True)
        self._purge_cb.toggled.connect(self._recollect_cb.setEnabled)
        layout.addWidget(self._purge_cb)
        layout.addWidget(self._recollect_cb)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        save_btn = QtWidgets.QPushButton("Save")
        cancel_btn = QtWidgets.QPushButton("Cancel")
        save_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(save_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

    def purge(self) -> bool:
        return self._purge_cb.isChecked()

    def recollect(self) -> bool:
        return self._purge_cb.isChecked() and self._recollect_cb.isChecked()


def _query_all_keys_merged() -> list[tuple[str, int]]:
    merged: dict[str, int] = {}
    for db_name in list_setting_db_names():
        db_path = data_db_path(db_name)
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = None
        try:
            conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
            apply_read_pragmas(conn)
            rows = conn.execute("SELECT SUBSTR(key, 10) AS short_key, COUNT(*) AS freq FROM meta_info WHERE key LIKE 'exiftool.%' GROUP BY short_key").fetchall()
            for row in rows:
                merged[row[0]] = merged.get(row[0], 0) + row[1]
        except Exception as e:
            AppLogger.warning(f"[ExifToolSettings] Failed to query keys for {db_name}: {e}", exc=e)
        finally:
            if conn:
                conn.close()
    return sorted(merged.items(), key=lambda x: x[0])


def _query_sample_values_all(key: str, limit: int = 10) -> list[tuple[str, str, str]]:
    results: list[tuple[str, str, str]] = []
    remaining = limit
    for db_name in list_setting_db_names():
        if remaining <= 0:
            break
        db_path = data_db_path(db_name)
        uri = Path(db_path).resolve().as_uri() + "?mode=ro"
        conn = None
        try:
            conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
            apply_read_pragmas(conn)
            rows = conn.execute(
                "SELECT path, value FROM meta_info WHERE key = ? LIMIT ?",
                (key, remaining),
            ).fetchall()
            for row in rows:
                results.append((db_name, row[0], row[1]))
            remaining -= len(rows)
        except Exception as e:
            AppLogger.warning(f"[ExifToolSettings] Sample query failed for {key} in {db_name}: {e}", exc=e)
        finally:
            if conn:
                conn.close()
    return results

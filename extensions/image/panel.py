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
from .settings import MODE_BLACKLIST, MODE_WHITELIST

_SORT_NAME = 0
_SORT_COUNT = 1

_CHECK_COL = 0
_KEY_COL = 1
_COUNT_COL = 2


class ExifSettingsPanelPlugin(BasePanelPlugin):
    NAME = "exif_settings"
    DISPLAY_NAME = "EXIF Settings"
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
        self._mode_combo.addItem("Blacklist (Block selected)", MODE_BLACKLIST)
        self._mode_combo.addItem("Whitelist (Use selected only)", MODE_WHITELIST)
        self._mode_combo.setCurrentIndex(0 if self._filter_mode == MODE_BLACKLIST else 1)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        tabs = QtWidgets.QTabWidget()
        self._key_browser = _KeyBrowserTab(
            self._filter_mode, self._filter_keys, self._dispatcher, self._cancel
        )
        self._sample_preview = _SamplePreviewTab(self._filter_mode, self._filter_keys)
        tabs.addTab(self._key_browser, "Key Browser")
        tabs.addTab(self._sample_preview, "Sample Preview")

        self._sample_preview.filter_keys_changed.connect(self._on_preview_keys_changed)

        bottom_layout = QtWidgets.QHBoxLayout()
        bottom_layout.addWidget(QtWidgets.QLabel("Filter Mode:"))
        bottom_layout.addWidget(self._mode_combo)
        bottom_layout.addStretch()

        save_btn = QtWidgets.QPushButton("Save && Recollect")
        save_btn.clicked.connect(self._on_save)
        bottom_layout.addWidget(save_btn)

        reset_btn = QtWidgets.QPushButton("Reset")
        reset_btn.clicked.connect(self._on_reset)
        bottom_layout.addWidget(reset_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))
        layout.addWidget(tabs, 1)
        layout.addLayout(bottom_layout)

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
        BaseCollector.notify_to("exif")
        self._sample_preview.set_filter_keys(self._filter_keys)

        self._saved_mode = self._filter_mode
        self._saved_keys = set(self._filter_keys)

        if do_purge:
            db_names = list_setting_db_names()
            if db_names:
                self._send_purge_collector(db_names, "exif", re_collect=do_recollect)

        if do_purge:
            action = "saved + purge & recollect" if do_recollect else "saved + purge"
        else:
            action = "saved"
        Notifier.info(f"EXIF filter {action} ({self._filter_mode}, {len(self._filter_keys)} keys)")

    def _on_reset(self):
        self._filter_mode = MODE_BLACKLIST
        self._filter_keys = set()
        from .settings import write_filter_config

        write_filter_config(self._filter_mode, self._filter_keys)
        BaseCollector.notify_to("exif")

        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0)
        self._mode_combo.blockSignals(False)

        self._key_browser.set_filter(self._filter_mode, self._filter_keys)
        self._sample_preview.set_filter(self._filter_mode, self._filter_keys)

        self._saved_mode = self._filter_mode
        self._saved_keys = set()

        db_names = list_setting_db_names()
        if db_names:
            self._send_purge_collector(db_names, "exif", re_collect=True)

        Notifier.info("EXIF filter reset to defaults")

    @staticmethod
    def _send_purge_collector(db_names: list[str], collector: str, *, re_collect: bool):
        from wafer.core.commands.binding.instance_registry import InstanceRegistry

        node = InstanceRegistry.instance().resolve_node()
        if not node:
            AppLogger.warning("[ExifSettings] No IPC node available")
            return
        for db in db_names:
            node.send_reliable(
                "purge.collector",
                {"collector": collector, "re_collect": re_collect},
                dst="indexer",
                db=db,
            )


class _KeyBrowserTab(QtWidgets.QWidget):
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
        self._sort_mode = _SORT_NAME

        self._db_combo = QtWidgets.QComboBox()
        self._db_combo.currentTextChanged.connect(self._load_keys)
        self._sort_combo = QtWidgets.QComboBox()
        self._sort_combo.addItems(["Name", "Count"])
        self._sort_combo.currentIndexChanged.connect(self._on_sort_changed)

        check_all_btn = QtWidgets.QPushButton("Check All")
        check_all_btn.clicked.connect(self._on_check_all)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(check_all_btn)
        top_row.addSpacing(dpix(8))
        top_row.addWidget(QtWidgets.QLabel("Database:"))
        top_row.addWidget(self._db_combo, 1)
        top_row.addSpacing(dpix(8))
        top_row.addWidget(QtWidgets.QLabel("Sort:"))
        top_row.addWidget(self._sort_combo)

        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText("Filter keys...")
        self._search.textChanged.connect(self._apply_filter)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels([self._check_header(), "Key", "Count"])
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.header().setStretchLastSection(False)
        self._tree.header().setSectionResizeMode(_CHECK_COL, QtWidgets.QHeaderView.ResizeToContents)
        self._tree.header().setSectionResizeMode(_KEY_COL, QtWidgets.QHeaderView.Stretch)
        self._tree.header().setSectionResizeMode(_COUNT_COL, QtWidgets.QHeaderView.ResizeToContents)

        self._sample_header = QtWidgets.QLabel()
        self._sample_header.setWordWrap(True)
        self._sample_header.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._sample_header.setVisible(False)
        self._sample_table = QtWidgets.QTableWidget()
        self._sample_table.setColumnCount(2)
        self._sample_table.setHorizontalHeaderLabels(["File", "Value"])
        self._sample_table.horizontalHeader().setStretchLastSection(True)
        self._sample_table.horizontalHeader().setSectionResizeMode(0, QtWidgets.QHeaderView.Interactive)
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
        self._populate_dbs()

    def _check_header(self) -> str:
        return "Use" if self._filter_mode == MODE_BLACKLIST else "Block"

    def _on_check_all(self):
        self._filter_keys.clear()
        self._build_tree()

    def _on_sort_changed(self, index: int):
        self._sort_mode = index
        self._build_tree()

    def _populate_dbs(self):
        self._db_combo.blockSignals(True)
        self._db_combo.clear()
        for name in list_setting_db_names():
            self._db_combo.addItem(name)
        self._db_combo.blockSignals(False)
        if self._db_combo.count() > 0:
            self._load_keys(self._db_combo.currentText())

    def refresh(self):
        if self._db_combo.currentText():
            self._load_keys(self._db_combo.currentText())

    def _load_keys(self, db_name: str):
        if not db_name:
            return
        cancel = self._cancel.renew()

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_all_exif_keys(db_name)

        def _done(result):
            if cancel.is_cancelled():
                return
            self._key_data = result
            self._build_tree()

        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(_done, _bg())))

    def _sorted_entries(self, entries: list[tuple]) -> list[tuple]:
        if self._sort_mode == _SORT_COUNT:
            return sorted(entries, key=lambda e: e[1], reverse=True)
        return sorted(entries, key=lambda e: e[0].lower())

    def _build_tree(self):
        self._tree.clear()
        self._tree.setHeaderLabels([self._check_header(), "Key", "Count"])
        groups: dict[str, list[tuple[str, int, str]]] = {}
        for key, freq in self._key_data:
            parts = key.split("/", 1)
            group = parts[0] + "/" if len(parts) > 1 else ""
            leaf = parts[1] if len(parts) > 1 else parts[0]
            groups.setdefault(group, []).append((leaf, freq, key))

        ungrouped = groups.pop("", [])
        for leaf, freq, full_key in self._sorted_entries(ungrouped):
            item = self._make_leaf_item(leaf, freq, full_key)
            self._tree.addTopLevelItem(item)

        group_order = sorted(groups.keys())
        if self._sort_mode == _SORT_COUNT:
            group_order = sorted(groups.keys(), key=lambda g: sum(f for _, f, _ in groups[g]), reverse=True)

        for group_name in group_order:
            entries = groups[group_name]
            group_item = QtWidgets.QTreeWidgetItem(["", group_name, ""])
            group_item.setFlags(group_item.flags() | QtCore.Qt.ItemIsUserCheckable | QtCore.Qt.ItemIsAutoTristate)
            total_freq = sum(f for _, f, _ in entries)
            group_item.setText(_COUNT_COL, f"{total_freq:,}")
            all_out = all(fk not in self._filter_keys for _, _, fk in entries)
            all_in = all(fk in self._filter_keys for _, _, fk in entries)
            if all_out:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.Checked)
            elif all_in:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.Unchecked)
            else:
                group_item.setCheckState(_CHECK_COL, QtCore.Qt.PartiallyChecked)
            for leaf, freq, full_key in self._sorted_entries(entries):
                child = self._make_leaf_item(leaf, freq, full_key)
                group_item.addChild(child)
            self._tree.addTopLevelItem(group_item)

        self._tree.expandAll()
        self._apply_filter(self._search.text())

    def _make_leaf_item(self, label: str, freq: int, full_key: str) -> QtWidgets.QTreeWidgetItem:
        item = QtWidgets.QTreeWidgetItem(["", label, f"{freq:,}"])
        item.setData(_KEY_COL, QtCore.Qt.UserRole, full_key)
        item.setFlags(item.flags() | QtCore.Qt.ItemIsUserCheckable)
        in_keys = full_key in self._filter_keys
        item.setCheckState(_CHECK_COL, QtCore.Qt.Unchecked if in_keys else QtCore.Qt.Checked)
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

    def _on_item_clicked(self, item: QtWidgets.QTreeWidgetItem, column: int):
        full_key = item.data(_KEY_COL, QtCore.Qt.UserRole)
        if not full_key:
            return
        db_name = self._db_combo.currentText()
        if not db_name:
            return
        cancel = self._cancel.renew()

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_sample_values(db_name, f"exif.{full_key}")

        def _done(samples: list[tuple[str, str]]):
            if cancel.is_cancelled():
                return
            freq = 0
            for k, f in self._key_data:
                if k == full_key:
                    freq = f
                    break
            self._sample_header.setText(
                f"<b>Key:</b> exif.{full_key} &nbsp; <b>Affected:</b> {freq:,} files"
            )
            self._sample_table.setRowCount(len(samples))
            for row, (file_path, value) in enumerate(samples):
                self._sample_table.setItem(row, 0, QtWidgets.QTableWidgetItem(os.path.basename(file_path)))
                val_str = str(value) if value is not None else ""
                self._sample_table.setItem(row, 1, QtWidgets.QTableWidgetItem(val_str[:300]))
            self._placeholder.setVisible(False)
            self._sample_header.setVisible(True)
            self._sample_table.setVisible(True)

        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(_done, _bg())))

    def collect_filter_keys(self) -> set[str]:
        result: set[str] = set()
        for i in range(self._tree.topLevelItemCount()):
            top = self._tree.topLevelItem(i)
            if top.childCount() == 0:
                if top.checkState(_CHECK_COL) == QtCore.Qt.Unchecked:
                    key = top.data(_KEY_COL, QtCore.Qt.UserRole)
                    if key:
                        result.add(key)
            else:
                for j in range(top.childCount()):
                    child = top.child(j)
                    if child.checkState(_CHECK_COL) == QtCore.Qt.Unchecked:
                        key = child.data(_KEY_COL, QtCore.Qt.UserRole)
                        if key:
                            result.add(key)
        return result

    def all_known_keys(self) -> set[str]:
        return {k for k, _ in self._key_data}

    def set_filter(self, mode: str, keys: set[str]):
        self._filter_mode = mode
        self._filter_keys = set(keys)
        self._build_tree()

    def set_filter_keys(self, keys: set[str]):
        self._filter_keys = set(keys)
        self._build_tree()


class _SamplePreviewTab(QtWidgets.QWidget):
    filter_keys_changed = QtCore.Signal(set)

    def __init__(self, filter_mode: str, filter_keys: set[str], parent=None):
        super().__init__(parent)
        self._filter_mode = filter_mode
        self._filter_keys = set(filter_keys)
        self._meta: dict[str, str] = {}
        self._current_path: str | None = None
        self.setAcceptDrops(True)

        self._drop_label = QtWidgets.QLabel("Drop an image file here to preview EXIF tags")
        self._drop_label.setAlignment(QtCore.Qt.AlignCenter)
        self._drop_label.setMinimumHeight(dpix(60))
        self._drop_label.setStyleSheet(
            f"border: {dpix(2)}px dashed palette(mid); border-radius: {dpix(6)}px; padding: {dpix(12)}px;"
        )

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
        return "Use" if self._filter_mode == MODE_BLACKLIST else "Block"

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
        try:
            from .exif_parser import ExifParser

            result = ExifParser.parse_file(path)
        except Exception as e:
            AppLogger.warning(f"[ExifSettings] Preview failed: {e}", exc=e)
            Notifier.warning(f"Preview failed: {e}")
            return

        self._current_path = path
        self._meta = {}
        if result.get("exif"):
            self._meta.update(result["exif"])
        if result.get("info_items"):
            self._meta.update(result["info_items"])

        pixmap = QtGui.QPixmap(path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                dpix(240), dpix(240),
                QtCore.Qt.KeepAspectRatio,
                QtCore.Qt.SmoothTransformation,
            )
            self._thumb.setPixmap(scaled)
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
            self._drop_label.setText(
                f"Previewing: {Path(self._current_path).name} "
                f"({len(self._meta)} keys, {self._blocked_count()} blocked)"
            )

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
            check_item.setCheckState(QtCore.Qt.Unchecked if in_keys else QtCore.Qt.Checked)
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
            self._filter_keys.discard(key)
        else:
            self._filter_keys.add(key)
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
        self.setWindowTitle("Save EXIF Filter Settings")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))
        layout.addWidget(QtWidgets.QLabel("Filter settings have been modified."))

        self._purge_cb = QtWidgets.QCheckBox("Purge existing EXIF data")
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


def _query_all_exif_keys(db_name: str) -> list[tuple[str, int]]:
    db_path = data_db_path(db_name)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
        apply_read_pragmas(conn)
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT SUBSTR(key, 6) AS short_key, COUNT(*) AS freq "
            "FROM meta_info WHERE key LIKE 'exif.%' "
            "GROUP BY short_key ORDER BY short_key"
        ).fetchall()
        return [(row["short_key"], row["freq"]) for row in rows]
    except Exception as e:
        AppLogger.warning(f"[ExifSettings] Failed to query keys for {db_name}: {e}", exc=e)
        return []
    finally:
        if conn:
            conn.close()


def _query_sample_values(db_name: str, key: str, limit: int = 10) -> list[tuple[str, str]]:
    db_path = data_db_path(db_name)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = None
    try:
        conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
        apply_read_pragmas(conn)
        rows = conn.execute(
            "SELECT path, value FROM meta_info WHERE key = ? LIMIT ?",
            (key, limit),
        ).fetchall()
        return [(row[0], row[1]) for row in rows]
    except Exception as e:
        AppLogger.warning(f"[ExifSettings] Sample query failed for {key}: {e}", exc=e)
        return []
    finally:
        if conn:
            conn.close()

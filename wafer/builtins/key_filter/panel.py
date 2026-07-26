from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from functools import partial

from PySide6 import QtWidgets, QtCore

from ...plugin import BasePanelPlugin, KeyFilter, MODE_BLACKLIST, MODE_WHITELIST
from ...plugin.collector.handler import collector_resolver
from ...plugin.parser.handler import parser_resolver
from ...plugin.key_filter_dialog import FilterSaveConfirmDialog
from ...core.db.recollect import Recollect
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...core.lang.manager import t
from ...utils.paths import list_setting_db_names, data_db_path
from ...core.db.db_utils import apply_read_pragmas
from ...core.qt.dispatcher import Dispatcher, CancelSlot
from ...core.qt.icon_engine import themed_icon
from ...app.viewer.widgets.loading_overlay import OverlayLoadingIndicator

_CHECK_COL = 0
_KEY_COL = 1
_COUNT_COL = 2

SORT_NAME = 0
SORT_COUNT = 1


class KeyFilterPanelPlugin(BasePanelPlugin):
    NAME = "key_filter"
    DISPLAY_NAME = "Metadata Filter"
    SOURCE = "Builtin"
    DEFAULT_ENABLED = True
    CLOSABLE = True
    PRIORITY = 40

    def create_widget(self) -> QtWidgets.QWidget:
        return KeyFilterWidget()


class KeyFilterWidget(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher()

        self._tabs = QtWidgets.QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        reload_btn = QtWidgets.QToolButton()
        reload_btn.setIcon(themed_icon("refresh", margin=0.06))
        reload_btn.setIconSize(QtCore.QSize(dpix(14), dpix(14)))
        reload_btn.setToolTip(t("Reload counts"))
        reload_btn.setCursor(QtCore.Qt.PointingHandCursor)
        reload_btn.setAutoRaise(True)
        reload_btn.clicked.connect(self._refresh_current)
        self._tabs.setCornerWidget(reload_btn, QtCore.Qt.TopRightCorner)

        save_btn = QtWidgets.QPushButton(t("Save"))
        save_btn.clicked.connect(self._on_save)
        revert_btn = QtWidgets.QPushButton(t("Revert"))
        revert_btn.clicked.connect(self._on_revert)

        bottom = QtWidgets.QHBoxLayout()
        bottom.addStretch()
        bottom.addWidget(save_btn)
        bottom.addWidget(revert_btn)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(dpix(8), dpix(8), dpix(8), dpix(8))
        layout.setSpacing(dpix(6))
        layout.addWidget(self._tabs, 1)
        layout.addLayout(bottom)

        self._prefix_tabs: dict[str, _FilterTab] = {}
        self._build_tabs()

        self._filter_callback = self._on_filter_changed
        self._dirty = False
        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._reload)
        self._connect_bridge()

    def _connect_bridge(self):
        from ...app.viewer.ipc_bridge import ViewerIpcBridge

        bridge = ViewerIpcBridge.instance()
        if bridge:
            bridge.db_content_updated.connect(self._on_db_updated)

    def _on_db_updated(self, _db: str):
        if self.isVisible():
            self._debounce_timer.start()
        else:
            self._dirty = True

    def showEvent(self, event):
        super().showEvent(event)
        KeyFilter.subscribe(self._filter_callback)
        for tab in self._prefix_tabs.values():
            tab.sync_from_store()
        if self._dirty:
            self._dirty = False
            self._reload()

    def hideEvent(self, event):
        super().hideEvent(event)
        KeyFilter.unsubscribe(self._filter_callback)
        self._debounce_timer.stop()

    def _on_filter_changed(self, prefix: str):
        tab = self._prefix_tabs.get(prefix)
        if tab is not None:
            tab.sync_from_store()

    def _build_tabs(self):
        loading = QtWidgets.QLabel(t("Loading..."))
        loading.setAlignment(QtCore.Qt.AlignCenter)
        loading.setStyleSheet(f"color: palette(mid); padding: {dpix(20)}px;")
        self._tabs.addTab(loading, t("Loading..."))
        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(self._populate_tabs, _list_prefixes())))

    def _all_prefixes(self, db_prefixes: list[str]) -> list[str]:
        return sorted(set(db_prefixes) | set(collector_resolver.names()) | set(parser_resolver.names()))

    def _populate_tabs(self, db_prefixes: list[str]):
        self._tabs.clear()
        self._prefix_tabs.clear()
        for prefix in self._all_prefixes(db_prefixes):
            tab = _FilterTab(prefix, self._dispatcher)
            self._prefix_tabs[prefix] = tab
            self._tabs.addTab(tab, prefix)
        if self._tabs.count():
            self._on_tab_changed(0)

    def _reload(self):
        self._dispatcher.post(lambda: self._dispatcher.invoke(partial(self._merge_prefixes, _list_prefixes())))

    def _merge_prefixes(self, db_prefixes: list[str]):
        if not self._prefix_tabs:
            self._populate_tabs(db_prefixes)
            return
        for prefix in self._all_prefixes(db_prefixes):
            if prefix not in self._prefix_tabs:
                tab = _FilterTab(prefix, self._dispatcher)
                self._prefix_tabs[prefix] = tab
                self._insert_tab_sorted(prefix, tab)
        current = self._tabs.currentWidget()
        for tab in self._prefix_tabs.values():
            if tab is not current:
                tab.mark_stale()
        self._refresh_current()

    def _insert_tab_sorted(self, prefix: str, tab: _FilterTab):
        index = self._tabs.count()
        for i in range(self._tabs.count()):
            if prefix < self._tabs.tabText(i):
                index = i
                break
        self._tabs.insertTab(index, tab, prefix)

    def _on_tab_changed(self, index: int):
        widget = self._tabs.widget(index)
        if isinstance(widget, _FilterTab):
            widget.ensure_loaded()

    @QtCore.Slot()
    def _refresh_current(self):
        widget = self._tabs.currentWidget()
        if isinstance(widget, _FilterTab) and widget.isVisible():
            widget.refresh()

    def _on_save(self):
        dirty = [tab for tab in self._prefix_tabs.values() if tab.is_dirty()]
        if not dirty:
            return
        dlg = FilterSaveConfirmDialog([tab.prefix for tab in dirty], parent=self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        do_delete = dlg.delete_data()
        do_recollect = dlg.recollect()
        db_names = list_setting_db_names()
        parser_names = set(parser_resolver.names())
        for tab in dirty:
            tab.apply()
            if (do_delete or do_recollect) and db_names:
                delete_keys = tab.compute_delete_keys() if do_delete else []
                re_collect = do_recollect and tab.prefix not in parser_names
                if delete_keys or re_collect:
                    Recollect.purge(db_scope=list(db_names), collector=tab.prefix, keys=delete_keys, delete=False, re_collect=re_collect)
        Notifier.info(t("Filter settings saved ({n} changed)").format(n=len(dirty)))

    def _on_revert(self):
        for tab in self._prefix_tabs.values():
            tab.revert()


class _FilterTab(QtWidgets.QWidget):
    def __init__(self, prefix: str, dispatcher: Dispatcher, parent=None):
        super().__init__(parent)
        self.prefix = prefix
        self._dispatcher = dispatcher
        self._cancel = CancelSlot()
        self._filter_mode, keys = KeyFilter.get(prefix)
        self._filter_keys = set(keys)
        self._saved_mode = self._filter_mode
        self._saved_keys = set(keys)
        self._sort_mode, self._sort_ascending = KeyFilter.read_sort()
        self._key_data: list[tuple[str, int]] = []
        self._loaded = False
        self._stale = False

        self._mode_combo = QtWidgets.QComboBox()
        self._mode_combo.addItem(t("Blacklist (block selected)"), MODE_BLACKLIST)
        self._mode_combo.addItem(t("Whitelist (use selected only)"), MODE_WHITELIST)
        self._mode_combo.setCurrentIndex(0 if self._filter_mode == MODE_BLACKLIST else 1)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self._check_all_btn = QtWidgets.QPushButton(t("Check All"))
        self._check_all_btn.clicked.connect(self._on_check_all)

        top_row = QtWidgets.QHBoxLayout()
        top_row.addWidget(QtWidgets.QLabel(t("Filter Mode:")))
        top_row.addWidget(self._mode_combo)
        top_row.addStretch()
        top_row.addWidget(self._check_all_btn)

        self._search = QtWidgets.QLineEdit()
        self._search.setPlaceholderText(t("Filter keys..."))
        self._search.textChanged.connect(self._apply_search)

        self._tree = QtWidgets.QTreeWidget()
        self._tree.setHeaderLabels([self._check_header(), t("Key"), t("Count")])
        self._tree.setRootIsDecorated(True)
        self._tree.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.currentItemChanged.connect(self._on_current_changed)
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

        self._placeholder = QtWidgets.QLabel(t("Click a key to see sample values"))
        self._placeholder.setAlignment(QtCore.Qt.AlignCenter)
        self._placeholder.setStyleSheet(f"color: palette(mid); padding: {dpix(20)}px;")

        sample_widget = QtWidgets.QWidget()
        sample_layout = QtWidgets.QVBoxLayout(sample_widget)
        sample_layout.setContentsMargins(0, 0, 0, 0)
        sample_layout.setSpacing(dpix(2))
        sample_layout.addWidget(self._sample_header)
        sample_layout.addWidget(self._sample_table, 1)
        sample_layout.addWidget(self._placeholder, 1)

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

        self._loading = OverlayLoadingIndicator(self._tree.viewport())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))
        layout.addLayout(top_row)
        layout.addWidget(self._splitter, 1)

    def eventFilter(self, obj, event):
        if hasattr(self, "_tree") and obj is self._tree.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
            self._pre_click_selection = list(self._tree.selectedItems())
        return super().eventFilter(obj, event)

    def is_dirty(self) -> bool:
        return self._filter_mode != self._saved_mode or self._filter_keys != self._saved_keys

    def apply(self):
        KeyFilter.set_keys(self.prefix, self._filter_mode, self._filter_keys)
        self._saved_mode = self._filter_mode
        self._saved_keys = set(self._filter_keys)

    def sync_from_store(self):
        was_dirty = self.is_dirty()
        mode, keys = KeyFilter.get(self.prefix)
        new_keys = set(keys)
        if mode == self._saved_mode and new_keys == self._saved_keys:
            return
        self._saved_mode = mode
        self._saved_keys = set(new_keys)
        if was_dirty:
            return
        self._filter_mode = mode
        self._filter_keys = set(new_keys)
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0 if mode == MODE_BLACKLIST else 1)
        self._mode_combo.blockSignals(False)
        self._update_check_all_label()
        if self._loaded:
            self._build_tree()

    def revert(self):
        self._filter_mode = self._saved_mode
        self._filter_keys = set(self._saved_keys)
        self._mode_combo.blockSignals(True)
        self._mode_combo.setCurrentIndex(0 if self._filter_mode == MODE_BLACKLIST else 1)
        self._mode_combo.blockSignals(False)
        self._update_check_all_label()
        self._build_tree()

    def compute_delete_keys(self) -> list[str]:
        return KeyFilter.blocked_keys(
            self.prefix,
            [k for k, _ in self._key_data],
            mode=self._filter_mode,
            keys=self._filter_keys,
        )

    def ensure_loaded(self):
        if not self._loaded:
            self._loaded = True
            self._load_keys()
        elif self._stale:
            self._stale = False
            self._load_keys()

    def mark_stale(self):
        if self._loaded:
            self._stale = True

    def refresh(self):
        if self._loaded:
            self._stale = False
            self._load_keys()

    def _check_header(self) -> str:
        return t("Block") if self._filter_mode == MODE_BLACKLIST else t("Use")

    def _on_mode_changed(self, index: int):
        new_mode = self._mode_combo.itemData(index)
        if new_mode == self._filter_mode:
            return
        all_keys = self._all_known_keys()
        if all_keys:
            self._filter_keys = all_keys - self._filter_keys
        self._filter_mode = new_mode
        self._update_check_all_label()
        self._build_tree()

    def _all_known_keys(self) -> set[str]:
        return {k for k, _ in self._key_data} | self._filter_keys

    def _check_all_target_keys(self) -> set[str]:
        text = self._search.text().strip().lower()
        all_keys = self._all_known_keys()
        if not text:
            return all_keys
        return {key for key in all_keys if text in key.lower()}

    def _on_check_all(self):
        target_keys = self._check_all_target_keys()
        if not target_keys:
            return
        if target_keys <= self._filter_keys:
            self._filter_keys.difference_update(target_keys)
        else:
            self._filter_keys.update(target_keys)
        self._update_check_all_label()
        self._build_tree()

    def _update_check_all_label(self):
        target_keys = self._check_all_target_keys()
        all_checked = target_keys and target_keys <= self._filter_keys
        self._check_all_btn.setText(t("Uncheck All") if all_checked else t("Check All"))

    def _on_header_sort(self, section: int):
        if section == _CHECK_COL:
            return
        new_mode = SORT_NAME if section == _KEY_COL else SORT_COUNT
        if new_mode == self._sort_mode:
            self._sort_ascending = not self._sort_ascending
        else:
            self._sort_mode = new_mode
            self._sort_ascending = new_mode == SORT_NAME
        KeyFilter.write_sort(self._sort_mode, self._sort_ascending)
        self._build_tree()

    def _position_loading(self):
        m = dpix(6)
        self._loading.move(m, m)

    def _load_keys(self):
        cancel = self._cancel.renew()
        self._position_loading()
        self._loading.start()
        prefix = self.prefix

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_prefix_keys(prefix)

        def _done(result):
            if cancel.is_cancelled():
                return
            self._loading.stop()
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
        key_label = t("Key")
        count_label = t("Count")
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
        self._apply_search(self._search.text())
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

    def _apply_search(self, text: str):
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
            self._filter_keys = self._collect_filter_keys()
            self._update_check_all_label()
        self._show_key_preview(item)

    def _on_current_changed(self, current: QtWidgets.QTreeWidgetItem, _previous: QtWidgets.QTreeWidgetItem):
        if current is not None:
            self._show_key_preview(current)

    def _show_key_preview(self, item: QtWidgets.QTreeWidgetItem):
        full_key = item.data(_KEY_COL, QtCore.Qt.UserRole)
        if not full_key:
            return
        cancel = self._cancel.renew()
        prefix = self.prefix

        def _bg():
            if cancel.is_cancelled():
                return []
            return _query_sample_values(f"{prefix}.{full_key}")

        def _done(samples: list[tuple[str, str, str]]):
            if cancel.is_cancelled():
                return
            freq = 0
            for k, f in self._key_data:
                if k == full_key:
                    freq = f
                    break
            self._sample_header.setText(f"<b>Key:</b> {prefix}.{full_key} &nbsp; <b>Affected:</b> {freq:,} files")
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

    def _collect_filter_keys(self) -> set[str]:
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


def _open_ro(db_name: str):
    db_path = data_db_path(db_name)
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
    apply_read_pragmas(conn)
    return conn


def _list_prefixes() -> list[str]:
    prefixes: set[str] = set()
    sql = "SELECT DISTINCT SUBSTR(key, 1, INSTR(key, '.') - 1) FROM meta_info WHERE key LIKE '%.%' UNION SELECT DISTINCT SUBSTR(key, 1, INSTR(key, '.') - 1) FROM tags WHERE key LIKE '%.%'"
    for db_name in list_setting_db_names():
        conn = None
        try:
            conn = _open_ro(db_name)
            for row in conn.execute(sql).fetchall():
                if row[0]:
                    prefixes.add(row[0])
        except Exception as e:
            AppLogger.warning(f"[MetadataFilter] Failed to list prefixes for {db_name}: {e}", exc=e)
        finally:
            if conn:
                conn.close()
    return sorted(prefixes)


def _query_prefix_keys(prefix: str) -> list[tuple[str, int]]:
    like = f"{prefix}.%"
    cut = len(prefix) + 2
    sql = (
        f"SELECT SUBSTR(key, {cut}) AS short_key, COUNT(*) AS freq FROM meta_info WHERE key LIKE ? GROUP BY short_key"
        f" UNION ALL SELECT SUBSTR(key, {cut}) AS short_key, COUNT(*) AS freq FROM tags WHERE key LIKE ? GROUP BY short_key"
    )
    merged: dict[str, int] = {}
    for db_name in list_setting_db_names():
        conn = None
        try:
            conn = _open_ro(db_name)
            for row in conn.execute(sql, (like, like)).fetchall():
                merged[row[0]] = merged.get(row[0], 0) + row[1]
        except Exception as e:
            AppLogger.warning(f"[MetadataFilter] Failed to query keys for {db_name}: {e}", exc=e)
        finally:
            if conn:
                conn.close()
    return sorted(merged.items(), key=lambda x: x[0])


_SAMPLE_POOL = 1000
_NONEMPTY_SAMPLE_SQL = (
    "SELECT * FROM (SELECT path, value FROM meta_info WHERE key = ? AND value IS NOT NULL AND value != '' LIMIT ?)"
    " UNION ALL SELECT * FROM (SELECT file_hash, value FROM tags WHERE key = ? AND value IS NOT NULL AND value != '' LIMIT ?)"
)
_EMPTY_SAMPLE_SQL = (
    "SELECT * FROM (SELECT path, value FROM meta_info WHERE key = ? AND (value IS NULL OR value = '') LIMIT ?)"
    " UNION ALL SELECT * FROM (SELECT file_hash, value FROM tags WHERE key = ? AND (value IS NULL OR value = '') LIMIT ?)"
)


def _collect_samples(sql: str, key: str, budget: int) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    remaining = budget
    for db_name in list_setting_db_names():
        if remaining <= 0:
            break
        conn = None
        try:
            conn = _open_ro(db_name)
            rows = conn.execute(sql, (key, remaining, key, remaining)).fetchall()[:remaining]
            out.extend((db_name, row[0], row[1]) for row in rows)
            remaining -= len(rows)
        except Exception as e:
            AppLogger.warning(f"[MetadataFilter] Sample query failed for {key} in {db_name}: {e}", exc=e)
        finally:
            if conn:
                conn.close()
    return out


def _query_sample_values(key: str, limit: int = 20, pool: int = _SAMPLE_POOL) -> list[tuple[str, str, str]]:
    candidates = _collect_samples(_NONEMPTY_SAMPLE_SQL, key, pool)
    candidates.sort(key=lambda row: len(str(row[2])), reverse=True)
    results = candidates[:limit]
    if len(results) < limit:
        results.extend(_collect_samples(_EMPTY_SAMPLE_SQL, key, limit - len(results)))
    return results

import sqlite3
from pathlib import Path

from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...core.qt.icon_engine import themed_icon
from ...utils.paths import list_setting_db_names, data_db_path, setting_db_path
from ...core.db.setting_db import SettingDB
from ...core.db.db_utils import apply_read_pragmas
from ...core.qt.dispatcher import Dispatcher, CancelSlot


_COL_DB = 0
_COL_PREFIX = 1
_COL_META = 2
_COL_TAGS = 3
_COL_STATUS = 4
_COL_CHECK = 5
_COLUMN_COUNT = 6
_HEADERS = ["Database", "Prefix", "MetaInfo", "Tags", "Status", ""]


class _NumericItem(QtWidgets.QTableWidgetItem):
    def __lt__(self, other):
        try:
            return int(self.text().replace(",", "")) < int(other.text().replace(",", ""))
        except (ValueError, AttributeError):
            return super().__lt__(other)


def _resolve_plugin_info(prefix: str) -> tuple[str, str]:
    from ...plugin.collector.handler import collector_resolver
    from ...plugin.detacher.handler import detacher_resolver

    if collector_resolver.registry.get(prefix):
        return "Collector", prefix
    if detacher_resolver.registry.get(prefix):
        return "Detacher", prefix
    return "", ""


def _query_prefix_summary(db_path: str) -> list[tuple[str, int, int]]:
    uri = Path(db_path).resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, timeout=1.0, uri=True, check_same_thread=False)
    try:
        apply_read_pragmas(conn)
        cur = conn.execute("""
            SELECT prefix, SUM(meta_count), SUM(tag_count) FROM (
                SELECT
                    CASE WHEN INSTR(key, '.') > 0
                         THEN SUBSTR(key, 1, INSTR(key, '.') - 1)
                         ELSE '' END AS prefix,
                    COUNT(*) AS meta_count,
                    0 AS tag_count
                FROM meta_info GROUP BY prefix
                UNION ALL
                SELECT
                    CASE WHEN INSTR(key, '.') > 0
                         THEN SUBSTR(key, 1, INSTR(key, '.') - 1)
                         ELSE '' END AS prefix,
                    0 AS meta_count,
                    COUNT(*) AS tag_count
                FROM tags GROUP BY prefix
            ) GROUP BY prefix ORDER BY prefix
        """)
        return cur.fetchall()
    finally:
        conn.close()


def _build_rows(db_names: list[str], cancel) -> list[tuple[str, str, int, int, str, str, bool]]:
    rows: list[tuple[str, str, int, int, str, str, bool]] = []
    for name in db_names:
        if cancel.is_cancelled():
            return []
        sdb = SettingDB(setting_db_path(name))
        enabled = set(sdb.get_enabled_collectors() or [])
        try:
            prefix_data = _query_prefix_summary(data_db_path(name))
        except Exception as e:
            AppLogger.warning(f"[DataTab] prefix query failed for {name}: {e}")
            prefix_data = []
        seen_prefixes: set[str] = set()
        for prefix, meta_count, tag_count in prefix_data:
            seen_prefixes.add(prefix)
            plugin_type, _ = _resolve_plugin_info(prefix)
            if prefix and prefix in enabled:
                status = "Active"
            elif prefix and plugin_type:
                status = "Disabled"
            else:
                status = ""
            purgeable = bool(prefix)
            rows.append((name, prefix, meta_count, tag_count, plugin_type, status, purgeable))
        for en in sorted(enabled - seen_prefixes):
            plugin_type, _ = _resolve_plugin_info(en)
            if not plugin_type:
                continue
            rows.append((name, en, 0, 0, plugin_type, "Active", True))
    return rows


_DisplayRow = tuple[str, str, int, int, str, bool]


def _split_rows(rows: list[tuple[str, str, int, int, str, str, bool]]) -> tuple[list[_DisplayRow], list[_DisplayRow]]:
    collectors: list[_DisplayRow] = []
    detachers: list[_DisplayRow] = []
    for db, prefix, meta, tags, plugin_type, status, purgeable in rows:
        display: _DisplayRow = (db, prefix, meta, tags, status, purgeable)
        if plugin_type == "Detacher":
            detachers.append(display)
        else:
            collectors.append(display)
    return collectors, detachers


class _PrefixTable(QtWidgets.QGroupBox):
    selection_changed = QtCore.Signal()

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        layout = QtWidgets.QVBoxLayout(self)
        self.table = QtWidgets.QTableWidget()
        self.table.setColumnCount(_COLUMN_COUNT)
        self.table.setHorizontalHeaderLabels(_HEADERS)
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_DB, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PREFIX, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_META, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_TAGS, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_STATUS, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_CHECK, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setColumnWidth(_COL_CHECK, dpix(30))
        self.table.setSortingEnabled(True)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        self.rows: list[_DisplayRow] = []

    def apply_rows(self, rows: list[_DisplayRow]):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, (db, prefix, meta, tags, status, purgeable) in enumerate(rows):
            self.table.setItem(i, _COL_DB, QtWidgets.QTableWidgetItem(db))
            self.table.setItem(i, _COL_PREFIX, QtWidgets.QTableWidgetItem(prefix))

            meta_item = _NumericItem(f"{meta:,}")
            meta_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, _COL_META, meta_item)

            tags_item = _NumericItem(f"{tags:,}")
            tags_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, _COL_TAGS, tags_item)

            self.table.setItem(i, _COL_STATUS, QtWidgets.QTableWidgetItem(status))

            if purgeable:
                cb = QtWidgets.QCheckBox()
                cb.stateChanged.connect(lambda _: self.selection_changed.emit())
                container = QtWidgets.QWidget()
                cb_layout = QtWidgets.QHBoxLayout(container)
                cb_layout.addWidget(cb)
                cb_layout.setAlignment(QtCore.Qt.AlignCenter)
                cb_layout.setContentsMargins(0, 0, 0, 0)
                self.table.setCellWidget(i, _COL_CHECK, container)
            else:
                self.table.removeCellWidget(i, _COL_CHECK)
        self.table.setSortingEnabled(True)

    def merge_rows(self, rows: list[_DisplayRow]):
        old_set = {(r[0], r[1]) for r in self.rows}
        new_set = {(r[0], r[1]) for r in rows}
        if old_set != new_set:
            self.apply_rows(rows)
            return
        old_data = {(r[0], r[1]): r[2:] for r in self.rows}
        new_data = {(r[0], r[1]): r[2:] for r in rows}
        for i in range(self.table.rowCount()):
            db = self.table.item(i, _COL_DB).text()
            prefix = self.table.item(i, _COL_PREFIX).text()
            key = (db, prefix)
            old = old_data.get(key)
            new = new_data.get(key)
            if old is None or new is None:
                continue
            if old[0] != new[0]:
                self.table.item(i, _COL_META).setText(f"{new[0]:,}")
            if old[1] != new[1]:
                self.table.item(i, _COL_TAGS).setText(f"{new[1]:,}")
            if old[2] != new[2]:
                self.table.item(i, _COL_STATUS).setText(new[2])
        self.rows = rows

    def checked_count(self) -> int:
        count = 0
        for i in range(self.table.rowCount()):
            container = self.table.cellWidget(i, _COL_CHECK)
            if container:
                cb = container.findChild(QtWidgets.QCheckBox)
                if cb and cb.isChecked():
                    count += 1
        return count

    def get_checked(self) -> list[tuple[str, str]]:
        selected = []
        for i in range(self.table.rowCount()):
            container = self.table.cellWidget(i, _COL_CHECK)
            if not container:
                continue
            cb = container.findChild(QtWidgets.QCheckBox)
            if cb and cb.isChecked():
                db = self.table.item(i, _COL_DB).text()
                prefix = self.table.item(i, _COL_PREFIX).text()
                if prefix:
                    selected.append((db, prefix))
        return selected


class DataTab(QtWidgets.QWidget):
    purge_requested = QtCore.Signal(list, bool)

    def __init__(self, dispatcher: Dispatcher, parent=None):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._load_cancel = CancelSlot()
        self._poll_cancel = CancelSlot()
        self._raw_rows: list[tuple[str, str, int, int, str, str, bool]] = []
        self._initial_loaded = False
        self.destroyed.connect(lambda: (self._load_cancel.renew(), self._poll_cancel.renew()))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(6))

        header_row = QtWidgets.QHBoxLayout()
        label = QtWidgets.QLabel("Collected Data")
        label.setObjectName("section_header")
        header_row.addWidget(label)
        header_row.addStretch()
        self._refresh_btn = QtWidgets.QPushButton()
        self._refresh_btn.setIcon(themed_icon("refresh"))
        self._refresh_btn.setFixedSize(dpix(24), dpix(24))
        self._refresh_btn.setToolTip("Refresh")
        self._refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(self._refresh_btn)
        layout.addLayout(header_row)

        self._collector_table = _PrefixTable("Collectors")
        self._collector_table.selection_changed.connect(self._update_selected_count)

        self._detacher_table = _PrefixTable("Detachers")
        self._detacher_table.selection_changed.connect(self._update_selected_count)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.splitter.addWidget(self._collector_table)
        self.splitter.addWidget(self._detacher_table)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        self._selected_label = QtWidgets.QLabel("Selected: 0 items")
        layout.addWidget(self._selected_label)

        self._re_collect_cb = QtWidgets.QCheckBox("Re-collect after purge (mark as pending)")
        self._re_collect_cb.setChecked(True)
        layout.addWidget(self._re_collect_cb)

        self._purge_btn = QtWidgets.QPushButton("Purge Selected")
        self._purge_btn.setObjectName("purge_btn")
        self._purge_btn.setFixedWidth(dpix(140))
        self._purge_btn.clicked.connect(self._on_purge)
        layout.addWidget(self._purge_btn)

        self._dirty = False
        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._on_debounced_update)
        self._connect_bridge()

        self._load_async(priority=5)

    def _connect_bridge(self):
        from ...app.viewer.ipc_bridge import ViewerIpcBridge

        bridge = ViewerIpcBridge.instance()
        if bridge:
            bridge.db_content_updated.connect(self._on_db_updated)

    def _on_db_updated(self, db: str):
        if self.isVisible():
            self._debounce_timer.start()
        else:
            self._dirty = True

    def _on_debounced_update(self):
        self._poll()

    def showEvent(self, event):
        super().showEvent(event)
        if self._dirty and self._initial_loaded:
            self._dirty = False
            self._poll()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._debounce_timer.stop()

    def _set_loading(self, loading: bool):
        self._refresh_btn.setEnabled(not loading)
        self._refresh_btn.setToolTip("Loading..." if loading else "Refresh")

    def _load_async(self, priority: int = 9, log: bool = False):
        self._set_loading(True)
        cancel = self._load_cancel.renew()
        db_names = list_setting_db_names()
        if log:
            AppLogger.info(f"[DataTab] Refresh started (databases={db_names})")

        def task():
            rows = _build_rows(db_names, cancel)
            if rows is not None and not cancel.is_cancelled():
                self._dispatcher.invoke(lambda: self._on_loaded(rows, log=log))
            else:
                self._dispatcher.invoke(lambda: self._set_loading(False))

        self._dispatcher.post(task, priority=priority, cancel=cancel)

    def _on_loaded(self, rows, *, log: bool = False):
        self._set_loading(False)
        self._apply_rows(rows)
        if not self._initial_loaded:
            self._initial_loaded = True
        if log:
            AppLogger.info(f"[DataTab] Refresh complete ({len(rows)} rows)")

    def _apply_rows(self, rows: list[tuple[str, str, int, int, str, str, bool]]):
        self._raw_rows = rows
        c_rows, d_rows = _split_rows(rows)
        self._collector_table.apply_rows(c_rows)
        self._detacher_table.apply_rows(d_rows)

    def _update_selected_count(self):
        count = self._collector_table.checked_count() + self._detacher_table.checked_count()
        self._selected_label.setText(f"Selected: {count} items")

    def _on_purge(self):
        selected = self._collector_table.get_checked() + self._detacher_table.get_checked()
        if not selected:
            return
        re_collect = self._re_collect_cb.isChecked()
        msg = f"Purge {len(selected)} prefix(es)?\n\n"
        for db, prefix in selected:
            msg += f"  {prefix} on {db}\n"
        if re_collect:
            msg += "\nFiles will be marked for re-collection."
        result = QtWidgets.QMessageBox.question(
            self,
            "Confirm Purge",
            msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        self.purge_requested.emit(selected, re_collect)

    def refresh(self):
        self._poll_cancel.cancel()
        self._debounce_timer.stop()
        self._load_async(log=True)

    def _poll(self):
        cancel = self._poll_cancel.renew()
        db_names = list_setting_db_names()

        def task():
            rows = _build_rows(db_names, cancel)
            if rows is not None and not cancel.is_cancelled():
                self._dispatcher.invoke(lambda r=rows: self._merge_rows(r))

        self._dispatcher.post(task, priority=7, cancel=cancel)

    def _merge_rows(self, rows: list[tuple[str, str, int, int, str, str, bool]]):
        self._raw_rows = rows
        c_rows, d_rows = _split_rows(rows)
        self._collector_table.merge_rows(c_rows)
        self._detacher_table.merge_rows(d_rows)

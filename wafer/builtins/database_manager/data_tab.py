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
from ...core.lang.manager import t


_COL_DB = 0
_COL_PREFIX = 1
_COL_META = 2
_COL_TAGS = 3
_COL_STATUS = 4
_COL_DELETE = 5
_COL_RECOLLECT = 6
_COLUMN_COUNT = 7
_HEADERS = [t("Database"), t("Prefix"), t("MetaInfo"), t("Tags"), t("Status"), t("Delete"), t("Recollect")]


class _NumericItem(QtWidgets.QTableWidgetItem):
    def __lt__(self, other):
        try:
            return int(self.text().replace(",", "")) < int(other.text().replace(",", ""))
        except (ValueError, AttributeError):
            return super().__lt__(other)


def _resolve_plugin_info(prefix: str) -> tuple[str, str]:
    from ...plugin.collector.handler import collector_resolver
    from ...plugin.parser.handler import parser_resolver

    if collector_resolver.registry.get(prefix):
        return "Collector", prefix
    if parser_resolver.registry.get(prefix):
        return "Parser", prefix
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
            deletable = bool(prefix)
            rows.append((name, prefix, meta_count, tag_count, plugin_type, status, deletable))
        for en in sorted(enabled - seen_prefixes):
            plugin_type, _ = _resolve_plugin_info(en)
            if not plugin_type:
                continue
            rows.append((name, en, 0, 0, plugin_type, "Active", True))
    return rows


_DisplayRow = tuple[str, str, int, int, str, bool]


def _split_rows(rows: list[tuple[str, str, int, int, str, str, bool]]) -> tuple[list[_DisplayRow], list[_DisplayRow]]:
    collectors: list[_DisplayRow] = []
    parsers: list[_DisplayRow] = []
    for db, prefix, meta, tags, plugin_type, status, deletable in rows:
        display: _DisplayRow = (db, prefix, meta, tags, status, deletable)
        if plugin_type == "Parser":
            parsers.append(display)
        else:
            collectors.append(display)
    return collectors, parsers


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
        header.setSectionResizeMode(_COL_DELETE, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_RECOLLECT, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setSortingEnabled(True)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.verticalHeader().setVisible(False)
        layout.addWidget(self.table)
        self.rows: list[_DisplayRow] = []

    def _add_check(self, row: int, col: int, enabled: bool = True):
        cb = QtWidgets.QCheckBox()
        cb.setEnabled(enabled)
        cb.stateChanged.connect(lambda _: self.selection_changed.emit())
        container = QtWidgets.QWidget()
        cb_layout = QtWidgets.QHBoxLayout(container)
        cb_layout.addWidget(cb)
        cb_layout.setAlignment(QtCore.Qt.AlignCenter)
        cb_layout.setContentsMargins(0, 0, 0, 0)
        self.table.setCellWidget(row, col, container)

    def _checkbox_at(self, row: int, col: int) -> QtWidgets.QCheckBox | None:
        container = self.table.cellWidget(row, col)
        return container.findChild(QtWidgets.QCheckBox) if container else None

    def _sync_recollect_enabled(self, row: int, enabled: bool):
        cb = self._checkbox_at(row, _COL_RECOLLECT)
        if cb is None:
            return
        cb.setEnabled(enabled)
        if not enabled and cb.isChecked():
            cb.setChecked(False)

    def apply_rows(self, rows: list[_DisplayRow]):
        self.rows = rows
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(rows))
        for i, (db, prefix, meta, tags, status, deletable) in enumerate(rows):
            self.table.setItem(i, _COL_DB, QtWidgets.QTableWidgetItem(db))
            self.table.setItem(i, _COL_PREFIX, QtWidgets.QTableWidgetItem(prefix))

            meta_item = _NumericItem(f"{meta:,}")
            meta_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, _COL_META, meta_item)

            tags_item = _NumericItem(f"{tags:,}")
            tags_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self.table.setItem(i, _COL_TAGS, tags_item)

            self.table.setItem(i, _COL_STATUS, QtWidgets.QTableWidgetItem(status))

            if deletable:
                self._add_check(i, _COL_DELETE)
                self._add_check(i, _COL_RECOLLECT, enabled=status == "Active")
            else:
                self.table.removeCellWidget(i, _COL_DELETE)
                self.table.removeCellWidget(i, _COL_RECOLLECT)
        self.table.setSortingEnabled(True)
        self.selection_changed.emit()

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
                self._sync_recollect_enabled(i, new[2] == "Active")
        self.rows = rows

    def count_checked(self) -> tuple[int, int]:
        delete_n = recollect_n = 0
        for i in range(self.table.rowCount()):
            del_cb = self._checkbox_at(i, _COL_DELETE)
            rec_cb = self._checkbox_at(i, _COL_RECOLLECT)
            if del_cb and del_cb.isChecked():
                delete_n += 1
            if rec_cb and rec_cb.isChecked():
                recollect_n += 1
        return delete_n, recollect_n

    def get_actions(self) -> list[tuple[str, str, bool, bool]]:
        actions = []
        for i in range(self.table.rowCount()):
            del_cb = self._checkbox_at(i, _COL_DELETE)
            rec_cb = self._checkbox_at(i, _COL_RECOLLECT)
            delete = bool(del_cb and del_cb.isChecked())
            recollect = bool(rec_cb and rec_cb.isChecked())
            if not (delete or recollect):
                continue
            db = self.table.item(i, _COL_DB).text()
            prefix = self.table.item(i, _COL_PREFIX).text()
            if prefix:
                actions.append((db, prefix, delete, recollect))
        return actions

    def clear_checks(self):
        for i in range(self.table.rowCount()):
            for cb in (self._checkbox_at(i, _COL_DELETE), self._checkbox_at(i, _COL_RECOLLECT)):
                if cb and cb.isChecked():
                    cb.blockSignals(True)
                    cb.setChecked(False)
                    cb.blockSignals(False)
        self.selection_changed.emit()


class DataTab(QtWidgets.QWidget):
    apply_requested = QtCore.Signal(list)

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
        label = QtWidgets.QLabel(t("Collected Data"))
        label.setObjectName("section_header")
        header_row.addWidget(label)
        header_row.addStretch()
        self._refresh_btn = QtWidgets.QPushButton()
        self._refresh_btn.setIcon(themed_icon("refresh"))
        self._refresh_btn.setFixedSize(dpix(24), dpix(24))
        self._refresh_btn.setToolTip(t("Refresh"))
        self._refresh_btn.clicked.connect(self.refresh)
        header_row.addWidget(self._refresh_btn)
        layout.addLayout(header_row)

        self._collector_table = _PrefixTable(t("Collectors"))
        self._collector_table.selection_changed.connect(self._update_summary)

        self._parser_table = _PrefixTable(t("Parsers"))
        self._parser_table.selection_changed.connect(self._update_summary)

        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Vertical)
        self.splitter.addWidget(self._collector_table)
        self.splitter.addWidget(self._parser_table)
        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setChildrenCollapsible(False)
        layout.addWidget(self.splitter, 1)

        self._summary_label = QtWidgets.QLabel()
        layout.addWidget(self._summary_label)

        self._save_btn = QtWidgets.QPushButton(t("Apply"))
        self._save_btn.setObjectName("save_btn")
        self._revert_btn = QtWidgets.QPushButton(t("Revert"))
        self._revert_btn.setObjectName("cancel_btn")
        self._save_btn.clicked.connect(self._on_save)
        self._revert_btn.clicked.connect(self._on_revert)

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        btn_layout.addWidget(self._save_btn)
        btn_layout.addWidget(self._revert_btn)
        layout.addLayout(btn_layout)

        self._dirty = False
        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(500)
        self._debounce_timer.timeout.connect(self._on_debounced_update)
        self._connect_bridge()
        self._update_summary()

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
        self._refresh_btn.setToolTip(t("Loading...") if loading else t("Refresh"))

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
        self._parser_table.apply_rows(d_rows)

    def _update_summary(self):
        c_del, c_rec = self._collector_table.count_checked()
        p_del, p_rec = self._parser_table.count_checked()
        delete_n = c_del + p_del
        recollect_n = c_rec + p_rec
        self._summary_label.setText(t("Delete: {delete}  Recollect: {recollect}", delete=delete_n, recollect=recollect_n))
        self._save_btn.setEnabled(delete_n > 0 or recollect_n > 0)

    def _on_save(self):
        actions = self._collector_table.get_actions() + self._parser_table.get_actions()
        if not actions:
            return
        dlg = _ApplyConfirmDialog(actions, parent=self)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        self.apply_requested.emit(actions)

    def _on_revert(self):
        self.clear_checks()

    def clear_checks(self):
        self._collector_table.clear_checks()
        self._parser_table.clear_checks()

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
        self._parser_table.merge_rows(d_rows)


class _ApplyConfirmDialog(QtWidgets.QDialog):
    def __init__(self, actions: list[tuple[str, str, bool, bool]], parent=None):
        super().__init__(parent)
        self.setWindowTitle(t("Apply Data Changes"))

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(8))

        msg = t("Apply changes to {count} prefix(es)?\n\n", count=len(actions))
        for db, prefix, delete, recollect in actions:
            if delete and recollect:
                action = t("Delete+Recollect")
            elif delete:
                action = t("Delete")
            else:
                action = t("Recollect")
            msg += f"  {prefix} on {db}: {action}\n"
        layout.addWidget(QtWidgets.QLabel(msg))

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        apply_btn = QtWidgets.QPushButton(t("Apply"))
        cancel_btn = QtWidgets.QPushButton(t("Cancel"))
        apply_btn.clicked.connect(self.accept)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(apply_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

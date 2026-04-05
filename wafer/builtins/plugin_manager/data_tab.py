from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.paths import list_setting_db_names, data_db_path, setting_db_path
from ...core.db.setting_db import SettingDB
from ...core.db.file_db import FileDB
from ...core.qt.dispatcher import Dispatcher, CancelSlot


_COL_DB = 0
_COL_PREFIX = 1
_COL_META = 2
_COL_TAGS = 3
_COL_PLUGIN = 4
_COL_STATUS = 5
_COL_CHECK = 6
_COLUMN_COUNT = 7
_HEADERS = ['Database', 'Prefix', 'Meta', 'Tags', 'Plugin', 'Status', '']


class _NumericItem(QtWidgets.QTableWidgetItem):
    def __lt__(self, other):
        try:
            return int(self.text().replace(',', '')) < int(other.text().replace(',', ''))
        except (ValueError, AttributeError):
            return super().__lt__(other)


def _resolve_plugin_info(prefix: str) -> tuple[str, str]:
    from ...plugin.collector.handler import collector_resolver
    from ...plugin.detacher.handler import detacher_resolver
    if collector_resolver.registry.get(prefix):
        return 'Collector', prefix
    if detacher_resolver.registry.get(prefix):
        return 'Detacher', prefix
    return '', ''


def _build_rows(db_names: list[str], cancel) -> list[tuple[str, str, int, int, str, str, bool]]:
    rows: list[tuple[str, str, int, int, str, str, bool]] = []
    for name in db_names:
        if cancel.is_cancelled():
            return []
        sdb = SettingDB(setting_db_path(name))
        enabled = set(sdb.get_enabled_collectors() or [])
        try:
            fdb = FileDB(data_db_path(name))
            fdb.start()
            prefix_data = fdb.prefix_data_summary()
            fdb.close()
        except Exception:
            prefix_data = []
        seen_prefixes: set[str] = set()
        for prefix, meta_count, tag_count in prefix_data:
            seen_prefixes.add(prefix)
            plugin_type, _ = _resolve_plugin_info(prefix)
            if prefix and prefix in enabled:
                status = 'Active'
            elif prefix and plugin_type:
                status = 'Disabled'
            else:
                status = ''
            purgeable = bool(prefix)
            rows.append((name, prefix, meta_count, tag_count, plugin_type, status, purgeable))
        for en in sorted(enabled - seen_prefixes):
            plugin_type, _ = _resolve_plugin_info(en)
            if not plugin_type:
                continue
            rows.append((name, en, 0, 0, plugin_type, 'Active', True))
    return rows


class DataTab(QtWidgets.QWidget):

    purge_requested = QtCore.Signal(list, bool)

    def __init__(self, dispatcher: Dispatcher, parent=None):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._cancel = CancelSlot()
        self._rows: list[tuple[str, str, int, int, str, str, bool]] = []
        self.destroyed.connect(lambda: self._cancel.renew())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(6))

        label = QtWidgets.QLabel('Collected Data')
        label.setObjectName('section_header')
        layout.addWidget(label)

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(_COLUMN_COUNT)
        self._table.setHorizontalHeaderLabels(_HEADERS)
        header = self._table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(_COL_DB, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_PREFIX, QtWidgets.QHeaderView.Stretch)
        header.setSectionResizeMode(_COL_META, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_TAGS, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_PLUGIN, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_STATUS, QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(_COL_CHECK, QtWidgets.QHeaderView.Fixed)
        self._table.setColumnWidth(_COL_CHECK, dpix(30))
        self._table.setSortingEnabled(True)
        self._table.setSelectionMode(QtWidgets.QAbstractItemView.NoSelection)
        self._table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        layout.addWidget(self._table, 1)

        self._selected_label = QtWidgets.QLabel('Selected: 0 items')
        layout.addWidget(self._selected_label)

        self._re_collect_cb = QtWidgets.QCheckBox('Re-collect after purge (mark as pending)')
        self._re_collect_cb.setChecked(True)
        layout.addWidget(self._re_collect_cb)

        self._purge_btn = QtWidgets.QPushButton('Purge Selected')
        self._purge_btn.setObjectName('purge_btn')
        self._purge_btn.setFixedWidth(dpix(140))
        self._purge_btn.clicked.connect(self._on_purge)
        layout.addWidget(self._purge_btn)

        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(4000)
        self._timer.timeout.connect(self._poll)

        self._load_async()

    def showEvent(self, event):
        super().showEvent(event)
        self._timer.start()

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def _load_async(self):
        cancel = self._cancel.renew()
        db_names = list_setting_db_names()

        def task():
            rows = _build_rows(db_names, cancel)
            if rows is not None and not cancel.is_cancelled():
                self._dispatcher.invoke(lambda: self._apply_rows(rows))

        self._dispatcher.post(task, priority=5, cancel=cancel)

    def _apply_rows(self, rows: list[tuple[str, str, int, int, str, str, bool]]):
        self._rows = rows
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(rows))
        for i, (db, prefix, meta, tags, plugin_type, status, purgeable) in enumerate(rows):
            self._table.setItem(i, _COL_DB, QtWidgets.QTableWidgetItem(db))
            prefix_text = prefix if prefix else '(no prefix)'
            self._table.setItem(i, _COL_PREFIX, QtWidgets.QTableWidgetItem(prefix_text))

            meta_item = _NumericItem(f'{meta:,}')
            meta_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self._table.setItem(i, _COL_META, meta_item)

            tags_item = _NumericItem(f'{tags:,}')
            tags_item.setTextAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
            self._table.setItem(i, _COL_TAGS, tags_item)

            self._table.setItem(i, _COL_PLUGIN, QtWidgets.QTableWidgetItem(plugin_type))
            self._table.setItem(i, _COL_STATUS, QtWidgets.QTableWidgetItem(status))

            cb = QtWidgets.QCheckBox()
            if not purgeable:
                cb.setEnabled(False)
            cb.stateChanged.connect(self._update_selected_count)
            container = QtWidgets.QWidget()
            cb_layout = QtWidgets.QHBoxLayout(container)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(QtCore.Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(i, _COL_CHECK, container)
        self._table.setSortingEnabled(True)

    def _update_selected_count(self):
        count = 0
        for i in range(self._table.rowCount()):
            container = self._table.cellWidget(i, _COL_CHECK)
            if container:
                cb = container.findChild(QtWidgets.QCheckBox)
                if cb and cb.isChecked():
                    count += 1
        self._selected_label.setText(f'Selected: {count} items')

    def _on_purge(self):
        selected = []
        for i in range(self._table.rowCount()):
            container = self._table.cellWidget(i, _COL_CHECK)
            if not container:
                continue
            cb = container.findChild(QtWidgets.QCheckBox)
            if cb and cb.isChecked():
                db = self._table.item(i, _COL_DB).text()
                prefix = self._table.item(i, _COL_PREFIX).text()
                if prefix == '(no prefix)':
                    continue
                selected.append((db, prefix))
        if not selected:
            return
        re_collect = self._re_collect_cb.isChecked()
        msg = f'Purge {len(selected)} prefix(es)?\n\n'
        for db, prefix in selected:
            msg += f'  {prefix} on {db}\n'
        if re_collect:
            msg += '\nFiles will be marked for re-collection.'
        result = QtWidgets.QMessageBox.question(
            self, 'Confirm Purge', msg,
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if result != QtWidgets.QMessageBox.Yes:
            return
        self.purge_requested.emit(selected, re_collect)

    def refresh(self):
        self._load_async()

    def _poll(self):
        cancel = self._cancel.renew()
        db_names = list_setting_db_names()

        def task():
            rows = _build_rows(db_names, cancel)
            if rows is not None and not cancel.is_cancelled():
                self._dispatcher.invoke(lambda r=rows: self._merge_rows(r))

        self._dispatcher.post(task, priority=7, cancel=cancel)

    def _merge_rows(self, rows: list[tuple[str, str, int, int, str, str, bool]]):
        old_set = {(r[0], r[1]) for r in self._rows}
        new_set = {(r[0], r[1]) for r in rows}
        if old_set != new_set:
            self._apply_rows(rows)
            return
        old_data = {(r[0], r[1]): r[2:] for r in self._rows}
        new_data = {(r[0], r[1]): r[2:] for r in rows}
        for i in range(self._table.rowCount()):
            db = self._table.item(i, _COL_DB).text()
            prefix_text = self._table.item(i, _COL_PREFIX).text()
            prefix = '' if prefix_text == '(no prefix)' else prefix_text
            key = (db, prefix)
            old = old_data.get(key)
            new = new_data.get(key)
            if old is None or new is None:
                continue
            if old[0] != new[0]:
                self._table.item(i, _COL_META).setText(f'{new[0]:,}')
            if old[1] != new[1]:
                self._table.item(i, _COL_TAGS).setText(f'{new[1]:,}')
            if old[2] != new[2]:
                self._table.item(i, _COL_PLUGIN).setText(new[2])
            if old[3] != new[3]:
                self._table.item(i, _COL_STATUS).setText(new[3])
        self._rows = rows

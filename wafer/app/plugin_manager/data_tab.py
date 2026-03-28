from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.logs import AppLogger
from ...utils.paths import list_setting_db_names, data_db_path, setting_db_path
from ...core.db.setting_db import SettingDB
from ...core.db.file_db import FileDB
from ...core.qt.dispatcher import Dispatcher, CancelSlot


class DataTab(QtWidgets.QWidget):

    purge_requested = QtCore.Signal(list, bool)

    def __init__(self, dispatcher: Dispatcher, parent=None):
        super().__init__(parent)
        self._dispatcher = dispatcher
        self._cancel = CancelSlot()
        self._rows: list[tuple[str, str, int, str]] = []
        self._checkboxes: list[QtWidgets.QCheckBox] = []
        self.destroyed.connect(lambda: self._cancel.renew())

        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(dpix(6))

        label = QtWidgets.QLabel('Collected data per database:')
        label.setStyleSheet(f'font-weight: bold; font-size: {dpix(12)}px;')
        layout.addWidget(label)

        self._table = QtWidgets.QTableWidget()
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(['Database', 'Collector', 'Collected', 'Status', ''])
        self._table.horizontalHeader().setStretchLastSection(True)
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
        self._purge_btn.setFixedWidth(dpix(140))
        self._purge_btn.clicked.connect(self._on_purge)
        layout.addWidget(self._purge_btn)

        self._load_async()

    def _load_async(self):
        cancel = self._cancel.renew()
        db_names = list_setting_db_names()

        def task():
            rows = []
            for name in db_names:
                if cancel.is_cancelled():
                    return
                db_path = data_db_path(name)
                sdb = SettingDB(setting_db_path(name))
                enabled = set(sdb.get_enabled_collectors() or [])
                try:
                    fdb = FileDB(db_path)
                    fdb.start()
                    counts = dict(fdb.collector_data_counts())
                    fdb.close()
                except Exception:
                    counts = {}
                all_collectors = set(counts.keys()) | enabled
                for coll in sorted(all_collectors):
                    count = counts.get(coll, 0)
                    status = 'Active' if coll in enabled else 'Disabled'
                    if count == 0 and coll not in enabled:
                        status = '\u2014'
                    rows.append((name, coll, count, status))
            if not cancel.is_cancelled():
                self._dispatcher.invoke(lambda: self._apply_rows(rows))

        self._dispatcher.post(task, priority=5, cancel=cancel)

    def _apply_rows(self, rows: list[tuple[str, str, int, str]]):
        self._rows = rows
        self._table.setRowCount(len(rows))
        self._checkboxes: list[QtWidgets.QCheckBox] = []
        for i, (db, coll, count, status) in enumerate(rows):
            self._table.setItem(i, 0, QtWidgets.QTableWidgetItem(db))
            self._table.setItem(i, 1, QtWidgets.QTableWidgetItem(coll))
            self._table.setItem(i, 2, QtWidgets.QTableWidgetItem(f'{count:,}'))
            self._table.setItem(i, 3, QtWidgets.QTableWidgetItem(status))
            cb = QtWidgets.QCheckBox()
            cb.stateChanged.connect(self._update_selected_count)
            self._checkboxes.append(cb)
            container = QtWidgets.QWidget()
            cb_layout = QtWidgets.QHBoxLayout(container)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(QtCore.Qt.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._table.setCellWidget(i, 4, container)
        self._table.resizeColumnsToContents()

    def _update_selected_count(self):
        count = sum(1 for cb in self._checkboxes if cb.isChecked())
        self._selected_label.setText(f'Selected: {count} items')

    def _on_purge(self):
        selected = [
            (self._rows[i][0], self._rows[i][1])
            for i, cb in enumerate(self._checkboxes)
            if cb.isChecked()
        ]
        if not selected:
            return
        re_collect = self._re_collect_cb.isChecked()
        msg = f'Purge {len(selected)} collector(s)?\n\n'
        for db, coll in selected:
            msg += f'  {coll} on {db}\n'
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

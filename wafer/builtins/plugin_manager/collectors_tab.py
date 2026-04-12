from PySide6 import QtWidgets, QtCore
from ...utils.formatting import dpix
from ...utils.paths import list_setting_db_names, setting_db_path
from ...core.db.setting_db import SettingDB
from ...core.lang.manager import t


class CollectorsTab(QtWidgets.QWidget):
    purge_requested = QtCore.Signal(list, bool)

    def __init__(self, collector_names: list[str] | None = None, detacher_names: list[str] | None = None, parent=None):
        super().__init__(parent)
        if collector_names is None:
            from ...plugin.collector.handler import collector_resolver

            collector_names = list(collector_resolver.names())
        if detacher_names is None:
            from ...plugin.detacher.handler import detacher_resolver

            detacher_names = list(detacher_resolver.names())
        self._collector_names: list[str] = list(collector_names)
        self._detacher_names: list[str] = list(detacher_names)
        self._db_names: list[str] = list_setting_db_names()
        self._all_checks: dict[str, QtWidgets.QCheckBox] = {}
        self._matrix: dict[tuple[str, str], QtWidgets.QCheckBox] = {}

        self._initial_state: dict[str, set[str]] = {}
        for db in self._db_names:
            sdb = SettingDB(setting_db_path(db))
            self._initial_state[db] = set(sdb.get_enabled_collectors() or [])

        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(dpix(8))
        desc = QtWidgets.QLabel(t("Per-Database Assignment"))
        desc.setObjectName("section_header")
        outer.addWidget(desc)
        self._content = QtWidgets.QWidget()
        self._main_layout = QtWidgets.QVBoxLayout(self._content)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(dpix(8))
        outer.addWidget(self._content, 1)

        self._build_matrix()

    @property
    def _all_names(self) -> list[str]:
        return self._collector_names + self._detacher_names

    def _build_matrix(self):
        self._clear_matrix()

        if not self._all_names:
            self._main_layout.addWidget(QtWidgets.QLabel(t("No collector or detacher plugins loaded.")))
            self._main_layout.addStretch()
            return

        if not self._db_names:
            self._main_layout.addWidget(QtWidgets.QLabel(t("No databases found.")))
            self._main_layout.addStretch()
            return

        if self._collector_names:
            self._main_layout.addWidget(self._build_group("Collectors", self._collector_names))
        if self._detacher_names:
            self._main_layout.addWidget(self._build_group("Detachers", self._detacher_names))
        self._main_layout.addStretch()

    def _build_group(self, title: str, names: list[str]) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        grid = QtWidgets.QGridLayout(group)
        grid.setSpacing(dpix(4))

        def _vsep():
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.VLine)
            sep.setFrameShadow(QtWidgets.QFrame.Sunken)
            return sep

        total_rows = len(names) + 1
        for r in range(total_rows):
            grid.addWidget(_vsep(), r, 1)
            grid.addWidget(_vsep(), r, 3)

        grid.addWidget(QtWidgets.QLabel(t("All")), 0, 2, QtCore.Qt.AlignCenter)
        for col_idx, db in enumerate(self._db_names):
            lbl = QtWidgets.QLabel(db)
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(lbl, 0, col_idx + 4)

        for row_idx, name in enumerate(names):
            lbl = QtWidgets.QLabel(name)
            grid.addWidget(lbl, row_idx + 1, 0)

            all_cb = QtWidgets.QCheckBox()
            all_cb.setTristate(True)
            all_cb.clicked.connect(lambda checked, n=name: self._on_all_toggled(n, checked))
            self._all_checks[name] = all_cb
            grid.addWidget(all_cb, row_idx + 1, 2, QtCore.Qt.AlignCenter)

            for col_idx, db in enumerate(self._db_names):
                cb = QtWidgets.QCheckBox()
                cb.setChecked(name in self._initial_state.get(db, set()))
                cb.stateChanged.connect(lambda _s, n=name: self._sync_all_check(n))
                self._matrix[(name, db)] = cb
                grid.addWidget(cb, row_idx + 1, col_idx + 4, QtCore.Qt.AlignCenter)

            self._sync_all_check(name)

        return group

    def _clear_matrix(self):
        self._all_checks.clear()
        self._matrix.clear()
        while self._main_layout.count():
            item = self._main_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def refresh(self, collector_names: list[str], detacher_names: list[str]):
        if self._matrix:
            saved = self.get_per_db_collectors()
            known = set(self._all_names)
            for db in self._db_names:
                prev = self._initial_state.get(db, set())
                ui_state = set(saved.get(db, []))
                self._initial_state[db] = ui_state | (prev - known)
        self._collector_names = list(collector_names)
        self._detacher_names = list(detacher_names)
        self._build_matrix()

    def _on_all_toggled(self, name: str, checked: bool):
        for db in self._db_names:
            cb = self._matrix.get((name, db))
            if cb:
                cb.setChecked(checked)
        self._sync_all_check(name)

    def _sync_all_check(self, name: str):
        all_cb = self._all_checks.get(name)
        if not all_cb:
            return
        states = []
        for db in self._db_names:
            cb = self._matrix.get((name, db))
            if cb:
                states.append(cb.isChecked())
        all_cb.blockSignals(True)
        if all(states):
            all_cb.setCheckState(QtCore.Qt.Checked)
        elif any(states):
            all_cb.setCheckState(QtCore.Qt.PartiallyChecked)
        else:
            all_cb.setCheckState(QtCore.Qt.Unchecked)
        all_cb.blockSignals(False)

    def get_per_db_collectors(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for db in self._db_names:
            enabled = []
            for name in self._all_names:
                cb = self._matrix.get((name, db))
                if cb and cb.isChecked():
                    enabled.append(name)
            result[db] = enabled
        return result

    def save_to_dbs(self):
        per_db = self.get_per_db_collectors()
        for db, collectors in per_db.items():
            sdb = SettingDB(setting_db_path(db))
            sdb.set_enabled_collectors(collectors)

    def has_changes(self) -> bool:
        per_db = self.get_per_db_collectors()
        return any(set(per_db.get(db, [])) != self._initial_state.get(db, set()) for db in self._db_names)

    def get_newly_disabled(self) -> list[tuple[str, str]]:
        disabled = []
        per_db = self.get_per_db_collectors()
        for db in self._db_names:
            prev = self._initial_state.get(db, set())
            curr = set(per_db.get(db, []))
            for name in prev - curr:
                disabled.append((db, name))
        return disabled

    def confirm_and_save(self) -> bool:
        disabled = self.get_newly_disabled()
        if not disabled:
            self.save_to_dbs()
            return True

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(t("Confirm Disable"))
        layout = QtWidgets.QVBoxLayout(dlg)
        layout.addWidget(QtWidgets.QLabel(t("The following plugins will be disabled:")))

        purge_checks: list[tuple[QtWidgets.QCheckBox, str, str]] = []
        for db, name in disabled:
            cb = QtWidgets.QCheckBox(f"Delete data: {name} on {db}")
            purge_checks.append((cb, db, name))
            layout.addWidget(cb)

        layout.addWidget(QtWidgets.QLabel(t("Unchecked items keep their data.\n(re-enable later to use again without re-collecting)")))

        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addStretch()
        confirm_btn = QtWidgets.QPushButton(t("Confirm"))
        cancel_btn = QtWidgets.QPushButton(t("Cancel"))
        confirm_btn.clicked.connect(dlg.accept)
        cancel_btn.clicked.connect(dlg.reject)
        btn_layout.addWidget(confirm_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)

        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return False

        to_purge = [(db, name) for cb, db, name in purge_checks if cb.isChecked()]
        self.save_to_dbs()
        if to_purge:
            self.purge_requested.emit(to_purge, False)
        return True

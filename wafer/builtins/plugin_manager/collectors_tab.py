from PySide6 import QtWidgets, QtCore, QtGui
from ...utils.formatting import dpix
from ...utils.paths import list_setting_db_names, setting_db_path
from ...core.db.setting_db import SettingDB
from ...core.lang.manager import t


class _ClickableLabel(QtWidgets.QLabel):
    clicked = QtCore.Signal()

    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


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
        self._default_checks: dict[str, QtWidgets.QCheckBox] = {}
        self._matrix: dict[tuple[str, str], QtWidgets.QCheckBox] = {}

        self._initial_defaults = self._load_defaults() & set(self._all_names)
        self._initial_state: dict[str, set[str]] = {}
        for db in self._db_names:
            sdb = SettingDB(setting_db_path(db))
            enabled = sdb.get_enabled_collectors()
            if enabled is not None:
                self._initial_state[db] = set(enabled)
            else:
                self._initial_state[db] = set(self._initial_defaults)

        outer = QtWidgets.QVBoxLayout(self)
        outer.setSpacing(dpix(8))
        self._content = QtWidgets.QWidget()
        self._main_layout = QtWidgets.QVBoxLayout(self._content)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(dpix(8))
        outer.addWidget(self._content, 1)

        self._build_ui()

    def _load_defaults(self) -> set[str]:
        from ...plugin.settings import PluginSettings

        return set(PluginSettings().resolve_default_collectors())

    @property
    def _all_names(self) -> list[str]:
        return self._collector_names + self._detacher_names

    def _build_ui(self):
        self._clear_ui()

        if not self._all_names:
            self._main_layout.addWidget(QtWidgets.QLabel(t("No collector or detacher plugins loaded.")))
            self._main_layout.addStretch()
            return

        self._main_layout.addWidget(self._build_defaults_section())

        if self._db_names:
            header = QtWidgets.QLabel(t("Per-Database Assignment"))
            header.setObjectName("section_header")
            self._main_layout.addWidget(header)
            if self._collector_names:
                self._main_layout.addWidget(self._build_db_group("Collectors", self._collector_names))
            if self._detacher_names:
                self._main_layout.addWidget(self._build_db_group("Detachers", self._detacher_names))
        else:
            self._main_layout.addWidget(QtWidgets.QLabel(t("No databases found.")))

        self._main_layout.addStretch()

    def _build_defaults_section(self) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(t("Default for New Databases"))
        layout = QtWidgets.QVBoxLayout(group)
        layout.setSpacing(dpix(4))
        if self._collector_names:
            layout.addLayout(self._build_defaults_row("Collectors", self._collector_names))
        if self._detacher_names:
            layout.addLayout(self._build_defaults_row("Detachers", self._detacher_names))
        return group

    def _build_defaults_row(self, label: str, names: list[str]) -> QtWidgets.QHBoxLayout:
        row = QtWidgets.QHBoxLayout()
        row.setSpacing(dpix(8))
        lbl = QtWidgets.QLabel(f"{label}:")
        lbl.setStyleSheet("font-weight: bold;")
        row.addWidget(lbl)
        for name in names:
            cb = QtWidgets.QCheckBox(name)
            cb.setChecked(name in self._initial_defaults)
            self._default_checks[name] = cb
            row.addWidget(cb)
        row.addStretch()
        return row

    def _build_db_group(self, title: str, names: list[str]) -> QtWidgets.QGroupBox:
        group = QtWidgets.QGroupBox(title)
        grid = QtWidgets.QGridLayout(group)
        grid.setSpacing(dpix(4))

        for col_idx, db in enumerate(self._db_names):
            lbl = QtWidgets.QLabel(db)
            lbl.setAlignment(QtCore.Qt.AlignCenter)
            grid.addWidget(lbl, 0, col_idx + 2)

        def _vsep():
            sep = QtWidgets.QFrame()
            sep.setFrameShape(QtWidgets.QFrame.VLine)
            sep.setFrameShadow(QtWidgets.QFrame.Sunken)
            return sep

        total_rows = len(names) + 1
        for r in range(total_rows):
            grid.addWidget(_vsep(), r, 1)

        for row_idx, name in enumerate(names):
            lbl = _ClickableLabel(name)
            lbl.setToolTip(t("Click to toggle all databases"))
            lbl.clicked.connect(lambda n=name: self._toggle_all(n))
            grid.addWidget(lbl, row_idx + 1, 0)

            for col_idx, db in enumerate(self._db_names):
                cb = QtWidgets.QCheckBox()
                cb.setChecked(name in self._initial_state.get(db, set()))
                self._matrix[(name, db)] = cb
                grid.addWidget(cb, row_idx + 1, col_idx + 2, QtCore.Qt.AlignCenter)

        return group

    def _toggle_all(self, name: str):
        any_unchecked = any(
            not self._matrix[(name, db)].isChecked()
            for db in self._db_names
            if (name, db) in self._matrix
        )
        for db in self._db_names:
            cb = self._matrix.get((name, db))
            if cb:
                cb.setChecked(any_unchecked)

    def _clear_ui(self):
        self._default_checks.clear()
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
        self._build_ui()

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

    def get_default_collectors(self) -> list[str]:
        return [name for name in self._all_names if (cb := self._default_checks.get(name)) and cb.isChecked()]

    def save_to_dbs(self):
        per_db = self.get_per_db_collectors()
        for db, collectors in per_db.items():
            sdb = SettingDB(setting_db_path(db))
            sdb.set_enabled_collectors(collectors)

    def save_defaults(self):
        from ...plugin.settings import PluginSettings

        PluginSettings().set_default_enabled_collectors(self.get_default_collectors())

    def has_changes(self) -> bool:
        per_db = self.get_per_db_collectors()
        if any(set(per_db.get(db, [])) != self._initial_state.get(db, set()) for db in self._db_names):
            return True
        return set(self.get_default_collectors()) != self._initial_defaults

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
            self.save_defaults()
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
        self.save_defaults()
        if to_purge:
            self.purge_requested.emit(to_purge, False)
        return True

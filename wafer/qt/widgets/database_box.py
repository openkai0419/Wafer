from __future__ import annotations

from collections.abc import Callable

from PySide6 import QtWidgets

from wafer.core.common.paths import list_data_db_names


class DatabaseBox(QtWidgets.QComboBox):
    def __init__(self, can_open: Callable[[str], bool] | None = None, parent=None):
        super().__init__(parent)
        self.can_open = can_open

    def showPopup(self) -> None:
        self.reload()
        super().showPopup()

    def add_name(self, name: str) -> None:
        self.addItem(name)
        if self.can_open is not None:
            self.model().item(self.count() - 1).setEnabled(self.can_open(name))

    def reload(self) -> None:
        current = self.currentText()
        names = sorted(set(list_data_db_names()) | ({current} if current else set()))
        self.blockSignals(True)
        self.clear()
        for name in names:
            self.add_name(name)
        self.setCurrentText(current)
        self.blockSignals(False)

    def show_quietly(self, name: str) -> None:
        if not name:
            return
        self.blockSignals(True)
        if self.findText(name) < 0:
            self.add_name(name)
        self.setCurrentText(name)
        self.blockSignals(False)

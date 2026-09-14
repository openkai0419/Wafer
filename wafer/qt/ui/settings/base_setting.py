from PySide6 import QtWidgets


class SettingsTabBase(QtWidgets.QWidget):
    name = "Base"
    "Base class for setting tabs"

    def apply_settings(self):
        pass

    def has_unsaved_changes(self):
        return False

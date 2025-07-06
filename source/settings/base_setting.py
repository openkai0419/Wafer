from PySide6 import QtWidgets

class SettingsTabBase(QtWidgets.QWidget):
    name = "Base"
    """Base class for setting tabs"""
    def apply_settings(self):
        """Apply modifications"""
        pass

    def has_unsaved_changes(self) -> bool:
        """Return True if there are unsaved edits"""
        return False
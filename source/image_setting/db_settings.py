from PySide6 import QtWidgets, QtGui, QtCore

from .widgets.foldersetting import FolderListWidget
from .base_setting import SettingsTabBase
from .translation import TranslatorMixin

class DataBaseSettings(SettingsTabBase, TranslatorMixin):
    name = "Folder Settings"
    def __init__(self,):
        super().__init__()
        self.name = self.t.tr("Folder Settings")


    """Base class for settings tabs"""
    def apply_settings(self):
        """Apply changes"""
        pass

    def has_unsaved_changes(self) -> bool:
        """Check for unsaved changes"""
        return False
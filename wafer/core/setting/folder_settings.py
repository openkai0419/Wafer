from .base_setting import SettingsTabBase
from ..lang.manager import TranslatorMixin


class FolderSettings(SettingsTabBase, TranslatorMixin):
    name = "Folder Settings"

    def __init__(self):
        super().__init__()
        self.name = self.t.tr("Folder Settings")

    "Base class for settings tabs"

    def apply_settings(self):
        pass

    def has_unsaved_changes(self):
        return False

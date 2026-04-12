from .base_setting import SettingsTabBase
from wafer.core.lang.manager import t


class FolderSettings(SettingsTabBase):
    name = "Folder Settings"

    def __init__(self):
        super().__init__()
        self.name = t("Folder Settings")

    "Base class for settings tabs"

    def apply_settings(self):
        pass

    def has_unsaved_changes(self):
        return False

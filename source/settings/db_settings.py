from PySide6 import QtWidgets, QtGui, QtCore

from .widgets.foldersetting import FolderListWidget
from .base_setting import SettingsTabBase
from .translation import TranslatorMixin

class DataBaseSettings(SettingsTabBase, TranslatorMixin):
    name = "フォルダ設定"
    def __init__(self,):
        super().__init__()
        self.name = self.t.tr("フォルダ設定")


    """設定タブの基底クラス"""
    def apply_settings(self):
        """変更を適用"""
        pass

    def has_unsaved_changes(self) -> bool:
        """未保存の変更があるか"""
        return False
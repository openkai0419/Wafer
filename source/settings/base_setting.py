from PySide6 import QtWidgets

class SettingsTabBase(QtWidgets.QWidget):
    name = "Base"
    """設定タブの基底クラス"""
    def apply_settings(self):
        """変更を適用"""
        pass

    def has_unsaved_changes(self) -> bool:
        """未保存の変更があるか"""
        return False
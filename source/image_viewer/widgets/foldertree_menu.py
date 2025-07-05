from PySide6 import QtWidgets, QtGui, QtCore

from ...common import normalize_path
from ...dialog import ConfirmDialog

class FolderContextMenuBuilder:
    def __init__(self, parent, root):
        self.view = parent
        self.root = root

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.view)
        menu.addAction("パスをコピー", lambda: self.copy_path(path))
        menu.addAction("エクスプローラーで開く", lambda: self.open_in_explorer(path))
        menu.addSeparator()
        if path in self.view.roots:
            pass
            menu.addAction("除去", lambda: self.remove(path))
        else:
            menu.addAction("除外", lambda: self.ignore(path))
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def remove(self, path):
        result = ConfirmDialog.ask(f"表示リストから除去しますか？: \n{path}", title="確認", buttons=("除去する", "キャンセル"), parent=self.view)
        if result == "除去する":
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(f"表示リストから除外しますか？: \n{path}", title="確認", buttons=("除外する", "キャンセル"), parent=self.view)
        if result == "除外する":
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)
        

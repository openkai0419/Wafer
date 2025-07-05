from PySide6 import QtWidgets, QtGui, QtCore

from ...common import normalize_path
from ...dialog import ConfirmDialog
from ...settings.translation import TranslatorMixin

class FolderContextMenuBuilder(TranslatorMixin):
    def __init__(self, parent, root):
        self.view = parent
        self.root = root

    def build_menu(self, path: str) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(self.view)
        menu.addAction(self.t.tr("パスをコピー"), lambda: self.copy_path(path))
        menu.addAction(self.t.tr("エクスプローラーで開く"), lambda: self.open_in_explorer(path))
        menu.addSeparator()
        if path in self.view.roots:
            pass
            menu.addAction(self.t.tr("除去"), lambda: self.remove(path))
        else:
            menu.addAction(self.t.tr("除外"), lambda: self.ignore(path))
        return menu

    def open_in_explorer(self, path):
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path))

    def copy_path(self, path):
        QtGui.QGuiApplication.clipboard().setText(path)

    def remove(self, path):
        result = ConfirmDialog.ask(self.t.trf("表示リストから除去しますか？: \n{path}", path=path),
                                   title=self.t.tr("確認"),
                                   buttons=(self.t.tr("除去する"), self.t.tr("キャンセル")), parent=self.view)
        if result == self.t.tr("除去する"):
            if path in self.view.roots:
                self.view.remove_root(path)
                self.root.setting_db.remove_parent_folder(path)

    def ignore(self, path):
        result = ConfirmDialog.ask(self.t.trf("表示リストから除外しますか？: \n{path}", path=path),
                                   title=self.t.tr("確認"),
                                   buttons=(self.t.tr("除外する"), self.t.tr("キャンセル")), parent=self.view)
        if result == self.t.tr("除外する"):
            path = normalize_path(path)
            self.view.add_excluded(path)
            self.root.setting_db.add_ignore_folder(path)
        

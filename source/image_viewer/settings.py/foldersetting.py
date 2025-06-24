from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QPushButton, QFileDialog, QMessageBox, QMenu, QStackedLayout
)
from PySide6.QtCore import Qt, QPoint
import sys
import os


class FolderListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("フォルダリストマネージャー")
        self.resize(400, 300)

        self.folder_list = QListWidget()
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_context_menu)
        self.folder_list.itemDoubleClicked.connect(self.replace_folder)
        self.folder_list.setAlternatingRowColors(True)

        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(25, 25)
        self.add_button.setToolTip("フォルダを追加")

        # ボタンを重ねるレイアウト
        self.overlay_layout = QVBoxLayout()
        self.overlay_layout.addWidget(self.folder_list)
        self.overlay_layout.setContentsMargins(0, 0, 0, 0)

        container = QWidget()
        container.setLayout(self.overlay_layout)

        self.main_layout = QStackedLayout(self)
        self.main_layout.addWidget(container)

        self.add_button.setParent(self.folder_list)
        self.add_button.move(self.folder_list.width() - 30, 5)

        self.folder_list.resizeEvent = self.on_resize

        # シグナル接続
        self.add_button.clicked.connect(self.add_folder)

    def on_resize(self, event):
        self.add_button.move(self.folder_list.width() - 30, 5)
        QListWidget.resizeEvent(self.folder_list, event)

    def show_context_menu(self, position: QPoint):
        item = self.folder_list.itemAt(position)
        if item:
            menu = QMenu(self)
            delete_action = menu.addAction("削除")
            action = menu.exec(self.folder_list.mapToGlobal(position))
            if action == delete_action:
                self.confirm_and_remove_item(item)

    def confirm_and_remove_item(self, item):
        reply = QMessageBox.question(
            self,
            "確認",
            f"選択したフォルダを削除します。よろしいですか？\n\n{item.text()}",
            QMessageBox.Yes | QMessageBox.No
        )
        if reply == QMessageBox.Yes:
            self.folder_list.takeItem(self.folder_list.row(item))

    def add_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder_path:
            self._add_folder_path(folder_path)

    def _add_folder_path(self, path: str):
        """正規化・存在チェック・重複回避付きでパスを追加"""
        normalized_path = os.path.normpath(path)
        existing_paths = set(self.get_folder_list())
        if os.path.exists(normalized_path) and normalized_path not in existing_paths:
            self.folder_list.addItem(normalized_path)
            self.sort_folder_list()

    def replace_folder(self, item):
        old_path = item.text()
        new_path = QFileDialog.getExistingDirectory(self, "フォルダを再選択", old_path)
        if new_path:
            normalized_new_path = os.path.normpath(new_path)
            existing_paths = set(self.get_folder_list()) - {old_path}
            if os.path.exists(normalized_new_path) and normalized_new_path not in existing_paths:
                item.setText(normalized_new_path)
                self.sort_folder_list()

    def sort_folder_list(self):
        self.folder_list.sortItems(Qt.AscendingOrder)

    def set_folder_list(self, paths: list[str]):
        """コード側から一括設定（正規化・重複除去・存在チェックつき）"""
        for path in paths:
            self._add_folder_path(path)

    def get_folder_list(self) -> list[str]:
        """現在のリストを返す"""
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = FolderListWidget()

    # 初期フォルダリストを設定
    initial_folders = [
        "C:/Users/okab/Pictures",
        "D:/images",
        "C:/nonexistent/path"  # 存在しないパスは無視される
    ]
    window.set_folder_list(initial_folders)

    window.show()
    sys.exit(app.exec())
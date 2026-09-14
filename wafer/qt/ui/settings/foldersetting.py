import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFileDialog, QListWidget, QMessageBox, QPushButton, QStackedLayout, QVBoxLayout, QWidget
from wafer.utils.formatting import dpix
from wafer.utils.paths import safe_exists
from wafer.core.lang.manager import t
from wafer.core.commands.bridge import ActionKit, Menu


class FolderListWidget(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(t("Folder List Manager"))
        self.resize(dpix(400), dpix(300))
        self.folder_list = QListWidget()
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_context_menu)
        self.folder_list.itemDoubleClicked.connect(self.replace_folder)
        self.folder_list.setAlternatingRowColors(True)
        self.add_button = QPushButton("+")
        self.add_button.setFixedSize(dpix(25), dpix(25))
        self.add_button.setToolTip(t("Add folder"))
        self.overlay_layout = QVBoxLayout()
        self.overlay_layout.addWidget(self.folder_list)
        self.overlay_layout.setContentsMargins(0, 0, 0, 0)
        container = QWidget()
        container.setLayout(self.overlay_layout)
        self.main_layout = QStackedLayout(self)
        self.main_layout.addWidget(container)
        self.add_button.setParent(self.folder_list)
        self.add_button.move(self.folder_list.width() - dpix(30), dpix(5))
        self.folder_list.resizeEvent = self.on_resize
        self.add_button.clicked.connect(self.add_folder)

    def on_resize(self, event):
        self.add_button.move(self.folder_list.width() - dpix(30), dpix(5))
        QListWidget.resizeEvent(self.folder_list, event)

    def show_context_menu(self, position):
        item = self.folder_list.itemAt(position)
        if item:
            uid = f"{id(self):x}.{self.folder_list.row(item)}"
            spec = Menu.session(self).menu(
                [
                    ":Folder",
                    ActionKit.Action(path=f"inline.folder_list.{uid}.delete", display="Delete", func=lambda ctx, i=item: self.confirm_and_remove_item(i)),
                ]
            )
            if spec is not None:
                spec.exec(self.folder_list.mapToGlobal(position))

    def confirm_and_remove_item(self, item):
        reply = QMessageBox.question(self, t("Confirm"), t("Remove selected folder?\n\n{path}", path=item.text()), QMessageBox.Yes | QMessageBox.No)
        if reply == QMessageBox.Yes:
            self.folder_list.takeItem(self.folder_list.row(item))

    def add_folder(self):
        folder_path = QFileDialog.getExistingDirectory(self, t("Select folder"))
        if folder_path:
            self._add_folder_path(folder_path)

    def _add_folder_path(self, path):
        normalized_path = os.path.normpath(path)
        existing_paths = set(self.get_folder_list())
        if safe_exists(normalized_path) and normalized_path not in existing_paths:
            self.folder_list.addItem(normalized_path)
            self.sort_folder_list()

    def replace_folder(self, item):
        old_path = item.text()
        new_path = QFileDialog.getExistingDirectory(self, t("Select folder again"), old_path)
        if new_path:
            normalized_new_path = os.path.normpath(new_path)
            existing_paths = set(self.get_folder_list()) - {old_path}
            if safe_exists(normalized_new_path) and normalized_new_path not in existing_paths:
                item.setText(normalized_new_path)
                self.sort_folder_list()

    def sort_folder_list(self):
        self.folder_list.sortItems(Qt.AscendingOrder)

    def set_folder_list(self, paths):
        for path in paths:
            self._add_folder_path(path)

    def get_folder_list(self):
        return [self.folder_list.item(i).text() for i in range(self.folder_list.count())]

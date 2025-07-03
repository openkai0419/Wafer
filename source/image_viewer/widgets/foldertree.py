
import sys
import os
from PySide6 import QtWidgets, QtGui, QtCore

from ...common import normalize_path, native_sort
from ...profiling import logger, profiler
from ..viewer_settings import main_setting

FOLDER_ICON = QtGui.QIcon.fromTheme("folder")

class LazyFolderTreeModel(QtGui.QStandardItemModel):
    def __init__(self, roots, excluded=None):
        super().__init__()
        self.roots = roots
        self.excluded = set(normalize_path(p) for p in (excluded or []))
        self.setHorizontalHeaderLabels(["Folders"])
        self._build_roots(roots)

    def _build_roots(self, roots):
        self.roots = roots
        for root in roots:
            root = normalize_path(root)
            if root in self.excluded:
                continue
            item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(root) or root)
            item.setData(root, QtCore.Qt.UserRole)
            item.setChild(0, QtGui.QStandardItem())  # dummy
            self.appendRow(item)
        self.sort(0, QtCore.Qt.AscendingOrder)

    def has_subfolders(self, path: str) -> bool:
        try:
            for name in os.listdir(path):
                full_path = normalize_path(os.path.join(path, name))
                if os.path.isdir(full_path) and full_path not in self.excluded:
                    return True
        except Exception as e:
            print(f"Failed to check subfolders in {path}: {e}")
        return False

    def load_children(self, parent_item):
        if parent_item.hasChildren() and parent_item.child(0).data(QtCore.Qt.UserRole):
            return

        parent_item.removeRows(0, parent_item.rowCount())  # dummy削除
        path = parent_item.data(QtCore.Qt.UserRole)

        try:
            for name in native_sort(os.listdir(path)):
                full_path = normalize_path(os.path.join(path, name))
                if not os.path.isdir(full_path) or full_path in self.excluded:
                    continue
                child = QtGui.QStandardItem(FOLDER_ICON, name)
                child.setData(full_path, QtCore.Qt.UserRole)
                if self.has_subfolders(full_path):
                    child.setChild(0, QtGui.QStandardItem())  # dummy は本当に子がいる時だけ
                parent_item.appendRow(child)
        except Exception as e:
            print(f"Failed to read {path}: {e}")


class LazyFolderTreeView(QtWidgets.QTreeView):
    folder_selected = QtCore.Signal()

    def __init__(self, roots, excluded=None):
        super().__init__()
        self.setHeaderHidden(True)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        self.viewport().installEventFilter(self)
        self.collapsed.connect(self.on_collapsed)

        # 状態の保存・復元
        QtCore.QTimer.singleShot(0, self.restore_state)

    def get_selected_paths(self) -> list[str]:
        paths = []
        for index in self.selectionModel().selectedRows():
            path = index.data(QtCore.Qt.UserRole)
            if path:
                paths.append(path)
        return paths

    @property
    def roots(self):
        return self.model_.roots

    def on_expanded(self, index):
        item = self.model_.itemFromIndex(index)
        self.model_.load_children(item)

    def on_collapsed(self, index):
        # 省メモリ化のため閉じたら子供を削除しても良い
        pass

    def _on_item_clicked(self, index):
        self.folder_selected.emit()

    def get_state(self):
        expanded, selected = [], []
        stack = [self.model().index(i, 0) for i in range(self.model().rowCount())]

        while stack:
            idx = stack.pop()
            if not idx.isValid():
                continue
            path = idx.data(QtCore.Qt.UserRole)
            if self.isExpanded(idx):
                expanded.append(path)
            if self.selectionModel().isSelected(idx):
                selected.append(path)
            for i in range(self.model().rowCount(idx)):
                stack.append(self.model().index(i, 0, idx))

        # ファイルや設定に保存してもOK
        return (expanded, selected)

    def save_state(self):
        state = self.get_state()
        main_setting.save_important("tree/state", state)

    def restore_state(self):
        self.set_state(main_setting.get("tree/state", ([], [])))

    def set_state(self, states):
        try:
            expanded, selected = states
        except AttributeError:
            return
        stack = [self.model().index(i, 0) for i in range(self.model().rowCount())]
        selmodel = self.selectionModel()
        selmodel.clearSelection()
        to_select = []

        while stack:
            idx = stack.pop()
            if not idx.isValid():
                continue
            path = idx.data(QtCore.Qt.UserRole)
            if path in expanded:
                self.expand(idx)
                # 子をロードする必要があるのでロード
                self.model_.load_children(self.model_.itemFromIndex(idx))
            if path in selected:
                to_select.append(idx)
            for i in range(self.model().rowCount(idx)):
                stack.append(self.model().index(i, 0, idx))

        for idx in to_select:
            selmodel.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

        if to_select:
            self.setCurrentIndex(to_select[0])
            self.scrollTo(to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)

    def add_root(self, path: str):
        path = normalize_path(path)
        if path in self.model_.excluded:
            print(f"{path} は除外されているので追加できません")
            return
        for i in range(self.model_.rowCount()):
            if self.model_.item(i).data(QtCore.Qt.UserRole) == path:
                print(f"{path} は既に存在します")
                return
        item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(path) or path)
        item.setData(path, QtCore.Qt.UserRole)
        item.setChild(0, QtGui.QStandardItem())  # dummy
        self.model_.appendRow(item)

    def remove_root(self, path: str):
        path = normalize_path(path)
        for i in range(self.model_.rowCount()):
            if self.model_.item(i).data(QtCore.Qt.UserRole) == path:
                self.model_.removeRow(i)
                print(f"{path} をルートから削除しました")
                return
        print(f"{path} はルートに存在しません")

    def add_excluded(self, path: str):
        path = normalize_path(path)
        self.model_.excluded.add(path)
        self.reload_tree()

    def remove_excluded(self, path: str):
        path = normalize_path(path)
        if path in self.model_.excluded:
            self.model_.excluded.remove(path)
            self.reload_tree()

    def reload_tree(self):
        s = self.get_state()
        # ルートの内容を全てリロードする
        roots = []
        for i in range(self.model_.rowCount()):
            path = self.model_.item(i).data(QtCore.Qt.UserRole)
            roots.append(path)
        self.model_.clear()
        self.model_.setHorizontalHeaderLabels(["Folders"])
        self.model_._build_roots(roots)
        self.set_state(s)

    def eventFilter(self, source, event):
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            if event.button() == QtCore.Qt.LeftButton:
                    index = self.indexAt(event.pos())
                    if not index.isValid():
                        self.clearSelection()
                        self.folder_selected.emit()
        return super().eventFilter(source, event)

    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        index = self.indexAt(event.pos())
        self.folder_selected.emit() 
        if not index.isValid():
            return
        path = index.data(QtCore.Qt.UserRole)
        if self.context_menu_builder:
            menu = self.context_menu_builder.build_menu(path)
            menu.exec(event.globalPos())


if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)

    roots = [
        os.path.expanduser("~"),
        os.path.abspath(os.sep),  # /
    ]

    excluded = [
        os.path.expanduser("~/Documents"),
    ]

    w = QtWidgets.QMainWindow()
    tree = LazyFolderTreeView(roots, excluded)
    w.setCentralWidget(tree)

    btns = QtWidgets.QWidget()
    layout = QtWidgets.QHBoxLayout(btns)
    save_btn = QtWidgets.QPushButton("Save State")
    restore_btn = QtWidgets.QPushButton("Restore State")
    layout.addWidget(save_btn)
    layout.addWidget(restore_btn)

    dock = QtWidgets.QDockWidget("Controls")
    dock.setWidget(btns)
    w.addDockWidget(QtCore.Qt.BottomDockWidgetArea, dock)

    save_btn.clicked.connect(tree.save_state)
    restore_btn.clicked.connect(tree.restore_state)

    w.resize(400, 600)
    w.show()
    sys.exit(app.exec())

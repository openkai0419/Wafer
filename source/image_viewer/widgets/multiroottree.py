import os
from PySide6 import QtWidgets, QtGui, QtCore

from ..viewer_settings import main_setting
from ...profiling import init_env
logger, profiler = init_env()


class FolderTreeModel(QtGui.QStandardItemModel):

    def __init__(self, root_paths):
        super().__init__()
        self.root_paths = root_paths
        self.setHorizontalHeaderLabels(["Folders"])
        self.populate()

    @profiler.profile
    def populate(self):
        # 差分構築のため既存ルートのみ初期化
        existing_paths = {self.item(i).data(QtCore.Qt.UserRole): i for i in range(self.rowCount())}
        self.setHorizontalHeaderLabels(["Folders"])

        for root in self.root_paths:
            if root in existing_paths:
                continue
            root_item = QtGui.QStandardItem(QtGui.QIcon.fromTheme("folder"), os.path.basename(root) or root)
            root_item.setData(root, QtCore.Qt.UserRole)
            self.appendRow(root_item)
            self._add_children_iteratively(root_item, root)

    def _add_children_iteratively(self, root_item, root_path):
        stack = [(root_item, root_path)]
        while stack:
            parent_item, path = stack.pop()
            try:
                for name in sorted(os.listdir(path)):
                    abs_path = os.path.join(path, name)
                    if os.path.isdir(abs_path):
                        item = QtGui.QStandardItem(QtGui.QIcon.fromTheme("folder"), name)
                        item.setData(abs_path, QtCore.Qt.UserRole)
                        parent_item.appendRow(item)
                        stack.append((item, abs_path))
            except PermissionError:
                logger.warning(f"PermissionError: {path}")

    @profiler.profile
    def add_root_path(self, new_path):
        if new_path and new_path not in self.root_paths:
            self.root_paths.append(new_path)
            self.populate()

class FolderTreeView(QtWidgets.QTreeView):
    folder_selected = QtCore.Signal(list)

    def __init__(self, root_paths):
        super().__init__()
        self.setHeaderHidden(True)
        self.setMinimumWidth(200)
        self.model_ = FolderTreeModel(root_paths)
        self.setModel(self.model_)
        self.clicked.connect(self._on_item_clicked)
        self.viewport().installEventFilter(self)
        self.restore_state()

    @profiler.profile
    def get_selected(self):
        return [
            index.data(QtCore.Qt.UserRole)
            for index in self.selectedIndexes()
            if index.column() == 0 and index.data(QtCore.Qt.UserRole)
        ]

    def _on_item_clicked(self, index):
        self.folder_selected.emit(self.get_selected())

    @profiler.profile
    def add_path(self, new_path):
        self.model_.add_root_path(new_path)
        self.expandAll()

    @profiler.profile
    def eventFilter(self, source, event):
        if source == self.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clearSelection()
                self.folder_selected.emit(None)
        return super().eventFilter(source, event)

    @profiler.profile
    def save_state(self):
        expanded_paths = []
        model = self.model()

        def collect_expanded(index):
            if not index.isValid() or not self.isExpanded(index):
                return
            path = index.data(QtCore.Qt.UserRole)
            if path:
                expanded_paths.append(path)
            for i in range(model.rowCount(index)):
                child_index = model.index(i, 0, index)
                collect_expanded(child_index)

        for i in range(model.rowCount()):
            index = model.index(i, 0)
            collect_expanded(index)

        selected_paths = self.get_selected()

        print(selected_paths)
        main_setting.save_important("tree/expanded_paths", expanded_paths)
        main_setting.save_important("tree/selected_path", selected_paths)

    @profiler.profile
    def restore_state(self):
        expanded_paths = main_setting.get("tree/expanded_paths", [])
        selected_paths = main_setting.get("tree/selected_path", [])

        def expand_matching(index):
            if not index.isValid():
                return
            path = index.data(QtCore.Qt.UserRole)
            if path in expanded_paths:
                self.expand(index)
            for i in range(self.model().rowCount(index)):
                child_index = self.model().index(i, 0, index)
                expand_matching(child_index)

        for i in range(self.model().rowCount()):
            index = self.model().index(i, 0)
            expand_matching(index)

        if selected_paths:
            def find_indexes_by_paths(paths, index=QtCore.QModelIndex()):
                found = []
                for row in range(self.model().rowCount(index)):
                    child_index = self.model().index(row, 0, index)
                    child_path = child_index.data(QtCore.Qt.UserRole)
                    if child_path in paths:
                        found.append(child_index)
                    found.extend(find_indexes_by_paths(paths, child_index))
                return found

            indexes_to_select = find_indexes_by_paths(selected_paths)
            print(indexes_to_select)
            selection_model = self.selectionModel()
            selection_model.clearSelection()
            for idx in indexes_to_select:
                selection_model.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            if indexes_to_select:
                self.setCurrentIndex(indexes_to_select[0])

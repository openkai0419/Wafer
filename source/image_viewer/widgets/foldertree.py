import os
from PySide6 import QtWidgets, QtGui, QtCore

from ..viewer_settings import main_setting
from ...profiling import init_env
from ..thread import main_thread
logger, profiler = init_env()

def list_subfolders(path):
    try:
        return sorted(
            (e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)),
            key=lambda e: e.name
        )
    except (PermissionError, OSError):
        logger.warning(f"AccessError: {path}")
        return []

class FolderTreeBuilderSignal(QtCore.QObject):
    finished = QtCore.Signal(object)  # List[Dict[str, Dict]]

class FolderTreeBuildTask(QtCore.QRunnable):
    def __init__(self, root_paths):
        super().__init__()
        self.root_paths = root_paths
        self.signal_obj = FolderTreeBuilderSignal()
        self._should_abort = False

    def abort(self):
        self._should_abort = True

    def build_tree_data(self, root_path):
        tree_data = {}
        stack = [(tree_data, root_path)]
        while stack:
            if self._should_abort:
                return {}
            parent_dict, path = stack.pop()
            sub = {}
            parent_dict[path] = sub
            for entry in list_subfolders(path):
                stack.append((sub, entry.path))
        return tree_data

    def run(self):
        result = [self.build_tree_data(root) for root in self.root_paths if not self._should_abort]
        self.signal_obj.finished.emit(result)

class FolderTreeModel(QtGui.QStandardItemModel):
    def __init__(self, root_paths):
        super().__init__()
        self.root_paths = root_paths
        self.setHorizontalHeaderLabels(["Folders"])
        self.populate()

    @profiler.profile
    def populate(self):
        existing_paths = {self.item(i).data(QtCore.Qt.UserRole): i for i in range(self.rowCount())}
        for root in self.root_paths:
            if root in existing_paths:
                continue
            self.add_new_root_if_missing(root)

    def add_new_root_if_missing(self, root, insert_at_top=False):
        root_item = QtGui.QStandardItem(QtGui.QIcon.fromTheme("folder"), os.path.basename(root) or root)
        root_item.setData(root, QtCore.Qt.UserRole)
        if insert_at_top:
            self.insertRow(0, root_item)
        else:
            self.appendRow(root_item)
        self._add_children_iteratively(root_item, root)

    def _add_children_iteratively(self, root_item, root_path):
        stack = [(root_item, root_path)]
        while stack:
            parent_item, path = stack.pop()
            for entry in list_subfolders(path):
                item = QtGui.QStandardItem(QtGui.QIcon.fromTheme("folder"), entry.name)
                item.setData(entry.path, QtCore.Qt.UserRole)
                parent_item.appendRow(item)
                item.sortChildren(0)
                stack.append((item, entry.path))

    @profiler.profile
    def add_root_path(self, new_path):
        if new_path and new_path not in self.root_paths:
            self.root_paths.append(new_path)
            self.add_new_root_if_missing(new_path)
        
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
        self._reload_task_running = False
        self._reload_task = None
        self._path_to_item = {}
        self.restore_state()

        self.context_menu_builder=None

    def set_root_paths(self, new_paths: list[str], reset_state=True):
        self.model_.root_paths = new_paths[:]
        a, b = self.get_state()
        self.reload_async()
        if reset_state:
            self.set_state([], []) 
        else:
            self.set_state(a, b)
        self.model_.sort(0)

    def cancel_reload(self):
        if self._reload_task:
            self._reload_task.abort()

    def reload_async(self):
        self.cancel_reload()
        self._reload_task_running = True
        self._reload_task = FolderTreeBuildTask(self.model_.root_paths)
        self._reload_task.signal_obj.finished.connect(self._on_reload_complete)
        main_thread.start(self._reload_task)

    def _on_reload_complete(self, tree_data_list):
        a, b = self.get_state()
        self.model_.clear()
        self.model_.setHorizontalHeaderLabels(["Folders"])
        self._path_to_item = {}

        for tree_data in tree_data_list:
            for root_path, children in tree_data.items():
                item = self.build_items_recursive(root_path, children, self._path_to_item)
                self.model_.appendRow(item)

        self.set_state(a, b)
        self._reload_task_running = False

    def build_items_recursive(self, path, children_dict, lookup: dict):
        name = os.path.basename(path) or path
        item = QtGui.QStandardItem(QtGui.QIcon.fromTheme("folder"), name)
        item.setData(path, QtCore.Qt.UserRole)
        lookup[path] = item
        for child_path, subchildren in sorted(children_dict.items()):
            child_item = self.build_items_recursive(child_path, subchildren, lookup)
            item.appendRow(child_item)
        item.sortChildren(0)
        return item

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
        self.set_state(*self.get_state())
        self.model_.sort(0)

    @profiler.profile
    def eventFilter(self, source, event):
        if source == self.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clearSelection()
                self.folder_selected.emit(None)
        return super().eventFilter(source, event)

    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return

        path = index.data(QtCore.Qt.UserRole)
        if self.context_menu_builder:
            menu = self.context_menu_builder.build_menu(path)
            menu.exec(event.globalPos())

    @profiler.profile
    def get_state(self):
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
        return selected_paths, expanded_paths

    @profiler.profile
    def save_state(self):
        selected_paths, expanded_paths = self.get_state()
        main_setting.save_important("tree/expanded_paths", expanded_paths)
        main_setting.save_important("tree/selected_path", selected_paths)

    @profiler.profile
    def set_state(self, selected_paths, expanded_paths):
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
            indexes_to_select = [
                self.model_.indexFromItem(self._path_to_item[p])
                for p in selected_paths if p in self._path_to_item
            ]
            selection_model = self.selectionModel()
            selection_model.clearSelection()
            for idx in indexes_to_select:
                selection_model.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            if indexes_to_select:
                self.setCurrentIndex(indexes_to_select[0])
                self.scrollTo(indexes_to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)
        self.model_.sort(0)

    @profiler.profile
    def restore_state(self):
        expanded_paths = main_setting.get("tree/expanded_paths", [])
        selected_paths = main_setting.get("tree/selected_path", [])
        self.set_state(selected_paths, expanded_paths)

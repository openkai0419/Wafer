import os
import hashlib
from PySide6 import QtWidgets, QtGui, QtCore
from typing import List, Tuple

from ..viewer_settings import main_setting
from ...profiling import init_env
from ..thread import main_thread
from ...common import normalize_path
logger, profiler = init_env()

FOLDER_ICON = QtGui.QIcon.fromTheme("folder")

def is_path_excluded(path: str, excluded_set: set) -> bool:
    path = normalize_path(path)
    for excl in excluded_set:
        if path == excl or path.startswith(os.path.join(excl, '')):
            return True
    return False

def list_subfolders(path):
    try:
        return sorted(
            (e for e in os.scandir(path) if e.is_dir(follow_symlinks=False)),
            key=lambda e: e.name
        )
    except (PermissionError, OSError):
        logger.warning(f"AccessError: {path}")
        return []

def hash_tree(tree: dict) -> str:
    return hashlib.sha256(json.dumps(tree, sort_keys=True).encode()).hexdigest()

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

    @profiler.profile
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

    @profiler.profile
    def run(self):
        result = [self.build_tree_data(root) for root in self.root_paths if not self._should_abort]
        self.signal_obj.finished.emit(result)

class FolderTreeModel(QtGui.QStandardItemModel):
    def __init__(self, root_paths):
        super().__init__()
        self.root_paths = root_paths
        self.excluded_paths = set()
        self.setHorizontalHeaderLabels(["Folders"])
        self.populate()

    @profiler.profile
    def populate(self):
        existing_paths = {self.item(i).data(QtCore.Qt.UserRole): i for i in range(self.rowCount())}
        for root in self.root_paths:
            if root in existing_paths:
                continue
            self.add_new_root_if_missing(root)

    @profiler.profile
    def add_new_root_if_missing(self, root, insert_at_top=False, lookup=None):
        root_item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(root) or root)
        root_item.setData(root, QtCore.Qt.UserRole)
        if lookup is not None:
            lookup[root] = root_item
        if insert_at_top:
            self.insertRow(0, root_item)
        else:
            self.appendRow(root_item)
        self._add_children_iteratively(root_item, root, lookup)

    @profiler.profile
    def _add_children_iteratively(self, root_item, root_path, lookup=None):
        stack = [(root_item, root_path)]
        while stack:
            parent_item, path = stack.pop()
            children = list_subfolders(path)
            for entry in sorted(children, key=lambda e: e.name):
                if is_path_excluded(entry.path, self.excluded_paths):
                    continue  # ← 除外処理
                item = QtGui.QStandardItem(FOLDER_ICON, entry.name)
                item.setData(entry.path, QtCore.Qt.UserRole)
                parent_item.appendRow(item)
                if lookup is not None:
                    lookup[entry.path] = item
                stack.append((item, entry.path))

    @profiler.profile
    def add_root_path(self, new_path, lookup=None):
        if new_path and new_path not in self.root_paths:
            self.root_paths.append(new_path)
            self.add_new_root_if_missing(new_path, lookup=lookup)

    @profiler.profile
    def remove_root_path(self, target_path: str):
        if target_path not in self.root_paths:
            return
        self.root_paths.remove(target_path)
        for i in range(self.rowCount()):
            item = self.item(i)
            if item.data(QtCore.Qt.UserRole) == target_path:
                self.removeRow(i)
                break

    @profiler.profile
    def build_items_from_tree_data(self, root_path: str, children_dict: dict, lookup: dict) -> QtGui.QStandardItem:
        name = os.path.basename(root_path) or root_path
        item = QtGui.QStandardItem(FOLDER_ICON, name)
        item.setData(root_path, QtCore.Qt.UserRole)
        lookup[root_path] = item
        for child_path, subchildren in sorted(children_dict.items()):
            if is_path_excluded(child_path, self.excluded_paths):
                continue
            child_item = self.build_items_from_tree_data(child_path, subchildren, lookup)
            item.appendRow(child_item)
        return item

class FolderTreeView(QtWidgets.QTreeView):
    folder_selected = QtCore.Signal()

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
        self._tree_cache = {}
        self._path_to_item = {}
        self.restore_state()
        self.context_menu_builder = None
        self.model_.excluded_paths = set()

    @property
    def excluded_paths(self):
        return self.model_.excluded_paths

    def set_excluded_paths(self, paths: List[str]):
        logger.debug(paths)
        self.model_.excluded_paths = set(paths)
        self.reload_async()

    def is_root_path(self, path):
        return path in self.root_paths

    @property
    def root_paths(self):
        return self.model_.root_paths

    @profiler.profile
    def set_root_paths(self, new_paths: List[str], reset_state=True):
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

    @profiler.profile
    def reload_async(self):
        if self._reload_task_running:
            return
        self.cancel_reload()
        self._reload_task_running = True
        self._reload_task = FolderTreeBuildTask(self.model_.root_paths)
        self._reload_task.signal_obj.finished.connect(self._on_reload_complete)
        main_thread.start(self._reload_task)

    @profiler.profile
    def _on_reload_complete(self, tree_data_list):
        a, b = self.get_state()
        self.model_.clear()
        self.model_.setHorizontalHeaderLabels(["Folders"])
        self._path_to_item = {}

        for tree_data in tree_data_list:
            for root_path, children in tree_data.items():
                h_new = hash_tree(children)
                h_old = hash_tree(self._tree_cache.get(root_path, {}))
                if h_new != h_old:
                    item = self.model_.build_items_from_tree_data(root_path, children, self._path_to_item)
                    self.model_.appendRow(item)
                    self._tree_cache[root_path] = children

        QtCore.QTimer.singleShot(0, lambda: self.set_state(a, b))
        self._reload_task_running = False
        self.model_.sort(0)

    @profiler.profile
    def get_selected(self) -> List[str]:
        selected = []
        for index in self.selectedIndexes():
            if index.column() != 0:
                continue
            path = index.data(QtCore.Qt.UserRole)
            if path:
                selected.append(path)
        return selected

    def _on_item_clicked(self, index):
        self.folder_selected.emit()

    @profiler.profile
    def add_path(self, new_path: str):
        self.model_.add_root_path(new_path, lookup=self._path_to_item)
        self.set_state(*self.get_state())
        self.model_.sort(0)

    @profiler.profile
    def remove_path(self, path: str):
        self.model_.remove_root_path(path)
        self.set_state(*self.get_state())
        self.model_.sort(0)

    def eventFilter(self, source, event):
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            index = self.indexAt(event.pos())
            if not index.isValid():
                self.clearSelection()
                self.folder_selected.emit()
        return super().eventFilter(source, event)

    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder

    @profiler.profile
    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        index = self.indexAt(event.pos())
        if not index.isValid():
            return
        path = index.data(QtCore.Qt.UserRole)
        if self.context_menu_builder:
            menu = self.context_menu_builder.build_menu(path)
            menu.exec(event.globalPos())

    @profiler.profile
    def get_state(self) -> Tuple[List[str], List[str]]:
        expanded_paths = []
        selected_paths = self.get_selected()
        model = self.model()
        stack = [model.index(i, 0) for i in range(model.rowCount())]

        while stack:
            index = stack.pop()
            if not index.isValid():
                continue
            if self.isExpanded(index):
                path = index.data(QtCore.Qt.UserRole)
                if path:
                    expanded_paths.append(path)
            # 末尾に子供をまとめて push（再帰削減）
            stack.extend(
                model.index(i, 0, index) for i in range(model.rowCount(index))
            )

        return selected_paths, expanded_paths

    def save_state(self):
        selected_paths, expanded_paths = self.get_state()
        main_setting.save_important("tree/expanded_paths", expanded_paths)
        main_setting.save_important("tree/selected_path", selected_paths)

    @profiler.profile
    def set_state(self, selected_paths: List[str], expanded_paths: List[str]):
        expanded_set = set(expanded_paths)
        selection_set = set(selected_paths)
        selection_model = self.selectionModel()
        selection_model.clearSelection()
        to_select = []

        model = self.model()
        stack = [model.index(i, 0) for i in range(model.rowCount())]

        while stack:
            index = stack.pop()
            if not index.isValid():
                continue
            path = index.data(QtCore.Qt.UserRole)
            if path:
                if path in expanded_set:
                    self.expand(index)
                if path in selection_set and path in self._path_to_item:
                    item = self._path_to_item[path]
                    to_select.append(self.model_.indexFromItem(item))
            stack.extend(model.index(i, 0, index) for i in range(model.rowCount(index)))

        for idx in to_select:
            selection_model.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)

        if to_select:
            self.setCurrentIndex(to_select[0])
            self.scrollTo(to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)

        self.model_.sort(0)

    def restore_state(self):
        expanded_paths = main_setting.get("tree/expanded_paths", [])
        selected_paths = main_setting.get("tree/selected_path", [])
        QtCore.QTimer.singleShot(0, lambda: self.set_state(selected_paths, expanded_paths))
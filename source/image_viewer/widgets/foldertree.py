
import sys
import os
from PySide6 import QtWidgets, QtGui, QtCore

from ...funcs import normalize_path, native_sort
from ...profiling import logger, profiler
from ..viewer_settings import main_setting

FOLDER_ICON = QtGui.QIcon.fromTheme("folder")

class LazyFolderTreeModel(QtGui.QStandardItemModel):
    def __init__(self, roots, excluded=None):
        super().__init__()
        self.roots = roots
        self.excluded = set(normalize_path(p) for p in (excluded or []))
        self.setHorizontalHeaderLabels(["Folders"])
        self.path_item_map = {}  # ★ 追加

    def clear_cache(self):
        self.path_item_map.clear()

    def _add_item(self, path, item):
        path = normalize_path(path)
        self.path_item_map[path] = item

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
            self._add_item(root, item)  # ★

        self.sort(0, QtCore.Qt.AscendingOrder)

    def has_subfolders(self, path: str) -> bool:
        try:
            for name in os.listdir(path):
                full_path = normalize_path(os.path.join(path, name))
                if os.path.isdir(full_path) and full_path not in self.excluded:
                    return True
        except Exception as e:
            logger.debug(f"Failed to check subfolders in {path}: {e}")
        return False

    def load_children(self, parent_item):
        if parent_item.hasChildren() and parent_item.child(0).data(QtCore.Qt.UserRole):
            return
        parent_item.removeRows(0, parent_item.rowCount())  # remove dummy
        path = parent_item.data(QtCore.Qt.UserRole)

        try:
            for name in native_sort(os.listdir(path)):
                full_path = normalize_path(os.path.join(path, name))
                if not os.path.isdir(full_path) or full_path in self.excluded:
                    continue
                child = QtGui.QStandardItem(FOLDER_ICON, name)
                child.setData(full_path, QtCore.Qt.UserRole)
                if self.has_subfolders(full_path):
                    child.setChild(0, QtGui.QStandardItem())  # dummy
                parent_item.appendRow(child)
                self._add_item(full_path, child)  # ★
        except Exception as e:
            logger.debug(f"Failed to read {path}: {e}")

    def find_item_by_path(self, path: str) -> QtGui.QStandardItem | None:
        path = normalize_path(path)
        item = self.path_item_map.get(path)
        if item:
            return item

        # キャッシュにない場合は探索（従来通り）
        for i in range(self.rowCount()):
            root_item = self.item(i)
            root_path = normalize_path(root_item.data(QtCore.Qt.UserRole))
            if not path.startswith(root_path):
                continue

            item = root_item
            current_path = root_path
            self.load_children(item)

            try:
                rel_parts = os.path.relpath(path, root_path).split(os.sep)
            except ValueError:
                continue

            for part in rel_parts:
                current_path = normalize_path(os.path.join(current_path, part))
                match = None
                for j in range(item.rowCount()):
                    child = item.child(j)
                    if normalize_path(child.data(QtCore.Qt.UserRole)) == current_path:
                        match = child
                        break
                if match is None:
                    return None
                item = match
                self.load_children(item)

            self.path_item_map[path] = item  # ★ 新たに発見したらキャッシュに追加
            return item
        return None

    def find_index_by_path(self, path: str) -> QtCore.QModelIndex | None:
        item = self.find_item_by_path(path)
        return self.indexFromItem(item) if item else None

class LazyFolderTreeView(QtWidgets.QTreeView):
    folder_selected = QtCore.Signal()

    def __init__(self, roots=None, excluded=None):
        super().__init__()
        self.setHeaderHidden(True)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        self.viewport().installEventFilter(self)
        self.collapsed.connect(self.on_collapsed)

    def get_selected_paths(self) -> list[str]:
        paths = []
        for index in self.selectionModel().selectedRows():
            path = index.data(QtCore.Qt.UserRole)
            if path:
                paths.append(path)
        return paths

    def set(self, roots: list[str], excluded: list[str] = None):
        # normalize
        roots = [normalize_path(r) for r in roots]
        excluded = set(normalize_path(e) for e in (excluded or []))
        
        # Clear model and rebuild
        self.model_.clear()
        self.model_.roots = roots
        self.model_.excluded = excluded
        self.model_.setHorizontalHeaderLabels(["Folders"])
        self.model_._build_roots(roots)

    @property
    def roots(self):
        return self.model_.roots

    def on_expanded(self, index):
        item = self.model_.itemFromIndex(index)
        self.model_.load_children(item)

    def on_collapsed(self, index):
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

        return (expanded, selected)

    def save_state(self, name):
        state = self.get_state()
        main_setting.save_important(f"tree/state/{name}", state)

    def restore_state(self, name):
        self.set_state(main_setting.get(f"tree/state/{name}", ([], [])))

    def set_state(self, states):
        try:
            expanded, selected = states
        except AttributeError:
            return
        stack = [self.model().index(i, 0) for i in range(self.model().rowCount())]
        selmodel = self.selectionModel()
        selmodel.clearSelection()
        to_select = []
        logger.info(expanded)
        logger.info(selected)

        while stack:
            idx = stack.pop()
            if not idx.isValid():
                continue
            path = idx.data(QtCore.Qt.UserRole)
            if path in expanded:
                self.expand(idx)
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

    def expand_and_select_path(self, path: str):
        path = normalize_path(path)
        index = self.model_.find_index_by_path(path)

        if not index.isValid():
            return

        self.expand(index)
        sel_model = self.selectionModel()
        sel_model.clearSelection()
        sel_model.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        self.setCurrentIndex(index)
        self.scrollTo(index, QtWidgets.QAbstractItemView.PositionAtCenter)
        self.folder_selected.emit()

    def add_root(self, path: str):
        path = normalize_path(path)
        if path in self.model_.excluded:
            return
        for i in range(self.model_.rowCount()):
            if self.model_.item(i).data(QtCore.Qt.UserRole) == path:
                return
        item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(path) or path)
        item.setData(path, QtCore.Qt.UserRole)
        item.setChild(0, QtGui.QStandardItem())  # dummy
        self.model_.roots.append(path)
        self.model_.appendRow(item)
        self.model_.sort(0, QtCore.Qt.AscendingOrder)

    def remove_root(self, path: str):
        path = normalize_path(path)
        for i in range(self.model_.rowCount()):
            if self.model_.item(i).data(QtCore.Qt.UserRole) == path:
                self.model_.removeRow(i)
                return

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
        roots = [self.model_.item(i).data(QtCore.Qt.UserRole) for i in range(self.model_.rowCount())]
        self.model_.clear()
        self.model_.path_item_map.clear()  # ★ キャッシュもクリア
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

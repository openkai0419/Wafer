import os
from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import normalize_path
from ...common.profiling import logger, profiler
from ..viewer_settings import main_setting

FOLDER_ICON = QtGui.QIcon.fromTheme('folder')
USER_ROLE_PATH = QtCore.Qt.UserRole

@profiler.profile
def create_folder_item(path):
    item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(path) or path)
    item.setData(path, USER_ROLE_PATH)
    return item

@profiler.profile
def iter_root_items(model):
    for i in range(model.rowCount()):
        yield model.item(i)

class LazyFolderTreeModel(QtGui.QStandardItemModel):

    def __init__(self, roots, excluded=None):
        super().__init__()
        self.roots = roots
        self.excluded = set((normalize_path(p) for p in excluded or []))
        self.setHorizontalHeaderLabels(['Folders'])
        self.path_item_map = {}
        self.path_item_trie = {}

    @profiler.profile
    def clear_cache(self):
        self.path_item_map.clear()
        self.path_item_trie.clear()

    @profiler.profile
    def _remove_from_trie(self, path):
        parts = path.split(os.sep)
        node = self.path_item_trie
        stack = []
        for part in parts:
            if part not in node:
                return
            stack.append((node, part))
            node = node[part]
        if '__item__' in node:
            del node['__item__']
        for parent, key in reversed(stack):
            if not parent[key]:
                del parent[key]
            else:
                break

    @profiler.profile
    def _add_item(self, path, item):
        norm_path = normalize_path(path)
        self.path_item_map[norm_path] = item
        self._insert_into_trie(norm_path, item)

    @profiler.profile
    def _insert_into_trie(self, path, item):
        parts = path.split(os.sep)
        node = self.path_item_trie
        for part in parts:
            node = node.setdefault(part, {})
        node['__item__'] = item

    @profiler.profile
    def _get_from_trie(self, path):
        parts = path.split(os.sep)
        node = self.path_item_trie
        for part in parts:
            node = node.get(part)
            if node is None:
                return None
        return node.get('__item__')

    @profiler.profile
    def _build_roots(self, roots):
        self.roots = roots
        for root in roots:
            root = normalize_path(root)
            if root in self.excluded:
                continue
            item = create_folder_item(root)
            if self.has_subfolders(root):
                item.setChild(0, QtGui.QStandardItem())
            self.appendRow(item)
            self._add_item(root, item)
        self.sort(0, QtCore.Qt.AscendingOrder)

    @profiler.profile
    def has_subfolders(self, path):
        try:
            with os.scandir(path) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        full_path = normalize_path(entry.path)
                        if full_path not in self.excluded:
                            return True
            return False
        except Exception as e:
            logger.debug(f'Failed to quick-check entries in {path}: {e}')
            return False

    @profiler.profile
    def load_children(self, parent_item):
        if parent_item.hasChildren() and parent_item.child(0).data(USER_ROLE_PATH):
            return
        parent_item.removeRows(0, parent_item.rowCount())
        path = parent_item.data(USER_ROLE_PATH)
        try:
            for entry in sorted(os.scandir(path), key=lambda e: e.name.lower()):
                if not entry.is_dir(follow_symlinks=False):
                    continue
                full_path = normalize_path(entry.path)
                if full_path in self.excluded:
                    continue
                child = create_folder_item(full_path)
                if self.has_subfolders(full_path):
                    child.setChild(0, QtGui.QStandardItem())
                parent_item.appendRow(child)
                self._add_item(full_path, child)
        except Exception as e:
            logger.debug(f'Failed to read {path}: {e}')

    @profiler.profile
    def _is_valid_item(self, item):
        try:
            return item is not None and item.model() is not None
        except RuntimeError:
            return False

    @profiler.profile
    def find_item_by_path(self, path):
        path = normalize_path(path)
        item = self.path_item_map.get(path)
        if self._is_valid_item(item):
            return item
        elif item:
            self.path_item_map.pop(path, None)
        trie_item = self._get_from_trie(path)
        if self._is_valid_item(trie_item):
            return trie_item
        self._remove_from_trie(path)
        for root_item in iter_root_items(self):
            root_path = normalize_path(root_item.data(USER_ROLE_PATH))
            if not path.startswith(root_path):
                continue
            item = root_item
            current_path = root_path
            self.load_children(item)
            try:
                rel = os.path.relpath(path, root_path)
            except ValueError:
                continue
            if rel == '.' or rel == '':
                self._add_item(path, item)
                return item
            rel_parts = rel.split(os.sep)
            for part in rel_parts:
                current_path = normalize_path(os.path.join(current_path, part))
                match = None
                for j in range(item.rowCount()):
                    child = item.child(j)
                    if normalize_path(child.data(USER_ROLE_PATH)) == current_path:
                        match = child
                        break
                if match is None:
                    return None
                item = match
                self.load_children(item)
            self._add_item(path, item)
            return item
        return None


    @profiler.profile
    def find_index_by_path(self, path):
        item = self.find_item_by_path(path)
        return self.indexFromItem(item) if item else None

class LazyFolderTreeView(QtWidgets.QTreeView):
    folder_selected = QtCore.Signal()

    def __init__(self, roots=None, excluded=None):
        super().__init__()
        self.setStyleSheet('\n        QTreeView::item:selected {\n            background-color: rgb(59, 128, 255);\n        }\n        ')
        self.setHeaderHidden(True)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        self.viewport().installEventFilter(self)
        self.collapsed.connect(self.on_collapsed)
        self.context_menu_builder = None

    @profiler.profile
    def get_selected_paths(self):
        return [i.data(USER_ROLE_PATH) for i in self.selectionModel().selectedRows() if i.data(USER_ROLE_PATH)]

    def set(self, roots, excluded=None):
        roots = [normalize_path(r) for r in roots]
        excluded = set((normalize_path(e) for e in excluded or []))
        self.model_.clear()
        self.model_.roots = roots
        self.model_.excluded = excluded
        self.model_.setHorizontalHeaderLabels(['Folders'])
        self.model_._build_roots(roots)

    @property
    def roots(self):
        return self.model_.roots

    @profiler.profile
    def expand_path(self, path):
        path = normalize_path(path)
        parts = path.split(os.sep)
        current_item = None
        current_path = ''
        for part in parts:
            current_path = normalize_path(os.path.join(current_path, part))
            item = self.model_.find_item_by_path(current_path)
            if not self.model_._is_valid_item(item):
                return None
            index = self.model_.indexFromItem(item)
            if not index.isValid():
                return None
            self.expand(index)
            self.model_.load_children(item)
            current_item = item
        return self.model_.indexFromItem(current_item) if current_item else None

    @profiler.profile
    def on_expanded(self, index):
        item = self.model_.itemFromIndex(index)
        self.model_.load_children(item)

    def on_collapsed(self, index):
        pass

    def _on_item_clicked(self, index):
        self.folder_selected.emit()

    @profiler.profile
    def get_state(self):
        expanded, selected = ([], [])
        stack = [self.model().index(i, 0) for i in range(self.model().rowCount())]
        while stack:
            idx = stack.pop()
            if not idx.isValid():
                continue
            path = idx.data(USER_ROLE_PATH)
            if self.isExpanded(idx):
                expanded.append(path)
            if self.selectionModel().isSelected(idx):
                selected.append(path)
            for i in range(self.model().rowCount(idx)):
                stack.append(self.model().index(i, 0, idx))
        return (expanded, selected)

    def save_state(self, name):
        main_setting.save_important(f'tree/state/{name}', self.get_state())

    def restore_state(self, name):
        self.set_state(main_setting.get(f'tree/state/{name}', ([], [])))

    @profiler.profile
    def set_state(self, states):
        try:
            expanded, selected = states
        except Exception:
            return
        selmodel = self.selectionModel()
        selmodel.clearSelection()
        to_select = []
        for path in expanded:
            index = self.expand_path(path)
            if index and index.isValid():
                self.model_.load_children(self.model_.itemFromIndex(index))
        for path in selected:
            index = self.model_.find_index_by_path(path)
            if index and index.isValid():
                to_select.append(index)
        for idx in to_select:
            selmodel.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        if to_select:
            self.setCurrentIndex(to_select[0])
            self.scrollTo(to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)

    @profiler.profile
    def expand_and_select_path(self, path):
        index = self.expand_path(path)
        if index and index.isValid():
            sel_model = self.selectionModel()
            sel_model.clearSelection()
            sel_model.select(index, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
            self.setCurrentIndex(index)
            QtCore.QTimer.singleShot(0, lambda: self.scrollTo(index, QtWidgets.QAbstractItemView.PositionAtCenter))
            self.folder_selected.emit()

    @profiler.profile
    def add_root(self, path):
        path = normalize_path(path)
        if path in self.model_.excluded:
            return
        for item in iter_root_items(self.model_):
            if item.data(USER_ROLE_PATH) == path:
                return
        item = create_folder_item(path)
        if self.model_.has_subfolders(path):
            item.setChild(0, QtGui.QStandardItem())
        self.model_.roots.append(path)
        self.model_.appendRow(item)
        self.model_._add_item(path, item)
        self.model_.sort(0, QtCore.Qt.AscendingOrder)

    @profiler.profile
    def remove_root(self, path):
        path = normalize_path(path)
        removed = False
        for i in range(self.model_.rowCount()):
            if self.model_.item(i).data(USER_ROLE_PATH) == path:
                self.model_.removeRow(i)
                removed = True
                break
        if removed:
            try:
                self.model_.roots.remove(path)
            except ValueError:
                pass
            self.reload_tree()

    @profiler.profile
    def add_excluded(self, path):
        self.model_.excluded.add(normalize_path(path))
        self.reload_tree()

    @profiler.profile
    def remove_excluded(self, path):
        path = normalize_path(path)
        if path in self.model_.excluded:
            self.model_.excluded.remove(path)
            self.reload_tree()

    @profiler.profile
    def reload_tree(self):
        state = self.get_state()
        roots = [item.data(USER_ROLE_PATH) for item in iter_root_items(self.model_)]
        self.model_.clear()
        self.model_.clear_cache()
        self.model_.setHorizontalHeaderLabels(['Folders'])
        self.model_._build_roots(roots)
        self.set_state(state)

    def eventFilter(self, source, event):
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            if event.button() == QtCore.Qt.LeftButton:
                index = self.indexAt(event.pos())
                if not index.isValid():
                    self.clearSelection()
                    self.folder_selected.emit()
        return super().eventFilter(source, event)

    @profiler.profile
    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder

    def contextMenuEvent(self, event):
        index = self.indexAt(event.pos())
        self.folder_selected.emit()
        if not index.isValid():
            return
        path = index.data(USER_ROLE_PATH)
        if self.context_menu_builder:
            menu = self.context_menu_builder.build_menu(path)
            menu.exec(event.globalPos())

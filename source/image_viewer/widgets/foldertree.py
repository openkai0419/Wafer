import os
from natsort import natsorted
from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import normalize_path
from ...common.profiling import logger, profiler
from ..viewer_settings import main_setting
from ...actions.bridge import Kit
from ...qt.dialog import ConfirmDialog

FOLDER_ICON = QtGui.QIcon.fromTheme('folder')
USER_ROLE_PATH = QtCore.Qt.UserRole

@profiler.profile
def create_folder_item(path):
    item = QtGui.QStandardItem(FOLDER_ICON, os.path.basename(path) or path)
    item.setData(path, USER_ROLE_PATH)
    item.setEditable(True)
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
        self._mime_type = 'application/x-foldertree-paths'

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
    def _remove_from_maps_recursive(self, base_path):
        base_path = normalize_path(base_path)
        self.path_item_map.pop(base_path, None)
        self._remove_from_trie(base_path)
        to_remove = [p for p in list(self.path_item_map.keys()) if p.startswith(base_path + os.sep)]
        for p in to_remove:
            self.path_item_map.pop(p, None)
            self._remove_from_trie(p)

    @profiler.profile
    def _update_item_path_recursive(self, item, old_base, new_base):
        old_item_path = normalize_path(item.data(USER_ROLE_PATH))
        if not old_item_path.startswith(old_base):
            return
        relative = os.path.relpath(old_item_path, old_base)
        new_item_path = normalize_path(os.path.join(new_base, '.' if relative == '.' else relative))
        self.path_item_map.pop(old_item_path, None)
        self._remove_from_trie(old_item_path)
        item.setData(new_item_path, USER_ROLE_PATH)
        self._add_item(new_item_path, item)
        for i in range(item.rowCount()):
            child = item.child(i)
            if child and child.data(USER_ROLE_PATH):
                self._update_item_path_recursive(child, old_base, new_base)

    @profiler.profile
    def _rename_item(self, item, new_name):
        old_path = normalize_path(item.data(USER_ROLE_PATH))
        parent_item = item.parent() or self.invisibleRootItem()
        parent_path = None
        parent_path = normalize_path(os.path.dirname(old_path)) if parent_item is self.invisibleRootItem() else normalize_path(parent_item.data(USER_ROLE_PATH))
        dest_path = normalize_path(os.path.join(parent_path, new_name))
        if dest_path == old_path:
            return True
        try:
            import shutil
            shutil.move(old_path, dest_path)
        except Exception as e:
            logger.debug(f'Failed to rename {old_path} -> {dest_path}: {e}')
            return False
        item.setText(os.path.basename(dest_path) or dest_path)
        self._update_item_path_recursive(item, old_path, dest_path)
        if parent_item is self.invisibleRootItem():
            try:
                idx = self.roots.index(old_path)
                self.roots[idx] = dest_path
            except ValueError:
                pass
        return True

    @profiler.profile
    def _move_item(self, item, new_parent_item):
        old_path = normalize_path(item.data(USER_ROLE_PATH))
        new_parent_path = normalize_path(new_parent_item.data(USER_ROLE_PATH)) if new_parent_item is not self.invisibleRootItem() else None
        if new_parent_item is self.invisibleRootItem():
            return False
        dest_path = normalize_path(os.path.join(new_parent_path, os.path.basename(old_path)))
        if dest_path == old_path:
            return True
        try:
            import shutil
            shutil.move(old_path, dest_path)
        except Exception as e:
            logger.debug(f'Failed to move {old_path} -> {dest_path}: {e}')
            return False
        src_parent = item.parent() or self.invisibleRootItem()
        row = item.row()
        taken = src_parent.takeRow(row)
        if not taken:
            return False
        if not new_parent_item.hasChildren() or (new_parent_item.rowCount() == 1 and not new_parent_item.child(0).data(USER_ROLE_PATH)):
            new_parent_item.removeRows(0, new_parent_item.rowCount())
        new_parent_item.appendRow(taken)
        moved_item = new_parent_item.child(new_parent_item.rowCount() - 1)
        self._update_item_path_recursive(moved_item, old_path, dest_path)
        return True

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

    def flags(self, index):
        default = super().flags(index)
        if not index.isValid():
            return default
        return default | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled

    def supportedDropActions(self):
        return QtCore.Qt.MoveAction

    def mimeTypes(self):
        return [self._mime_type]

    def mimeData(self, indexes):
        mime = QtCore.QMimeData()
        paths = []
        seen_rows = set()
        for idx in indexes:
            if idx.column() != 0:
                continue
            if idx.row() in seen_rows:
                continue
            seen_rows.add(idx.row())
            p = idx.data(USER_ROLE_PATH)
            if p:
                paths.append(p)
        mime.setData(self._mime_type, '\n'.join(paths).encode('utf-8'))
        return mime

    def canDropMimeData(self, data, action, row, column, parent):
        if action != QtCore.Qt.MoveAction:
            return False
        if not data or not data.hasFormat(self._mime_type):
            return False
        if row != -1 or not parent.isValid():
            return False
        parent_item = self.itemFromIndex(parent)
        if parent_item is None:
            return False
        target_path = parent_item.data(USER_ROLE_PATH)
        if not target_path or target_path in self.excluded:
            return False
        try:
            src_paths = bytes(data.data(self._mime_type)).decode('utf-8').split('\n')
        except Exception:
            return False
        target_norm = normalize_path(target_path)
        for src in src_paths:
            src_norm = normalize_path(src)
            if src_norm == target_norm:
                return False
            if target_norm.startswith(src_norm + os.sep):
                return False
        return True

    @profiler.profile
    def dropMimeData(self, data, action, row, column, parent):
        if action != QtCore.Qt.MoveAction:
            return False
        if not data.hasFormat(self._mime_type):
            return False
        if row != -1 or not parent.isValid():
            return False
        parent_item = self.itemFromIndex(parent) if parent.isValid() else None
        if parent_item is None:
            return False
        target_path = parent_item.data(USER_ROLE_PATH)
        if not target_path or target_path in self.excluded:
            return False
        if not self._confirm_move(data, target_path):
            return False
        moved_any = False
        handled_noop = False
        try:
            src_paths = data.data(self._mime_type).data().decode('utf-8').split('\n')
        except Exception:
            return False
        for src in src_paths:
            src_item = self.find_item_by_path(src)
            if not self._is_valid_item(src_item):
                continue
            if normalize_path(src) == normalize_path(target_path):
                continue
            if normalize_path(target_path).startswith(normalize_path(src) + os.sep):
                continue
            src_parent = normalize_path(os.path.dirname(normalize_path(src)))
            if src_parent == normalize_path(target_path):
                handled_noop = True
                continue
            moved_any = self._move_item(src_item, parent_item) or moved_any
        if moved_any:
            self.sort(0, QtCore.Qt.AscendingOrder)
        return moved_any or handled_noop

    def _confirm_move(self, data, target_path) -> bool:
        try:
            src_paths = data.data(self._mime_type).data().decode('utf-8').split('\n')
        except Exception:
            return False
        src_paths = [p for p in src_paths if p]
        if not src_paths:
            return False
        parent = QtWidgets.QApplication.activeWindow()
        shown = '\n'.join(src_paths[:5])
        more = f"\n+{len(src_paths) - 5} more" if len(src_paths) > 5 else ""
        msg = f"Are you sure to move {len(src_paths)} folder(s) to:\n{normalize_path(target_path)}\n\n{shown}{more}"
        return ConfirmDialog.ask(msg, title="Confirm", buttons=("Move", "Cancel"), parent=parent) == "Move"

    @profiler.profile
    def setData(self, index, value, role=QtCore.Qt.EditRole):
        if role == QtCore.Qt.EditRole and index.isValid() and index.column() == 0:
            item = self.itemFromIndex(index)
            if not self._is_valid_item(item):
                return False
            new_name = str(value)
            if not new_name:
                return False
            return self._rename_item(item, new_name)
        return super().setData(index, value, role)

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
            for entry in natsorted(os.scandir(path), key=lambda e: e.name.lower()):
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

class LazyFolderTreeView(QtWidgets.QTreeView, Kit.UIMixin):
    folder_selected = QtCore.Signal()

    def __init__(self, roots=None, excluded=None):
        super().__init__()
        self.setStyleSheet('QTreeView::item:selected { background-color: rgb(59, 128, 255);}')
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.NoContextMenu)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.DoubleClicked
        )
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        self.init_command_binding("FolderTree", enable_drops=True, use_existing_events=True)
        self.viewport().installEventFilter(self)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        pos = ctx.get("pos") if hasattr(ctx, "get") else None
        idx = self.indexAt(pos) if pos is not None else QtCore.QModelIndex()
        clicked = idx.data(USER_ROLE_PATH) if idx.isValid() else None
        selected = self.get_selected_paths()
        path = clicked or (selected[0] if selected else None)
        return {"path": path, "paths": selected}

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
    def rename_path(self, path, new_name):
        item = self.model_.find_item_by_path(path)
        if not self.model_._is_valid_item(item):
            return False
        return self.model_._rename_item(item, new_name)

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

    @profiler.profile
    def move_paths(self, src_paths, dest_dir):
        dest_dir = normalize_path(dest_dir)
        parent_item = self.model_.find_item_by_path(dest_dir)
        if not self.model_._is_valid_item(parent_item):
            return False
        moved_all = True
        for p in src_paths:
            item = self.model_.find_item_by_path(p)
            if not self.model_._is_valid_item(item):
                moved_all = False
                continue
            if normalize_path(dest_dir).startswith(normalize_path(p) + os.sep):
                moved_all = False
                continue
            ok = self.model_._move_item(item, parent_item)
            moved_all = moved_all and ok
        if moved_all:
            self.model_.sort(0, QtCore.Qt.AscendingOrder)
        return moved_all

    def eventFilter(self, source, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            if event.button() == QtCore.Qt.LeftButton:
                index = self.indexAt(event.pos())
                if not index.isValid():
                    self.clearSelection()
                    self.folder_selected.emit()
        return super().eventFilter(source, event)

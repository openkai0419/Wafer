import os
from pathlib import Path
from natsort import natsorted
from PySide6 import QtCore, QtGui, QtWidgets
from source.utils.paths import normalize_path
from source.utils.profiling import profiler
from source.utils.logs import AppLogger
from ..viewer_settings import app_settings
from source.core.actions.bridge import ActionKit, UI, Context
from source.core.platform.dragparser import MimeDataParser
from source.core.platform.file_operations import (    PastePlanItem, check_copy_conflict, unique_path,
    execute_paste_plans_with_ui, drop_files_with_ui,
)


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
        parts = base_path.split(os.sep)
        node = self.path_item_trie
        stack = []
        for part in parts:
            if part not in node:
                self.path_item_map.pop(base_path, None)
                return
            stack.append((node, part))
            node = node[part]
        self._clear_subtree_map(node, base_path)
        if stack:
            parent, key = stack[-1]
            del parent[key]
            for parent, key in reversed(stack[:-1]):
                if not parent.get(key):
                    del parent[key]
                else:
                    break

    def _clear_subtree_map(self, node, prefix):
        self.path_item_map.pop(prefix, None)
        for key, child in list(node.items()):
            if key != '__item__':
                self._clear_subtree_map(child, prefix + os.sep + key)

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
        parent_path = normalize_path(os.path.dirname(old_path)) if parent_item is self.invisibleRootItem() else normalize_path(parent_item.data(USER_ROLE_PATH))
        dest_path = normalize_path(os.path.join(parent_path, new_name))
        if dest_path == old_path:
            return True

        conflict = os.path.exists(dest_path)
        plan = [PastePlanItem(
            index=0,
            src=Path(old_path),
            is_dir=True,
            action="cut",
            dst_default=Path(dest_path),
            conflict=conflict,
            suggested_dst=Path(unique_path(parent_path, new_name)) if conflict else None,
        )]
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        res = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent_w)
        if not res or res[0].get("status") != "ok":
            return False

        final_dst = res[0].get("dst", dest_path)
        final_dst = normalize_path(final_dst)
        item.setText(os.path.basename(final_dst) or final_dst)
        self._update_item_path_recursive(item, old_path, final_dst)
        if parent_item is self.invisibleRootItem():
            try:
                idx = self.roots.index(old_path)
                self.roots[idx] = final_dst
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

        conflict = os.path.exists(dest_path)
        plan = [PastePlanItem(
            index=0,
            src=Path(old_path),
            is_dir=True,
            action="cut",
            dst_default=Path(dest_path),
            conflict=conflict,
            suggested_dst=Path(unique_path(new_parent_path, os.path.basename(old_path))) if conflict else None,
        )]
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        res = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent_w)
        if not res or res[0].get("status") != "ok":
            return False

        src_parent = item.parent() or self.invisibleRootItem()
        row = item.row()
        taken = src_parent.takeRow(row)
        if not taken:
            self._request_reload_tree()
            return True

        final_dst = normalize_path(res[0].get("dst", dest_path))
        if not new_parent_item.hasChildren() or (new_parent_item.rowCount() == 1 and not new_parent_item.child(0).data(USER_ROLE_PATH)):
            new_parent_item.removeRows(0, new_parent_item.rowCount())
        new_parent_item.appendRow(taken)
        moved_item = new_parent_item.child(new_parent_item.rowCount() - 1)
        self._update_item_path_recursive(moved_item, old_path, final_dst)
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
        return QtCore.Qt.MoveAction | QtCore.Qt.CopyAction

    def _request_reload_tree(self):
        p = self.parent()
        if p is not None and hasattr(p, "reload_tree"):
            try:
                p.reload_tree()
            except Exception:
                pass

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
        if action not in (QtCore.Qt.MoveAction, QtCore.Qt.CopyAction):
            return False
        if not data or (not data.hasFormat(self._mime_type) and not data.hasUrls()):
            return False
        if row != -1 or not parent.isValid():
            return False
        parent_item = self.itemFromIndex(parent)
        if parent_item is None:
            return False
        target_path = parent_item.data(USER_ROLE_PATH)
        if not target_path or target_path in self.excluded:
            return False
        target_norm = normalize_path(target_path)

        if data.hasFormat(self._mime_type):
            if action != QtCore.Qt.MoveAction:
                return False
            try:
                src_paths = bytes(data.data(self._mime_type)).decode('utf-8').split('\n')
            except Exception:
                return False
            for src in src_paths:
                src_norm = normalize_path(src)
                if src_norm == target_norm:
                    return False
                if target_norm.startswith(src_norm + os.sep):
                    return False
            return True

        urls = list(getattr(data, "urls", lambda: [])() or [])
        if not urls:
            return False
        for url in urls:
            if not url.isLocalFile():
                continue
            src = url.toLocalFile()
            if not src or not os.path.exists(src):
                continue
            dst = normalize_path(os.path.join(target_norm, os.path.basename(src)))
            c = check_copy_conflict(src, dst)
            if c in ("same_path", "subpath"):
                return False
        return True

    @profiler.profile
    def dropMimeData(self, data, action, row, column, parent):
        if action not in (QtCore.Qt.MoveAction, QtCore.Qt.CopyAction):
            return False
        if not data or (not data.hasFormat(self._mime_type) and not data.hasUrls()):
            return False
        if row != -1 or not parent.isValid():
            return False
        parent_item = self.itemFromIndex(parent) if parent.isValid() else None
        if parent_item is None:
            return False
        target_path = parent_item.data(USER_ROLE_PATH)
        if not target_path or target_path in self.excluded:
            return False

        dest_dir = normalize_path(target_path)

        if data.hasFormat(self._mime_type):
            if action != QtCore.Qt.MoveAction:
                return False
            try:
                src_paths = data.data(self._mime_type).data().decode('utf-8').split('\n')
            except Exception:
                return False
            src_paths = [p for p in src_paths if p]
            valid_srcs = []
            for src in src_paths:
                src_norm = normalize_path(src)
                if src_norm == dest_dir:
                    continue
                if dest_dir.startswith(src_norm + os.sep):
                    continue
                src_parent = normalize_path(os.path.dirname(src_norm))
                if src_parent == dest_dir:
                    continue
                if self._is_valid_item(self.find_item_by_path(src)):
                    valid_srcs.append(src)
            if not valid_srcs:
                return False

            plans = []
            for i, src in enumerate(valid_srcs):
                name = os.path.basename(src)
                dst_default = Path(dest_dir) / name
                conflict = dst_default.exists()
                suggested = Path(unique_path(dest_dir, name)) if conflict else None
                plans.append(PastePlanItem(index=i, src=Path(src), is_dir=True, action="cut", dst_default=dst_default, conflict=conflict, suggested_dst=suggested))

            parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
            res = execute_paste_plans_with_ui(plans=plans, overwrite_mode="ask", parent=parent_w)
            if not res:
                return False

            for r in res:
                if r.get("status") != "ok":
                    continue
                src = r.get("src")
                dst = r.get("dst")
                if not src or not dst:
                    continue
                src_item = self.find_item_by_path(src)
                if not self._is_valid_item(src_item):
                    continue
                src_parent_item = src_item.parent() or self.invisibleRootItem()
                taken = src_parent_item.takeRow(src_item.row())
                if not taken:
                    continue
                if not parent_item.hasChildren() or (parent_item.rowCount() == 1 and not parent_item.child(0).data(USER_ROLE_PATH)):
                    parent_item.removeRows(0, parent_item.rowCount())
                parent_item.appendRow(taken)
                moved_item = parent_item.child(parent_item.rowCount() - 1)
                self._update_item_path_recursive(moved_item, normalize_path(src), normalize_path(dst))

            self.sort(0, QtCore.Qt.AscendingOrder)
            return True

        parser = MimeDataParser()
        if not parser.can_accept(data):
            return False

        src_items = parser.parse(data)
        if not src_items:
            return False

        op = "move" if action == QtCore.Qt.MoveAction else "copy"
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        drop_files_with_ui(src_items, dest_dir, op, overwrite_mode="ask", parent=parent_w)

        self._request_reload_tree()
        return True

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
            AppLogger.debug(f'Failed to quick-check entries in {path}: {e}')
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
            AppLogger.debug(f'Failed to read {path}: {e}')

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
    current_path_changed = QtCore.Signal(object)

    def __init__(self, roots=None, excluded=None):
        super().__init__()
        self.setStyleSheet('QTreeView::item:selected { background-color: rgb(59, 128, 255);}')
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.model_.setParent(self)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.setEditTriggers(
            QtWidgets.QAbstractItemView.EditKeyPressed
            | QtWidgets.QAbstractItemView.SelectedClicked
            | QtWidgets.QAbstractItemView.DoubleClicked
        )
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        UI.register_instance("FolderTree", self)
        self.viewport().installEventFilter(self)

        self.viewport().setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self.show_context_menu)

    def binding_scope(self) -> str:
        return "FolderTree"

    def show_context_menu(self, position):
        from ..commands import foldertree_commands
        gp = self.viewport().mapToGlobal(position)
        ctx = Context.create_menu_context(self, "FolderTree", pos=position, global_pos=gp)
        ctx.extras.update(self.extend_context(ctx, None, source="menu") or {})
        foldertree_commands.show_context_menu(ctx)

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

    def set_folders(self, roots, excluded=None):
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
        app_settings.save_immediate(f'tree/state/{name}', self.get_state())

    def restore_state(self, name):
        self.set_state(app_settings.get(f'tree/state/{name}', ([], [])))

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

    def dragEnterEvent(self, event):
        md = event.mimeData()
        if md and (md.hasUrls() or md.hasFormat(self.model_._mime_type)):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def eventFilter(self, source, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if source == self.viewport() and event.type() == QtCore.QEvent.ContextMenu:
            if hasattr(event, "pos") and callable(getattr(event, "pos")):
                self.show_context_menu(event.pos())
                return True
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            if event.button() == QtCore.Qt.LeftButton:
                index = self.indexAt(event.pos())
                if not index.isValid():
                    self.clearSelection()
                    self.folder_selected.emit()
        return super().eventFilter(source, event)

    def current_path(self) -> str | None:
        idx = self.currentIndex()
        return idx.data(USER_ROLE_PATH) if idx.isValid() else None

    def _select_and_emit(self, path):
        if not path:
            return None
        self.expand_and_select_path(path)
        self.current_path_changed.emit(path)
        return path

    @profiler.profile
    def navigate_next_visible(self) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            first = self.model().index(0, 0)
            if first.isValid():
                return self._select_and_emit(first.data(USER_ROLE_PATH))
            return None
        below = self.indexBelow(idx)
        while below.isValid():
            path = below.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path)
            below = self.indexBelow(below)
        return None

    @profiler.profile
    def navigate_prev_visible(self) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        above = self.indexAbove(idx)
        while above.isValid():
            path = above.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path)
            above = self.indexAbove(above)
        return None

    @profiler.profile
    def navigate_parent(self) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        parent = idx.parent()
        if parent.isValid():
            path = parent.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path)
        return None

    @profiler.profile
    def navigate_child(self) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        item = self.model_.itemFromIndex(idx)
        if item is None:
            return None
        self.model_.load_children(item)
        self.expand(idx)
        if item.rowCount() > 0:
            child = item.child(0)
            if child:
                path = child.data(USER_ROLE_PATH)
                if path:
                    return self._select_and_emit(path)
        return None

    @staticmethod
    def _list_subdirs(path, excluded):
        try:
            entries = []
            for entry in os.scandir(path):
                if entry.is_dir(follow_symlinks=False):
                    full = normalize_path(entry.path)
                    if full not in excluded:
                        entries.append(full)
            return natsorted(entries, key=lambda p: os.path.basename(p).lower())
        except (PermissionError, OSError):
            return []

    @staticmethod
    def _deepest_last(path, excluded):
        while True:
            children = LazyFolderTreeView._list_subdirs(path, excluded)
            if not children:
                return path
            path = children[-1]

    @profiler.profile
    def navigate_next_dfs(self) -> str | None:
        current = self.current_path()
        if not current:
            sorted_roots = natsorted(self.model_.roots, key=lambda p: os.path.basename(p).lower())
            return self._select_and_emit(sorted_roots[0]) if sorted_roots else None

        current = normalize_path(current)
        excluded = self.model_.excluded
        sorted_roots = natsorted([normalize_path(r) for r in self.model_.roots], key=lambda p: os.path.basename(p).lower())
        roots_set = set(sorted_roots)

        children = self._list_subdirs(current, excluded)
        if children:
            return self._select_and_emit(children[0])

        path = current
        while True:
            if path in roots_set:
                try:
                    idx = sorted_roots.index(path)
                    if idx + 1 < len(sorted_roots):
                        return self._select_and_emit(sorted_roots[idx + 1])
                except ValueError:
                    pass
                return None
            parent = normalize_path(os.path.dirname(path))
            siblings = self._list_subdirs(parent, excluded)
            try:
                idx = siblings.index(path)
                if idx + 1 < len(siblings):
                    return self._select_and_emit(siblings[idx + 1])
            except ValueError:
                pass
            path = parent

    @profiler.profile
    def navigate_prev_dfs(self) -> str | None:
        current = self.current_path()
        if not current:
            return None

        current = normalize_path(current)
        excluded = self.model_.excluded
        sorted_roots = natsorted([normalize_path(r) for r in self.model_.roots], key=lambda p: os.path.basename(p).lower())
        roots_set = set(sorted_roots)

        if current in roots_set:
            try:
                idx = sorted_roots.index(current)
                if idx > 0:
                    return self._select_and_emit(self._deepest_last(sorted_roots[idx - 1], excluded))
            except ValueError:
                pass
            return None

        parent = normalize_path(os.path.dirname(current))
        siblings = self._list_subdirs(parent, excluded)
        try:
            idx = siblings.index(current)
            if idx > 0:
                return self._select_and_emit(self._deepest_last(siblings[idx - 1], excluded))
        except ValueError:
            pass
        return self._select_and_emit(parent)

import os
import threading
import time
from collections import deque
from pathlib import Path
from natsort import natsorted
from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.paths import normalize_path
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
from ....core.qt.dispatcher import Dispatcher, CancelToken
from ....core.qt.thread import utility_pool
from ....core.commands.bridge import UI, Context
from ....core.platform.dragparser import MimeDataParser
from ....core.platform.file_operations import PastePlanItem
from ....core.platform.path_utils import unique_path
from ....core.platform.paste import execute_paste_plans_with_ui, drop_files_with_ui


def _scan_children(path, excluded):
    children = []
    try:
        for entry in natsorted(os.scandir(path), key=lambda e: e.name.lower()):
            if not entry.is_dir(follow_symlinks=False):
                continue
            full = normalize_path(entry.path)
            if full in excluded:
                continue
            has_sub = _has_subfolders_bg(full, excluded)
            children.append((full, has_sub))
    except OSError as e:
        AppLogger.debug(f"_scan_children failed for {path}: {e}")
    return children


def _collect_segments_for_paths(paths, roots):
    segments = []
    seen = set()
    for path in paths:
        root = None
        for r in roots:
            if path.startswith(r):
                root = r
                break
        if root is None:
            continue
        if root not in seen:
            seen.add(root)
            segments.append(root)
        try:
            rel = os.path.relpath(path, root)
        except ValueError:
            continue
        if rel in (".", ""):
            continue
        current = root
        for part in rel.split(os.sep):
            current = normalize_path(os.path.join(current, part))
            if current not in seen:
                seen.add(current)
                segments.append(current)
    return segments


def _has_subfolders_bg(path, excluded):
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    if normalize_path(entry.path) not in excluded:
                        return True
        return False
    except OSError:
        return False


FOLDER_ICON = QtGui.QIcon.fromTheme("folder")
USER_ROLE_PATH = QtCore.Qt.UserRole
EXPAND_RECURSIVE_BATCH_SIZE = 64
EXPAND_RECURSIVE_QUEUE_LIMIT = 512
EXPAND_RECURSIVE_DRAIN_MS = 6.0


class RecursiveExpandJob:
    __slots__ = ("root_path", "token", "pending", "condition", "scanned", "scheduled")

    def __init__(self, root_path, token):
        self.root_path = root_path
        self.token = token
        self.pending = deque()
        self.condition = threading.Condition()
        self.scanned = False
        self.scheduled = False


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
        self.excluded = set(normalize_path(p) for p in excluded or [])
        self.setHorizontalHeaderLabels(["Folders"])
        self.path_item_map = {}
        self.path_item_trie = {}
        self._mime_type = "application/x-foldertree-paths"
        self._dispatcher = Dispatcher(utility_pool, parent=self)
        self._pending_expands: dict[str, CancelToken] = {}

    def cancel_pending_expands(self):
        for token in self._pending_expands.values():
            token.cancel()
        self._pending_expands.clear()

    @profiler.profile
    def clear_cache(self):
        self.cancel_pending_expands()
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
        if "__item__" in node:
            del node["__item__"]
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
        node["__item__"] = item

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
            if key != "__item__":
                self._clear_subtree_map(child, prefix + os.sep + key)

    @profiler.profile
    def _update_item_path_recursive(self, item, old_base, new_base):
        old_item_path = normalize_path(item.data(USER_ROLE_PATH))
        if not old_item_path.startswith(old_base):
            return
        relative = os.path.relpath(old_item_path, old_base)
        new_item_path = normalize_path(os.path.join(new_base, "." if relative == "." else relative))
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
        plan = [
            PastePlanItem(
                index=0,
                src=Path(old_path),
                is_dir=True,
                action="cut",
                dst_default=Path(dest_path),
                conflict=conflict,
                suggested_dst=Path(unique_path(parent_path, new_name)) if conflict else None,
            )
        ]
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        res = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent_w)
        if not res or res[0].status != "ok":
            return False

        final_dst = res[0].dst or dest_path
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
        plan = [
            PastePlanItem(
                index=0,
                src=Path(old_path),
                is_dir=True,
                action="cut",
                dst_default=Path(dest_path),
                conflict=conflict,
                suggested_dst=Path(unique_path(new_parent_path, os.path.basename(old_path))) if conflict else None,
            )
        ]
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        res = execute_paste_plans_with_ui(plans=plan, overwrite_mode="ask", parent=parent_w)
        if not res or res[0].status != "ok":
            return False

        src_parent = item.parent() or self.invisibleRootItem()
        row = item.row()
        taken = src_parent.takeRow(row)
        if not taken:
            self._request_reload_tree()
            return True

        final_dst = normalize_path(res[0].dst or dest_path)
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
        return node.get("__item__")

    @profiler.profile
    def _build_roots(self, roots):
        self.roots = roots
        for root in roots:
            root = normalize_path(root)
            if root in self.excluded:
                continue
            item = create_folder_item(root)
            if _has_subfolders_bg(root, self.excluded):
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
            except Exception as e:
                AppLogger.debug(f"_request_reload_tree failed: {e}")

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
        mime.setData(self._mime_type, "\n".join(paths).encode("utf-8"))
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
        if not os.path.isdir(normalize_path(target_path)):
            return False
        if data.hasFormat(self._mime_type):
            return action == QtCore.Qt.MoveAction
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
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        dest_name = os.path.basename(dest_dir) or dest_dir

        if data.hasFormat(self._mime_type):
            if action != QtCore.Qt.MoveAction:
                return False
            try:
                src_paths = data.data(self._mime_type).data().decode("utf-8").split("\n")
            except (UnicodeDecodeError, AttributeError):
                return False
            src_paths = [p for p in src_paths if p]
            if not src_paths:
                return False

            plans = []
            for i, src in enumerate(src_paths):
                name = os.path.basename(src)
                dst_default = Path(dest_dir) / name
                conflict = dst_default.exists()
                suggested = Path(unique_path(dest_dir, name)) if conflict else None
                plans.append(
                    PastePlanItem(
                        index=i,
                        src=Path(src),
                        is_dir=True,
                        action="cut",
                        dst_default=dst_default,
                        conflict=conflict,
                        suggested_dst=suggested,
                    )
                )

            confirm = f'Move {len(src_paths)} folder(s) to "{dest_name}"?'
            execute_paste_plans_with_ui(plans=plans, overwrite_mode="ask", parent=parent_w, confirm_message=confirm)
            self._request_reload_tree()
            return True

        parser = MimeDataParser()
        if not parser.can_accept(data):
            return False

        src_items = parser.parse(data)
        if not src_items:
            return False

        op = "move" if action == QtCore.Qt.MoveAction else "copy"
        label = "Move" if op == "move" else "Copy"
        confirm = f'{label} {len(src_items)} item(s) to "{dest_name}"?'
        drop_files_with_ui(src_items, dest_dir, op, overwrite_mode="ask", parent=parent_w, confirm_message=confirm)
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
        return _has_subfolders_bg(path, self.excluded)

    @profiler.profile
    def load_children(self, parent_item):
        if parent_item.hasChildren() and parent_item.child(0).data(USER_ROLE_PATH):
            return
        parent_item.removeRows(0, parent_item.rowCount())
        path = parent_item.data(USER_ROLE_PATH)
        children = _scan_children(path, self.excluded)
        self._apply_children(parent_item, path, children)

    def request_expand(self, item):
        path = item.data(USER_ROLE_PATH)
        if not path:
            return
        if item.hasChildren() and item.child(0).data(USER_ROLE_PATH):
            return
        if path in self._pending_expands:
            return
        cancel = CancelToken()
        self._pending_expands[path] = cancel
        excluded = set(self.excluded)

        def task():
            children = _scan_children(path, excluded)
            if cancel.is_cancelled():
                self._dispatcher.invoke(lambda: self._pending_expands.pop(path, None))
                return
            self._dispatcher.invoke(lambda: self._apply_children(item, path, children))

        self._dispatcher.post(task)

    def _apply_children(self, item, path, children, clear_pending=True):
        if clear_pending:
            self._pending_expands.pop(path, None)
        if not self._is_valid_item(item):
            AppLogger.debug(f"[FolderTree._apply_children] SKIPPED (invalid item): {path}")
            return
        item.removeRows(0, item.rowCount())
        for full_path, has_sub in children:
            child = create_folder_item(full_path)
            if has_sub:
                child.setChild(0, QtGui.QStandardItem())
            item.appendRow(child)
            self._add_item(full_path, child)

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
            if rel == "." or rel == "":
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
        from ....core.color.theme import ThemeManager

        _p = ThemeManager.instance().palette
        self.setStyleSheet(f"QTreeView::item:selected {{ background-color: {_p.accent}; color: {_p.accent_text}; }}")
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.model_ = LazyFolderTreeModel(roots, excluded)
        self.model_.setParent(self)
        self.setSelectionMode(QtWidgets.QAbstractItemView.ExtendedSelection)
        self.setModel(self.model_)
        self.setUniformRowHeights(True)
        self.setEditTriggers(QtWidgets.QAbstractItemView.EditKeyPressed | QtWidgets.QAbstractItemView.SelectedClicked | QtWidgets.QAbstractItemView.DoubleClicked)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDefaultDropAction(QtCore.Qt.MoveAction)
        self._programmatic_expand = 0
        self._recursive_expand_jobs = {}
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        UI.register_instance("FolderTree", self)
        self.viewport().installEventFilter(self)

        self.viewport().setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self.show_context_menu)

    def binding_scope(self) -> str:
        return "FolderTree"

    def show_context_menu(self, position):
        from wafer.builtins.commands import foldertree

        gp = self.viewport().mapToGlobal(position)
        ctx = Context.create_menu_context(self, "FolderTree", pos=position, global_pos=gp)
        ctx.extras.update(self.extend_context(ctx, None, source="menu") or {})
        foldertree.show_context_menu(ctx)

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
        excluded = set(normalize_path(e) for e in excluded or [])
        self._cancel_recursive_expand_jobs()
        self.model_.clear()
        self.model_.roots = roots
        self.model_.excluded = excluded
        self.model_.setHorizontalHeaderLabels(["Folders"])
        self.model_._build_roots(roots)

    @property
    def roots(self):
        return self.model_.roots

    @profiler.profile
    def expand_path(self, path):
        path = normalize_path(path)
        parts = path.split(os.sep)
        current_item = None
        current_path = ""
        self._programmatic_expand += 1
        try:
            for part in parts:
                current_path = normalize_path(os.path.join(current_path, part))
                item = self.model_.find_item_by_path(current_path)
                if not self.model_._is_valid_item(item):
                    AppLogger.debug(f"[FolderTree.expand_path] item not found at: {current_path} (target: {path})")
                    return None
                index = self.model_.indexFromItem(item)
                if not index.isValid():
                    AppLogger.debug(f"[FolderTree.expand_path] invalid index at: {current_path} (target: {path})")
                    return None
                self.model_.load_children(item)
                self.expand(index)
                current_item = item
        finally:
            self._programmatic_expand -= 1
        return self.model_.indexFromItem(current_item) if current_item else None

    @profiler.profile
    def on_expanded(self, index):
        if self._programmatic_expand:
            return
        item = self.model_.itemFromIndex(index)
        self.model_.request_expand(item)

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
        pending = list(self.model_._pending_expands.keys())
        AppLogger.debug(f"[FolderTree.get_state] expanded={len(expanded)} selected={len(selected)} pending_expands={pending}")
        if expanded:
            AppLogger.debug(f"[FolderTree.get_state] paths={expanded}")
        return (expanded, selected)

    @profiler.profile
    def set_state(self, states):
        try:
            expanded, selected = states
        except (ValueError, TypeError):
            return
        AppLogger.debug(f"[FolderTree.set_state] restoring expanded={len(expanded)} selected={len(selected)}")
        selmodel = self.selectionModel()
        selmodel.clearSelection()
        to_select = []
        for path in expanded:
            index = self.expand_path(path)
            if index and index.isValid():
                self.model_.load_children(self.model_.itemFromIndex(index))
            else:
                AppLogger.debug(f"[FolderTree.set_state] expand FAILED: {path}")
        for path in selected:
            index = self.model_.find_index_by_path(path)
            if index and index.isValid():
                to_select.append(index)
        for idx in to_select:
            selmodel.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        if to_select:
            selmodel.setCurrentIndex(to_select[0], QtCore.QItemSelectionModel.NoUpdate)
            self.scrollTo(to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)

    def set_state_async(self, states, on_complete=None):
        try:
            expanded, selected = states
        except (ValueError, TypeError):
            if on_complete:
                on_complete()
            return
        if not expanded and not selected:
            if on_complete:
                on_complete()
            return
        roots = [normalize_path(r) for r in self.model_.roots]
        all_paths = list(dict.fromkeys(expanded + selected))
        segments = _collect_segments_for_paths([normalize_path(p) for p in all_paths], roots)
        excluded = set(self.model_.excluded)
        dispatcher = self.model_._dispatcher

        def task():
            children_map = {}
            for seg in segments:
                children_map[seg] = _scan_children(seg, excluded)
            dispatcher.invoke(lambda: self._apply_state_async(expanded, selected, children_map, on_complete))

        dispatcher.post(task, priority=8)

    def _apply_state_async(self, expanded, selected, children_map, on_complete):
        model = self.model_
        for seg_path, children in children_map.items():
            item = model.path_item_map.get(normalize_path(seg_path))
            if not model._is_valid_item(item):
                continue
            if item.hasChildren() and item.child(0).data(USER_ROLE_PATH):
                continue
            model._apply_children(item, seg_path, children)
        self._programmatic_expand += 1
        try:
            for path in expanded:
                path = normalize_path(path)
                item = model.path_item_map.get(path)
                if model._is_valid_item(item):
                    index = model.indexFromItem(item)
                    if index.isValid():
                        self.expand(index)
        finally:
            self._programmatic_expand -= 1
        selmodel = self.selectionModel()
        selmodel.clearSelection()
        to_select = []
        for path in selected:
            path = normalize_path(path)
            item = model.path_item_map.get(path)
            if model._is_valid_item(item):
                index = model.indexFromItem(item)
                if index and index.isValid():
                    to_select.append(index)
        for idx in to_select:
            selmodel.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        if to_select:
            selmodel.setCurrentIndex(to_select[0], QtCore.QItemSelectionModel.NoUpdate)
            self.scrollTo(to_select[0], QtWidgets.QAbstractItemView.PositionAtCenter)
        if on_complete:
            on_complete()

    @profiler.profile
    def expand_and_select_path(self, path, on_complete=None, emit_selected=True):
        self.expand_and_select_paths([path], on_complete=on_complete, emit_selected=emit_selected)

    @profiler.profile
    def expand_and_select_paths(self, paths, on_complete=None, emit_selected=True):
        normalized = list(dict.fromkeys(normalize_path(p) for p in paths if p))
        if not normalized:
            if on_complete:
                on_complete()
            return
        roots = [normalize_path(r) for r in self.model_.roots]
        segments = _collect_segments_for_paths(normalized, roots)
        excluded = set(self.model_.excluded)
        dispatcher = self.model_._dispatcher

        def task():
            children_map = {seg: _scan_children(seg, excluded) for seg in segments}
            dispatcher.invoke(lambda: self._apply_expand_and_select(normalized, children_map, on_complete, emit_selected))

        dispatcher.post(task, priority=8)

    def _apply_expand_and_select(self, paths, children_map, on_complete, emit_selected):
        model = self.model_
        for seg_path, children in children_map.items():
            item = model.path_item_map.get(seg_path)
            if not model._is_valid_item(item):
                continue
            if item.hasChildren() and item.child(0).data(USER_ROLE_PATH):
                continue
            model._apply_children(item, seg_path, children)
        to_select = []
        self._programmatic_expand += 1
        try:
            for path in paths:
                item = model.path_item_map.get(path)
                if not model._is_valid_item(item):
                    AppLogger.debug(f"[FolderTree.expand_and_select_paths] not found: {path}")
                    continue
                index = model.indexFromItem(item)
                if not index.isValid():
                    continue
                parent = index.parent()
                while parent.isValid():
                    self.expand(parent)
                    parent = parent.parent()
                self.expand(index)
                to_select.append(index)
        finally:
            self._programmatic_expand -= 1
        sel_model = self.selectionModel()
        sel_model.clearSelection()
        for idx in to_select:
            sel_model.select(idx, QtCore.QItemSelectionModel.Select | QtCore.QItemSelectionModel.Rows)
        if to_select:
            last = to_select[-1]
            sel_model.setCurrentIndex(last, QtCore.QItemSelectionModel.NoUpdate)
            QtCore.QTimer.singleShot(0, lambda: self.scrollTo(last, QtWidgets.QAbstractItemView.PositionAtCenter))
            if emit_selected:
                self.folder_selected.emit()
        if on_complete:
            on_complete()

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
        self._cancel_recursive_expand_jobs()
        state = self.get_state()
        roots = [item.data(USER_ROLE_PATH) for item in iter_root_items(self.model_)]
        self.model_.clear()
        self.model_.clear_cache()
        self.model_.setHorizontalHeaderLabels(["Folders"])
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

    def dropEvent(self, event):
        super().dropEvent(event)
        event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)

    def eventFilter(self, source, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if source == self.viewport() and event.type() == QtCore.QEvent.ContextMenu:
            if hasattr(event, "pos") and callable(event.pos):
                self.show_context_menu(event.pos())
                return True
        if source == self.viewport() and event.type() == QtCore.QEvent.MouseButtonPress:
            if event.button() == QtCore.Qt.LeftButton and (event.modifiers() & QtCore.Qt.ShiftModifier):
                index = self.indexAt(event.pos())
                if index.isValid() and self.model().hasChildren(index) and self._is_on_branch_indicator(index, event.pos()):
                    path = index.data(USER_ROLE_PATH)
                    if path and normalize_path(path) in self.model_._pending_expands:
                        self._cancel_expand_recursive(index)
                    elif self.isExpanded(index):
                        self.collapse_recursive(index)
                    else:
                        self.expand_recursive(index)
                    return True
        if source == self.viewport() and event.type() in {QtCore.QEvent.MouseButtonPress, QtCore.QEvent.MouseButtonDblClick}:
            if event.button() == QtCore.Qt.LeftButton:
                index = self.indexAt(event.pos())
                if not index.isValid():
                    self.clearSelection()
                    self.folder_selected.emit()
        return super().eventFilter(source, event)

    def _is_on_branch_indicator(self, index, pos):
        rect = self.visualRect(index)
        indent = self.indentation()
        x = pos.x()
        return rect.x() - indent <= x < rect.x() and rect.y() <= pos.y() < rect.y() + rect.height()

    def _cancel_expand_recursive(self, index):
        path = index.data(USER_ROLE_PATH) if index.isValid() else None
        if not path:
            return
        root_path = normalize_path(path)
        token = self.model_._pending_expands.get(root_path)
        if token is not None:
            token.cancel()
        self._finish_expand_recursive_job(root_path)
        self.collapse_recursive(index)

    @profiler.profile
    def collapse_recursive(self, index):
        if not index.isValid():
            return
        model = self.model()
        order = []
        stack = [index]
        while stack:
            idx = stack.pop()
            if not idx.isValid():
                continue
            order.append(idx)
            for i in range(model.rowCount(idx)):
                stack.append(model.index(i, 0, idx))
        for idx in reversed(order):
            if self.isExpanded(idx):
                self.collapse(idx)

    @profiler.profile
    def expand_recursive(self, index):
        if not index.isValid():
            return
        item = self.model_.itemFromIndex(index)
        if item is None:
            return
        root_path = item.data(USER_ROLE_PATH)
        if not root_path:
            return
        root_path = normalize_path(root_path)
        if root_path in self.model_._pending_expands:
            return
        cancel = CancelToken()
        self.model_._pending_expands[root_path] = cancel
        job = RecursiveExpandJob(root_path, cancel)
        self._recursive_expand_jobs[root_path] = job
        excluded = set(self.model_.excluded)
        dispatcher = self.model_._dispatcher

        def task():
            batch = []

            stack = [root_path]
            while stack:
                if cancel.is_cancelled():
                    dispatcher.invoke(lambda: self._finish_expand_recursive_job(root_path))
                    return
                path = stack.pop()
                children = _scan_children(path, excluded)
                batch.append((path, children))
                for child_path, has_sub in reversed(children):
                    if has_sub:
                        stack.append(child_path)
                if len(batch) >= EXPAND_RECURSIVE_BATCH_SIZE and not self._push_recursive_expand_batch(job, batch):
                    dispatcher.invoke(lambda: self._finish_expand_recursive_job(root_path))
                    return
            if batch and not self._push_recursive_expand_batch(job, batch):
                dispatcher.invoke(lambda: self._finish_expand_recursive_job(root_path))
                return
            dispatcher.invoke(lambda: self._complete_recursive_expand_scan(root_path))

        dispatcher.post(task, priority=8)

    def _push_recursive_expand_batch(self, job, batch):
        with job.condition:
            while len(job.pending) >= EXPAND_RECURSIVE_QUEUE_LIMIT and not job.token.is_cancelled():
                job.condition.wait(0.05)
            if job.token.is_cancelled():
                return False
            job.pending.extend(batch)
            batch.clear()
            if job.scheduled:
                return True
            job.scheduled = True
        self.model_._dispatcher.invoke(lambda: self._drain_recursive_expand(job.root_path))
        return True

    def _complete_recursive_expand_scan(self, root_path):
        job = self._recursive_expand_jobs.get(root_path)
        if job is None:
            return
        should_drain = False
        with job.condition:
            job.scanned = True
            if not job.scheduled:
                job.scheduled = True
                should_drain = True
            job.condition.notify_all()
        if should_drain:
            QtCore.QTimer.singleShot(0, lambda: self._drain_recursive_expand(root_path))

    def _drain_recursive_expand(self, root_path):
        job = self._recursive_expand_jobs.get(root_path)
        if job is None:
            return
        if root_path not in self.model_._pending_expands or job.token.is_cancelled():
            self._finish_expand_recursive_job(root_path)
            return
        deadline = time.perf_counter() + EXPAND_RECURSIVE_DRAIN_MS / 1000.0
        processed = False
        updates_enabled = self.updatesEnabled()
        if updates_enabled:
            self.setUpdatesEnabled(False)
        self._programmatic_expand += 1
        try:
            while True:
                with job.condition:
                    if not job.pending:
                        break
                    seg_path, children = job.pending.popleft()
                    job.condition.notify_all()
                self._apply_recursive_expand_entry(seg_path, children)
                processed = True
                if time.perf_counter() >= deadline:
                    break
        finally:
            self._programmatic_expand -= 1
            if updates_enabled:
                self.setUpdatesEnabled(True)
        finish = False
        reschedule = False
        with job.condition:
            if job.token.is_cancelled():
                finish = True
            elif job.pending:
                reschedule = True
            elif job.scanned:
                finish = True
            else:
                job.scheduled = False
            if finish:
                job.scheduled = False
            job.condition.notify_all()
        if finish:
            self._finish_expand_recursive_job(root_path)
        elif reschedule:
            QtCore.QTimer.singleShot(0 if processed else 1, lambda: self._drain_recursive_expand(root_path))

    def _apply_recursive_expand_entry(self, seg_path, children):
        model = self.model_
        item = model.path_item_map.get(normalize_path(seg_path))
        if not model._is_valid_item(item):
            return
        if not (item.hasChildren() and item.child(0).data(USER_ROLE_PATH)):
            model._apply_children(item, seg_path, children, clear_pending=False)
        item = model.path_item_map.get(normalize_path(seg_path))
        if not model._is_valid_item(item):
            return
        idx = model.indexFromItem(item)
        if idx.isValid():
            self.expand(idx)

    def _finish_expand_recursive_job(self, root_path):
        job = self._recursive_expand_jobs.pop(root_path, None)
        if job is not None:
            with job.condition:
                job.pending.clear()
                job.scanned = True
                job.scheduled = False
                job.condition.notify_all()
        self.model_._pending_expands.pop(root_path, None)

    def _cancel_recursive_expand_jobs(self):
        for root_path, job in list(self._recursive_expand_jobs.items()):
            job.token.cancel()
            self._finish_expand_recursive_job(root_path)

    def current_path(self) -> str | None:
        idx = self.currentIndex()
        return idx.data(USER_ROLE_PATH) if idx.isValid() else None

    def _select_and_emit(self, path, trigger_search=True):
        if not path:
            return None
        self.expand_and_select_paths([path], on_complete=lambda: self.current_path_changed.emit(path), emit_selected=trigger_search)
        return path

    @profiler.profile
    def navigate_next_visible(self, trigger_search=True) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            first = self.model().index(0, 0)
            if first.isValid():
                return self._select_and_emit(first.data(USER_ROLE_PATH), trigger_search=trigger_search)
            return None
        below = self.indexBelow(idx)
        while below.isValid():
            path = below.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path, trigger_search=trigger_search)
            below = self.indexBelow(below)
        return None

    @profiler.profile
    def navigate_prev_visible(self, trigger_search=True) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        above = self.indexAbove(idx)
        while above.isValid():
            path = above.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path, trigger_search=trigger_search)
            above = self.indexAbove(above)
        return None

    @profiler.profile
    def navigate_parent(self, trigger_search=True) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        parent = idx.parent()
        if parent.isValid():
            path = parent.data(USER_ROLE_PATH)
            if path:
                return self._select_and_emit(path, trigger_search=trigger_search)
        return None

    @profiler.profile
    def navigate_child(self, trigger_search=True) -> str | None:
        idx = self.currentIndex()
        if not idx.isValid():
            return None
        item = self.model_.itemFromIndex(idx)
        if item is None:
            return None
        self.model_.load_children(item)
        self._programmatic_expand += 1
        try:
            self.expand(idx)
        finally:
            self._programmatic_expand -= 1
        if item.rowCount() > 0:
            child = item.child(0)
            if child:
                path = child.data(USER_ROLE_PATH)
                if path:
                    return self._select_and_emit(path, trigger_search=trigger_search)
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
    def navigate_next_dfs(self, trigger_search=True) -> str | None:
        current = self.current_path()
        if not current:
            sorted_roots = natsorted(self.model_.roots, key=lambda p: os.path.basename(p).lower())
            return self._select_and_emit(sorted_roots[0], trigger_search=trigger_search) if sorted_roots else None

        current = normalize_path(current)
        excluded = self.model_.excluded
        sorted_roots = natsorted([normalize_path(r) for r in self.model_.roots], key=lambda p: os.path.basename(p).lower())
        roots_set = set(sorted_roots)

        children = self._list_subdirs(current, excluded)
        if children:
            return self._select_and_emit(children[0], trigger_search=trigger_search)

        path = current
        while True:
            if path in roots_set:
                try:
                    idx = sorted_roots.index(path)
                    if idx + 1 < len(sorted_roots):
                        return self._select_and_emit(sorted_roots[idx + 1], trigger_search=trigger_search)
                except ValueError:
                    pass
                return None
            parent = normalize_path(os.path.dirname(path))
            siblings = self._list_subdirs(parent, excluded)
            try:
                idx = siblings.index(path)
                if idx + 1 < len(siblings):
                    return self._select_and_emit(siblings[idx + 1], trigger_search=trigger_search)
            except ValueError:
                pass
            path = parent

    @profiler.profile
    def navigate_prev_dfs(self, trigger_search=True) -> str | None:
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
                    return self._select_and_emit(self._deepest_last(sorted_roots[idx - 1], excluded), trigger_search=trigger_search)
            except ValueError:
                pass
            return None

        parent = normalize_path(os.path.dirname(current))
        siblings = self._list_subdirs(parent, excluded)
        try:
            idx = siblings.index(current)
            if idx > 0:
                return self._select_and_emit(self._deepest_last(siblings[idx - 1], excluded), trigger_search=trigger_search)
        except ValueError:
            pass
        return self._select_and_emit(parent, trigger_search=trigger_search)

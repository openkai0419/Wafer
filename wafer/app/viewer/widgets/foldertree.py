import bisect
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import NamedTuple
from natsort import natsort_keygen
from PySide6 import QtCore, QtGui, QtWidgets
from ....core.common.paths import normalize_path
from ....core.profiling import profiler
from ....core.logs import AppLogger
from ....qt.common.dispatcher import Dispatcher, CancelSlot, CancelToken
from ....qt.common.notifier import Notifier
from ....qt.common.thread import utility_pool
from ....qt.commands.bridge import UI, Context
from ....qt.commands.binding.common import TEXT_ENTRY_TYPES as INLINE_EDITOR_TYPES
from ....qt.transfer.dragparser import MimeDataParser
from ....core.platform.file_operations import PastePlanItem
from ....core.platform.path_utils import unique_path, validate_filename
from ....qt.transfer.paste import execute_paste_plans_with_ui, drop_files_with_ui, resolve_drop_operation_with_ui

FOLDER_SORT_KEY = natsort_keygen(key=lambda path: (os.path.basename(path) or path).lower())


class FolderStructure(NamedTuple):
    roots: tuple[str, ...]
    excluded: frozenset[str]
    ignore_pattern: str | None
    loaded_children: dict[str, tuple[str, ...]]


def _is_hidden_folder(path, excluded, ignore_pattern_re):
    return path in excluded or (ignore_pattern_re is not None and ignore_pattern_re.match(path) is not None)


def visible_roots(roots, excluded, ignore_pattern_re=None):
    visible = (root for root in dict.fromkeys(normalize_path(r) for r in roots) if not _is_hidden_folder(root, excluded, ignore_pattern_re))
    return tuple(sorted(visible, key=FOLDER_SORT_KEY))


def scan_roots(roots, excluded, ignore_pattern_re=None):
    return [(root, _has_subfolders_bg(root, excluded, ignore_pattern_re)) for root in visible_roots(roots, excluded, ignore_pattern_re)]


def structure_is_current(structure, roots, excluded, ignore_pattern_re=None):
    excluded = frozenset(normalize_path(path) for path in excluded or ())
    if structure.roots != visible_roots(roots, excluded, ignore_pattern_re) or structure.excluded != excluded:
        return False
    if structure.ignore_pattern != (ignore_pattern_re.pattern if ignore_pattern_re is not None else None):
        return False
    return all(_scan_child_paths(path, excluded, ignore_pattern_re) == children for path, children in structure.loaded_children.items())


def _scan_children(path, excluded, ignore_pattern_re=None):
    child_paths = _scan_child_paths(path, excluded, ignore_pattern_re)
    return [(child_path, _has_subfolders_bg(child_path, excluded, ignore_pattern_re)) for child_path in child_paths]


def _scan_child_paths(path, excluded, ignore_pattern_re=None):
    children = []
    try:
        with os.scandir(path) as it:
            for entry in it:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                full = normalize_path(entry.path)
                if not _is_hidden_folder(full, excluded, ignore_pattern_re):
                    children.append(full)
    except OSError as e:
        AppLogger.warning(f"Cannot list the folders in {path}: {e}")
    return tuple(sorted(children, key=FOLDER_SORT_KEY))


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


def _has_subfolders_bg(path, excluded, ignore_pattern_re=None):
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False) and not _is_hidden_folder(normalize_path(entry.path), excluded, ignore_pattern_re):
                    return True
        return False
    except PermissionError:
        return False
    except OSError as e:
        AppLogger.warning(f"Cannot check the folders in {path}: {e}")
        return False


FOLDER_ICON = QtGui.QIcon.fromTheme("folder")
USER_ROLE_PATH = QtCore.Qt.UserRole
SUPPORTED_DROP_ACTIONS = (QtCore.Qt.MoveAction, QtCore.Qt.CopyAction)
EXPAND_RECURSIVE_BATCH_SIZE = 64
EXPAND_RECURSIVE_QUEUE_LIMIT = 512
EXPAND_RECURSIVE_DRAIN_MS = 6.0


class RecursiveExpandJob:
    __slots__ = ("condition", "pending", "root_path", "scanned", "scheduled", "token")

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
    EXTRA_COLUMNS: tuple[str, ...] = ()

    def __init__(self, roots, excluded=None, ignore_pattern_re=None):
        super().__init__()
        self.roots = roots
        self.excluded = set(normalize_path(p) for p in excluded or [])
        self.ignore_pattern_re = ignore_pattern_re
        self.reset_header()
        self.path_item_map = {}
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

    @profiler.profile
    def _add_item(self, path, item):
        self.path_item_map[normalize_path(path)] = item

    @profiler.profile
    def _update_item_path_recursive(self, item, old_base, new_base):
        old_item_path = normalize_path(item.data(USER_ROLE_PATH))
        if not old_item_path.startswith(old_base):
            return
        relative = os.path.relpath(old_item_path, old_base)
        new_item_path = normalize_path(os.path.join(new_base, "." if relative == "." else relative))
        self.path_item_map.pop(old_item_path, None)
        item.setData(new_item_path, USER_ROLE_PATH)
        self._add_item(new_item_path, item)
        for i in range(item.rowCount()):
            child = item.child(i)
            if child and child.data(USER_ROLE_PATH):
                self._update_item_path_recursive(child, old_base, new_base)

    @profiler.profile
    def _rename_item(self, item, new_name):
        issues = validate_filename(new_name)
        if issues:
            Notifier.warning(f"Invalid filename: {', '.join(issues)}")
            return False
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

    def reset_header(self):
        self.setHorizontalHeaderLabels(["Folders", *self.EXTRA_COLUMNS])

    def make_row(self, path: str) -> list[QtGui.QStandardItem]:
        row = [create_folder_item(path)]
        for _ in self.EXTRA_COLUMNS:
            cell = QtGui.QStandardItem()
            cell.setFlags(QtCore.Qt.ItemIsEnabled | QtCore.Qt.ItemIsSelectable)
            row.append(cell)
        return row

    @profiler.profile
    def _build_roots(self, roots):
        self.roots = roots
        self.append_roots(scan_roots(roots, self.excluded, self.ignore_pattern_re))

    def append_roots(self, root_entries):
        for root, has_subfolders in root_entries:
            self.insert_root(root, has_subfolders)

    def insert_root(self, path, has_subfolders):
        row = self.make_row(path)
        if has_subfolders:
            row[0].setChild(0, QtGui.QStandardItem())
        root_paths = [item.data(USER_ROLE_PATH) for item in iter_root_items(self)]
        self.insertRow(bisect.bisect_right(root_paths, FOLDER_SORT_KEY(path), key=FOLDER_SORT_KEY), row)
        self._add_item(path, row[0])

    def children_loaded(self, item):
        return self._is_valid_item(item) and item.hasChildren() and bool(item.child(0).data(USER_ROLE_PATH))

    def flags(self, index):
        default = super().flags(index)
        if not index.isValid() or index.column() != 0:
            return default
        return default | QtCore.Qt.ItemIsEditable | QtCore.Qt.ItemIsDragEnabled | QtCore.Qt.ItemIsDropEnabled

    def supportedDropActions(self):
        return QtCore.Qt.MoveAction | QtCore.Qt.CopyAction

    def _request_reload_tree(self):
        p = self.parent()
        if p is not None and hasattr(p, "reload_tree"):
            p.reload_tree()

    def mimeTypes(self):
        return [self._mime_type]

    def mimeData(self, indexes):
        mime = QtCore.QMimeData()
        paths = dict.fromkeys(path for idx in indexes if idx.column() == 0 and (path := idx.data(USER_ROLE_PATH)))
        mime.setData(self._mime_type, "\n".join(paths).encode("utf-8"))
        return mime

    def canDropMimeData(self, data, action, row, column, parent):
        if action not in SUPPORTED_DROP_ACTIONS:
            return False
        if not data or (not data.hasFormat(self._mime_type) and not data.hasUrls()):
            return False
        if row != -1 or not parent.isValid():
            return False
        parent_item = self.itemFromIndex(parent)
        if parent_item is None:
            return False
        target_path = parent_item.data(USER_ROLE_PATH)
        return bool(target_path and target_path not in self.excluded)

    @profiler.profile
    def dropMimeData(self, data, action, row, column, parent):
        if action not in SUPPORTED_DROP_ACTIONS:
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
        if not os.path.isdir(dest_dir):
            return False
        parent_w = self.parent() or QtWidgets.QApplication.activeWindow()
        dest_name = os.path.basename(dest_dir) or dest_dir

        if data.hasFormat(self._mime_type):
            try:
                src_paths = data.data(self._mime_type).data().decode("utf-8").split("\n")
            except (UnicodeDecodeError, AttributeError):
                return False
            src_paths = [p for p in src_paths if p]
            if not src_paths:
                return False

            confirm = f'Drop {len(src_paths)} folder(s) to "{dest_name}"?\nChoose your operation.'
            op = resolve_drop_operation_with_ui("ask", parent=parent_w, message=confirm)
            if op is None:
                return False
            plan_action = "cut" if op == "move" else "copy"

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
                        action=plan_action,
                        dst_default=dst_default,
                        conflict=conflict,
                        suggested_dst=suggested,
                    )
                )

            execute_paste_plans_with_ui(plans=plans, overwrite_mode="ask", parent=parent_w)
            self._request_reload_tree()
            return True

        parser = MimeDataParser()
        if not parser.can_accept(data):
            return False

        src_items = parser.parse(data)
        if not src_items:
            return False

        confirm = f'Drop {len(src_items)} item(s) to "{dest_name}"?\nChoose your operation.'
        drop_files_with_ui(src_items, dest_dir, "ask", overwrite_mode="ask", parent=parent_w, confirm_message=confirm)
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
        return _has_subfolders_bg(path, self.excluded, self.ignore_pattern_re)

    def request_expand(self, item):
        path = item.data(USER_ROLE_PATH)
        if not path:
            return
        if self.children_loaded(item):
            return
        if path in self._pending_expands:
            return
        cancel = CancelToken()
        self._pending_expands[path] = cancel
        excluded = set(self.excluded)
        ignore_pattern_re = self.ignore_pattern_re

        def task():
            children = _scan_children(path, excluded, ignore_pattern_re)
            if cancel.is_cancelled():
                self._dispatcher.invoke(lambda: self._pending_expands.pop(path, None))
                return
            self._dispatcher.invoke(lambda: self._apply_expanded_children(item, path, children))

        self._dispatcher.post(task)

    def _apply_expanded_children(self, item, path, children):
        if self.children_loaded(item):
            self._pending_expands.pop(path, None)
            return
        self._apply_children(item, path, children)

    def _apply_children(self, item, path, children, clear_pending=True):
        if clear_pending:
            self._pending_expands.pop(path, None)
        if not self._is_valid_item(item):
            AppLogger.debug(f"[FolderTree._apply_children] SKIPPED (invalid item): {path}")
            return
        item.removeRows(0, item.rowCount())
        for full_path, has_sub in children:
            row = self.make_row(full_path)
            child = row[0]
            if has_sub:
                child.setChild(0, QtGui.QStandardItem())
            item.appendRow(row)
            self._add_item(full_path, child)

    @profiler.profile
    def _is_valid_item(self, item):
        try:
            return item is not None and item.model() is not None
        except RuntimeError:
            return False


class LazyFolderTreeView(QtWidgets.QTreeView):
    MODEL_CLASS = LazyFolderTreeModel
    BINDING_SCOPE = "FolderTree"
    folder_selected = QtCore.Signal()
    current_path_changed = QtCore.Signal(object)
    folders_set = QtCore.Signal()

    def __init__(self, roots=None, excluded=None, ignore_pattern_re=None, *, instance_name: str | None = None):
        super().__init__()
        from ....qt.theme import ThemeManager

        _p = ThemeManager.instance().palette
        self.setStyleSheet(f"QTreeView::item:selected {{ background-color: {_p.accent}; color: {_p.accent_text}; }}")
        self._drop_target_fill = QtGui.QColor(_p.accent)
        self._drop_target_fill.setAlpha(72)
        self._drop_target_pen = QtGui.QPen(QtGui.QColor(_p.accent))
        self.setHeaderHidden(True)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.model_ = self.MODEL_CLASS(roots, excluded, ignore_pattern_re)
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
        self._reload_cancel = CancelSlot()
        self._scroll_restore_serial = 0
        self._pending_reload_local_callback = None
        self._pending_reload_strong_callback = None
        self._pending_reload_scheduled = False
        self._drop_target_index = QtCore.QModelIndex()
        self.expanded.connect(self.on_expanded)
        self.clicked.connect(self._on_item_clicked)
        UI.register_instance(instance_name or self.BINDING_SCOPE, self)
        self.viewport().installEventFilter(self)

        self.viewport().setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.viewport().customContextMenuRequested.connect(self.show_context_menu)

    def binding_scope(self) -> str:
        return self.BINDING_SCOPE

    def keyboardSearch(self, search):
        return

    def drawRow(self, painter, option, index):
        super().drawRow(painter, option, index)
        if not self._is_drop_target_index(index):
            return
        rect = QtCore.QRect(0, option.rect.top(), self.viewport().width(), option.rect.height())
        painter.save()
        painter.fillRect(rect, self._drop_target_fill)
        painter.setPen(self._drop_target_pen)
        painter.drawRect(rect.adjusted(0, 0, -1, -1))
        painter.restore()

    def _is_drop_target_index(self, index):
        return index.isValid() and self._drop_target_index.isValid() and index == self._drop_target_index

    def _drop_mime_supported(self, mime):
        return bool(mime and (mime.hasUrls() or mime.hasFormat(self.model_._mime_type)))

    def _drop_action_supported(self, action):
        return action in SUPPORTED_DROP_ACTIONS

    def _drop_action_for_event(self, event):
        proposed = getattr(event, "proposedAction", None)
        if callable(proposed):
            action = proposed()
            if self._drop_action_supported(action):
                return action
        current = getattr(event, "dropAction", None)
        if callable(current):
            action = current()
            if self._drop_action_supported(action):
                return action
        return QtCore.Qt.DropAction.IgnoreAction

    def _drop_event_pos(self, event):
        position = getattr(event, "position", None)
        if callable(position):
            pos = position()
            return pos.toPoint() if hasattr(pos, "toPoint") else QtCore.QPoint(int(pos.x()), int(pos.y()))
        pos = getattr(event, "pos", None)
        if callable(pos):
            return pos()
        return QtCore.QPoint()

    def _can_drop_on_index(self, mime, action, index):
        if not self._drop_mime_supported(mime) or not self._drop_action_supported(action) or not index.isValid():
            return False
        target_path = index.data(USER_ROLE_PATH)
        if not target_path:
            return False
        return normalize_path(target_path) not in self.model_.excluded

    def _resolve_drop_target_index(self, pos, mime, action):
        if not self._drop_mime_supported(mime) or not self._drop_action_supported(action):
            return QtCore.QModelIndex()
        index = self.indexAt(pos)
        if self._can_drop_on_index(mime, action, index):
            return index
        return self._nearest_drop_target_index(pos, mime, action)

    def _nearest_drop_target_index(self, pos, mime, action):
        viewport_rect = self.viewport().rect()
        best_index = QtCore.QModelIndex()
        best_key = None
        for index in self._iter_visible_indexes():
            if not self._can_drop_on_index(mime, action, index):
                continue
            visual = self.visualRect(index)
            if not visual.isValid():
                continue
            row_rect = QtCore.QRect(viewport_rect.left(), visual.top(), viewport_rect.width(), visual.height())
            key = self._drop_distance_key(pos, row_rect, index)
            if best_key is None or key < best_key:
                best_index = index
                best_key = key
        return best_index

    def _drop_distance_key(self, pos, rect, index):
        px = pos.x()
        py = pos.y()
        dx = rect.left() - px if px < rect.left() else px - rect.right() if px > rect.right() else 0
        dy = rect.top() - py if py < rect.top() else py - rect.bottom() if py > rect.bottom() else 0
        center = rect.center()
        center_dx = center.x() - px
        center_dy = center.y() - py
        return (dx * dx + dy * dy, center_dx * center_dx + center_dy * center_dy, rect.top(), index.row())

    def _iter_visible_indexes(self):
        index = self._first_visible_index()
        if not index.isValid():
            return
        viewport_rect = self.viewport().rect()
        while True:
            prev_index = self.indexAbove(index)
            if not prev_index.isValid():
                break
            prev_rect = self.visualRect(prev_index)
            if not prev_rect.isValid() or prev_rect.bottom() < viewport_rect.top():
                break
            index = prev_index
        while index.isValid():
            rect = self.visualRect(index)
            if rect.isValid() and rect.top() > viewport_rect.bottom():
                break
            if rect.isValid() and rect.bottom() >= viewport_rect.top():
                yield index
            next_index = self.indexBelow(index)
            if not next_index.isValid() or next_index == index:
                break
            index = next_index

    def _first_visible_index(self):
        viewport_rect = self.viewport().rect()
        if not viewport_rect.isValid():
            return QtCore.QModelIndex()
        step = max(1, self.fontMetrics().height() // 2)
        left = viewport_rect.left()
        right = max(left, viewport_rect.right())
        x_candidates = []
        for x in (left, left + self.indentation(), viewport_rect.center().x(), right):
            x = min(right, max(left, x))
            if x not in x_candidates:
                x_candidates.append(x)
        for y in range(viewport_rect.top(), viewport_rect.bottom() + 1, step):
            for x in x_candidates:
                index = self.indexAt(QtCore.QPoint(x, y))
                if index.isValid():
                    return index
        return QtCore.QModelIndex()

    def _set_drop_target_index(self, index):
        if index == self._drop_target_index:
            return
        old_index = self._drop_target_index
        self._drop_target_index = index if index.isValid() else QtCore.QModelIndex()
        self._update_drop_target_row(old_index)
        self._update_drop_target_row(self._drop_target_index)

    def _clear_drop_target_index(self):
        self._set_drop_target_index(QtCore.QModelIndex())

    def _update_drop_target_row(self, index):
        if not index.isValid():
            return
        rect = self.visualRect(index)
        if not rect.isValid():
            self.viewport().update()
            return
        self.viewport().update(QtCore.QRect(0, rect.top(), self.viewport().width(), rect.height()))

    def _update_drop_target_from_event(self, event):
        mime = event.mimeData()
        action = self._drop_action_for_event(event)
        index = self._resolve_drop_target_index(self._drop_event_pos(event), mime, action)
        self._set_drop_target_index(index)
        return index, action

    def _drop_on_target(self, pos, mime, action):
        index = self._resolve_drop_target_index(pos, mime, action)
        return self._drop_on_resolved_target(index, mime, action)

    def _drop_on_resolved_target(self, index, mime, action):
        if not index.isValid() or not self._drop_action_supported(action):
            return False
        return self.model_.dropMimeData(mime, action, -1, 0, index)

    def show_context_menu(self, position):
        from wafer.builtins.commands import foldertree

        gp = self.viewport().mapToGlobal(position)
        ctx = Context.create_menu_context(self, self.binding_scope(), pos=position, global_pos=gp)
        ctx.extras.update(self.extend_context(ctx, None, source="menu") or {})
        foldertree.show_context_menu(ctx)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        pos = ctx.get("pos") if hasattr(ctx, "get") else None
        idx = self.indexAt(pos).siblingAtColumn(0) if pos is not None else QtCore.QModelIndex()
        clicked = idx.data(USER_ROLE_PATH) if idx.isValid() else None
        selected = self.get_selected_paths()
        path = clicked or (selected[0] if selected else None)
        return {"path": path, "paths": selected, "source": path, "sources": selected}

    @profiler.profile
    def get_selected_paths(self):
        return [i.data(USER_ROLE_PATH) for i in self.selectionModel().selectedRows() if i.data(USER_ROLE_PATH)]

    def capture_scroll_state(self):
        bar = self.verticalScrollBar()
        return {
            "value": int(bar.value()),
            "maximum": int(bar.maximum()),
        }

    def restore_scroll_state(self, scroll_state):
        if not isinstance(scroll_state, dict):
            return
        try:
            saved_value = int(scroll_state.get("value", 0))
        except (TypeError, ValueError):
            saved_value = 0
        self._scroll_restore_serial += 1
        serial = self._scroll_restore_serial

        def apply_scroll():
            if serial != self._scroll_restore_serial:
                return
            bar = self.verticalScrollBar()
            bar.setValue(max(0, min(saved_value, bar.maximum())))

        QtCore.QTimer.singleShot(0, self, apply_scroll)

    def set_folders(self, roots, excluded=None, ignore_pattern_re=None):
        roots = [normalize_path(r) for r in roots]
        excluded = set(normalize_path(e) for e in excluded or [])
        self._reset_folders(roots, excluded, ignore_pattern_re, scan_roots(roots, excluded, ignore_pattern_re))
        self.folders_set.emit()

    def _reset_folders(self, roots, excluded, ignore_pattern_re, root_entries):
        self._reload_cancel.cancel()
        self._cancel_recursive_expand_jobs()
        model = self.model_
        model.clear()
        model.clear_cache()
        model.roots = roots
        model.excluded = excluded
        model.ignore_pattern_re = ignore_pattern_re
        model.reset_header()
        model.append_roots(root_entries)

    def reload_folders_async(self, load_settings=None, on_complete=None):
        cancel = self._reload_cancel.renew()
        model = self.model_
        current_settings = (list(model.roots or ()), set(model.excluded), model.ignore_pattern_re)
        structure = self.structure_snapshot() if load_settings is not None else None
        expanded, selected = self.get_state()
        wanted = [*expanded, *selected]
        dispatcher = model._dispatcher

        def task():
            roots, excluded, ignore_pattern_re = load_settings() if load_settings is not None else current_settings
            roots = [normalize_path(r) for r in roots]
            excluded = set(normalize_path(e) for e in excluded or [])
            if structure is not None and structure_is_current(structure, roots, excluded, ignore_pattern_re):
                dispatcher.invoke(lambda: self._finish_reload(cancel, roots, on_complete))
                return
            root_entries = scan_roots(roots, excluded, ignore_pattern_re)
            segments = _collect_segments_for_paths(wanted, [root for root, _has_subfolders in root_entries])
            children_map = {seg: _scan_children(seg, excluded, ignore_pattern_re) for seg in segments if not cancel.is_cancelled()}
            dispatcher.invoke(lambda: self._apply_reload(cancel, (roots, excluded, ignore_pattern_re), root_entries, children_map, load_settings, on_complete))

        dispatcher.post(task, priority=8, cancel=cancel)

    def _finish_reload(self, cancel, roots, on_complete):
        if not cancel.is_cancelled() and on_complete is not None:
            on_complete(roots)

    def _apply_reload(self, cancel, settings, root_entries, children_map, load_settings, on_complete):
        if cancel.is_cancelled():
            return
        if self.defer_reload_if_editing(lambda: self.reload_folders_async(load_settings, on_complete), strong=load_settings is not None):
            return
        expanded, selected = self.get_state()
        needed = _collect_segments_for_paths([*expanded, *selected], [root for root, _has_subfolders in root_entries])
        if any(seg not in children_map for seg in needed):
            self.reload_folders_async(load_settings, on_complete)
            return
        scroll_state = self.capture_scroll_state()
        roots = settings[0]
        self._reset_folders(*settings, root_entries)
        self._apply_children_map(children_map)
        self._expand_loaded_paths(expanded)
        self._select_loaded_paths(selected, scroll=False)
        self.restore_scroll_state(scroll_state)
        if load_settings is not None:
            self.folders_set.emit()
        if on_complete is not None:
            on_complete(roots)

    def _iter_inline_editors(self):
        seen = set()
        for editor_type in INLINE_EDITOR_TYPES:
            for editor in self.findChildren(editor_type):
                editor_id = id(editor)
                if editor_id in seen:
                    continue
                seen.add(editor_id)
                yield editor

    def _has_live_inline_editor(self):
        app = QtWidgets.QApplication.instance()
        focus = app.focusWidget() if app is not None else None
        if isinstance(focus, INLINE_EDITOR_TYPES) and self.isAncestorOf(focus):
            return True
        for editor in self._iter_inline_editors():
            try:
                if editor.isVisible() and self.isAncestorOf(editor):
                    return True
            except RuntimeError:
                continue
        return False

    def is_editing(self):
        try:
            return self.state() == QtWidgets.QAbstractItemView.EditingState or self._has_live_inline_editor()
        except RuntimeError:
            return False

    def defer_reload_if_editing(self, callback, *, strong=False):
        if not callable(callback) or not self.is_editing():
            return False
        if strong:
            self._pending_reload_strong_callback = callback
        else:
            self._pending_reload_local_callback = callback
        return True

    def has_pending_reload(self):
        return self._pending_reload_local_callback is not None or self._pending_reload_strong_callback is not None

    def _schedule_pending_reload(self):
        if not self.has_pending_reload() or self._pending_reload_scheduled:
            return
        self._pending_reload_scheduled = True
        QtCore.QTimer.singleShot(0, self._flush_pending_reload)

    def _flush_pending_reload(self):
        self._pending_reload_scheduled = False
        if not self.has_pending_reload():
            return
        if self.is_editing():
            self._schedule_pending_reload()
            return
        callback = self._pending_reload_strong_callback or self._pending_reload_local_callback
        self._pending_reload_local_callback = None
        self._pending_reload_strong_callback = None
        if callback is not None:
            callback()

    def _child_paths_state(self, item):
        if item.rowCount() == 1:
            placeholder = item.child(0)
            if placeholder is not None and not placeholder.data(USER_ROLE_PATH):
                return None
        child_paths = []
        for i in range(item.rowCount()):
            child = item.child(i)
            child_path = child.data(USER_ROLE_PATH) if child is not None else None
            if child_path:
                child_paths.append(normalize_path(child_path))
        return tuple(child_paths)

    def structure_snapshot(self):
        model = self.model_
        root_items = [item for item in iter_root_items(model) if item.data(USER_ROLE_PATH)]
        loaded_children = {}
        stack = list(root_items)
        while stack:
            item = stack.pop()
            path = item.data(USER_ROLE_PATH)
            child_paths = self._child_paths_state(item) if path else None
            if child_paths is None:
                continue
            loaded_children[normalize_path(path)] = child_paths
            stack.extend(item.child(i) for i in range(item.rowCount()))
        pattern = model.ignore_pattern_re.pattern if model.ignore_pattern_re is not None else None
        roots = tuple(normalize_path(item.data(USER_ROLE_PATH)) for item in root_items)
        return FolderStructure(roots, frozenset(model.excluded), pattern, loaded_children)

    @property
    def roots(self):
        return self.model_.roots

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
        expanded = [normalize_path(p) for p in expanded]
        selected = [normalize_path(p) for p in selected]

        def apply():
            self._expand_loaded_paths(expanded)
            self._select_loaded_paths(selected)
            if on_complete:
                on_complete()

        self.load_paths_async(list(dict.fromkeys(expanded + selected)), apply)

    def expand_paths_async(self, paths, on_complete=None):
        normalized = list(dict.fromkeys(normalize_path(p) for p in paths if p))
        if not normalized:
            if on_complete:
                on_complete()
            return

        def apply():
            self._expand_loaded_paths(normalized)
            if on_complete:
                on_complete()

        self.load_paths_async(normalized, apply, skip_loaded=True)

    def load_paths_async(self, paths, on_loaded, *, skip_loaded=False):
        model = self.model_
        roots = [normalize_path(r) for r in model.roots]
        segments = _collect_segments_for_paths(paths, roots)
        if skip_loaded:
            segments = [seg for seg in segments if not model.children_loaded(model.path_item_map.get(seg))]
        excluded = set(model.excluded)
        ignore_pattern_re = model.ignore_pattern_re
        dispatcher = model._dispatcher

        def task():
            children_map = {seg: _scan_children(seg, excluded, ignore_pattern_re) for seg in segments}
            dispatcher.invoke(lambda: self._apply_loaded_children(children_map, on_loaded))

        dispatcher.post(task, priority=8)

    def _apply_children_map(self, children_map):
        model = self.model_
        for seg_path, children in children_map.items():
            item = model.path_item_map.get(seg_path)
            if model._is_valid_item(item) and not model.children_loaded(item):
                model._apply_children(item, seg_path, children)

    def _apply_loaded_children(self, children_map, on_loaded):
        self._apply_children_map(children_map)
        on_loaded()

    def _loaded_index(self, path):
        item = self.model_.path_item_map.get(path)
        if not self.model_._is_valid_item(item):
            return None
        index = self.model_.indexFromItem(item)
        return index if index.isValid() else None

    def _expand_loaded_paths(self, paths):
        self._programmatic_expand += 1
        try:
            for path in paths:
                index = self._loaded_index(path)
                if index is not None:
                    self.expand(index)
        finally:
            self._programmatic_expand -= 1

    def _select_indexes(self, indexes, current):
        selection = QtCore.QItemSelection()
        for index in indexes:
            selection.select(index, index)
        sel_model = self.selectionModel()
        sel_model.select(selection, QtCore.QItemSelectionModel.ClearAndSelect | QtCore.QItemSelectionModel.Rows)
        if current is not None:
            sel_model.setCurrentIndex(current, QtCore.QItemSelectionModel.NoUpdate)

    def _select_loaded_paths(self, paths, scroll=True):
        to_select = [index for index in map(self._loaded_index, paths) if index is not None]
        first = to_select[0] if to_select else None
        self._select_indexes(to_select, first)
        if first is not None and scroll:
            self.scrollTo(first, QtWidgets.QAbstractItemView.PositionAtCenter)

    @profiler.profile
    def expand_and_select_path(self, path, on_complete=None, emit_selected=True, expand_target=True):
        self.expand_and_select_paths([path], on_complete=on_complete, emit_selected=emit_selected, expand_target=expand_target)

    @profiler.profile
    def expand_and_select_paths(self, paths, on_complete=None, emit_selected=True, expand_target=True):
        normalized = list(dict.fromkeys(normalize_path(p) for p in paths if p))
        if not normalized:
            if on_complete:
                on_complete()
            return
        self.load_paths_async(normalized, lambda: self._apply_expand_and_select(normalized, on_complete, emit_selected, expand_target))

    def _apply_expand_and_select(self, paths, on_complete, emit_selected, expand_target):
        to_select = []
        self._programmatic_expand += 1
        try:
            for path in paths:
                index = self._loaded_index(path)
                if index is None:
                    AppLogger.debug(f"[FolderTree.expand_and_select_paths] not found: {path}")
                    continue
                parents = []
                parent = index.parent()
                while parent.isValid():
                    parents.append(parent)
                    parent = parent.parent()
                for parent in reversed(parents):
                    self.expand(parent)
                if expand_target:
                    self.expand(index)
                to_select.append(index)
        finally:
            self._programmatic_expand -= 1
        last = to_select[-1] if to_select else None
        self._select_indexes(to_select, last)
        if last is not None:
            QtCore.QTimer.singleShot(0, self, lambda: self.scrollTo(last, QtWidgets.QAbstractItemView.PositionAtCenter))
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
        self.model_.roots.append(path)
        self.model_.insert_root(path, self.model_.has_subfolders(path))

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
        if self.defer_reload_if_editing(self.reload_tree):
            return
        self.reload_folders_async()

    def dragEnterEvent(self, event):
        md = event.mimeData()
        action = self._drop_action_for_event(event)
        if self._drop_mime_supported(md) and self._drop_action_supported(action):
            event.setDropAction(action)
            event.accept()
        else:
            self._clear_drop_target_index()
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        super().dragMoveEvent(event)
        index, action = self._update_drop_target_from_event(event)
        if index.isValid() and self._drop_action_supported(action):
            event.setDropAction(action)
            event.accept()
            return
        self._clear_drop_target_index()
        ignore = getattr(event, "ignore", None)
        if callable(ignore):
            ignore()

    def dragLeaveEvent(self, event):
        self._clear_drop_target_index()
        super().dragLeaveEvent(event)

    def dropEvent(self, event):
        try:
            mime = event.mimeData()
            if self._drop_mime_supported(mime):
                action = self._drop_action_for_event(event)
                if self._drop_action_supported(action):
                    index = self._resolve_drop_target_index(self._drop_event_pos(event), mime, action)
                    self._clear_drop_target_index()
                    self._drop_on_resolved_target(index, mime, action)
            else:
                super().dropEvent(event)
        finally:
            self._clear_drop_target_index()
            event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)

    def commitData(self, editor):
        super().commitData(editor)
        self._schedule_pending_reload()

    def closeEditor(self, editor, hint):
        super().closeEditor(editor, hint)
        self._schedule_pending_reload()

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
        ignore_pattern_re = self.model_.ignore_pattern_re
        dispatcher = self.model_._dispatcher

        def task():
            batch = []

            stack = [root_path]
            while stack:
                if cancel.is_cancelled():
                    dispatcher.invoke(lambda: self._finish_expand_recursive_job(root_path))
                    return
                path = stack.pop()
                children = _scan_children(path, excluded, ignore_pattern_re)
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
        if not model.children_loaded(item):
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

    def current_folder_index(self):
        return self.currentIndex().siblingAtColumn(0)

    def current_path(self) -> str | None:
        idx = self.current_folder_index()
        return idx.data(USER_ROLE_PATH) if idx.isValid() else None

    def _select_path_for_navigation(self, path, trigger_search=True):
        if not path:
            return None
        path = normalize_path(path)
        self.expand_and_select_paths([path], on_complete=lambda: self.current_path_changed.emit(path), emit_selected=trigger_search, expand_target=False)
        return path

    def _select_index_for_navigation(self, index, trigger_search=True):
        if not index.isValid():
            return None
        path = index.data(USER_ROLE_PATH)
        if not path:
            return None
        self._select_indexes([index], index)
        self.scrollTo(index, QtWidgets.QAbstractItemView.PositionAtCenter)
        if trigger_search:
            self.folder_selected.emit()
        self.current_path_changed.emit(path)
        return path

    def _sibling_index(self, index, offset):
        if not index.isValid():
            return QtCore.QModelIndex()
        parent = index.parent()
        row = index.row() + offset
        if row < 0 or row >= self.model().rowCount(parent):
            return QtCore.QModelIndex()
        return self.model().index(row, 0, parent)

    @profiler.profile
    def navigate_next_folder(self, trigger_search=True) -> str | None:
        idx = self.current_folder_index()
        if not idx.isValid():
            first = self.model().index(0, 0)
            if first.isValid():
                return self._select_index_for_navigation(first, trigger_search=trigger_search)
            return None
        return self._select_index_for_navigation(self._sibling_index(idx, 1), trigger_search=trigger_search)

    @profiler.profile
    def navigate_prev_folder(self, trigger_search=True) -> str | None:
        idx = self.current_folder_index()
        if not idx.isValid():
            return None
        return self._select_index_for_navigation(self._sibling_index(idx, -1), trigger_search=trigger_search)

    @profiler.profile
    def navigate_parent(self, trigger_search=True, collapse=False) -> str | None:
        idx = self.current_folder_index()
        if not idx.isValid():
            return None
        parent = idx.parent()
        if parent.isValid():
            path = self._select_index_for_navigation(parent, trigger_search=trigger_search)
            if collapse and path:
                self.collapse(parent)
            return path
        return None

    @profiler.profile
    def navigate_child(self, trigger_search=True) -> str | None:
        idx = self.current_folder_index()
        if not idx.isValid():
            return None
        item = self.model_.itemFromIndex(idx)
        if item is None or not item.rowCount():
            return None
        if self.model_.children_loaded(item):
            return self._select_first_child(item, trigger_search)
        path = normalize_path(item.data(USER_ROLE_PATH))
        self.load_paths_async([path], lambda: self._select_first_child(self.model_.path_item_map.get(path), trigger_search), skip_loaded=True)
        return None

    def _select_first_child(self, item, trigger_search):
        if not self.model_.children_loaded(item):
            return None
        self._programmatic_expand += 1
        try:
            self.expand(self.model_.indexFromItem(item))
        finally:
            self._programmatic_expand -= 1
        return self._select_index_for_navigation(self.model_.indexFromItem(item.child(0)), trigger_search=trigger_search)

    def _root_paths(self):
        return [path for item in iter_root_items(self.model_) if (path := item.data(USER_ROLE_PATH))]

    @staticmethod
    def _deepest_last(path, excluded, ignore_pattern_re=None):
        while True:
            children = _scan_child_paths(path, excluded, ignore_pattern_re)
            if not children:
                return path
            path = children[-1]

    @profiler.profile
    def navigate_next_dfs(self, trigger_search=True) -> str | None:
        sorted_roots = self._root_paths()
        current = self.current_path()
        if not current:
            return self._select_path_for_navigation(sorted_roots[0], trigger_search=trigger_search) if sorted_roots else None

        current = normalize_path(current)
        excluded = self.model_.excluded
        ignore_pattern_re = self.model_.ignore_pattern_re
        roots_set = set(sorted_roots)

        children = _scan_child_paths(current, excluded, ignore_pattern_re)
        if children:
            return self._select_path_for_navigation(children[0], trigger_search=trigger_search)

        path = current
        while True:
            if path in roots_set:
                idx = sorted_roots.index(path)
                if idx + 1 < len(sorted_roots):
                    return self._select_path_for_navigation(sorted_roots[idx + 1], trigger_search=trigger_search)
                return None
            parent = normalize_path(os.path.dirname(path))
            if parent == path:
                return None
            siblings = _scan_child_paths(parent, excluded, ignore_pattern_re)
            if path in siblings:
                idx = siblings.index(path)
                if idx + 1 < len(siblings):
                    return self._select_path_for_navigation(siblings[idx + 1], trigger_search=trigger_search)
            path = parent

    @profiler.profile
    def navigate_prev_dfs(self, trigger_search=True) -> str | None:
        current = self.current_path()
        if not current:
            return None

        current = normalize_path(current)
        excluded = self.model_.excluded
        ignore_pattern_re = self.model_.ignore_pattern_re
        sorted_roots = self._root_paths()

        if current in sorted_roots:
            idx = sorted_roots.index(current)
            if idx > 0:
                return self._select_path_for_navigation(self._deepest_last(sorted_roots[idx - 1], excluded, ignore_pattern_re), trigger_search=trigger_search)
            return None

        parent = normalize_path(os.path.dirname(current))
        siblings = _scan_child_paths(parent, excluded, ignore_pattern_re)
        if current in siblings:
            idx = siblings.index(current)
            if idx > 0:
                return self._select_path_for_navigation(self._deepest_last(siblings[idx - 1], excluded, ignore_pattern_re), trigger_search=trigger_search)
        return self._select_path_for_navigation(parent, trigger_search=trigger_search)

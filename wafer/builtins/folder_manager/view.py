import posixpath
from collections.abc import Callable, Sequence

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.app.viewer.widgets.foldertree import EXPAND_RECURSIVE_BATCH_SIZE, USER_ROLE_PATH, LazyFolderTreeModel, LazyFolderTreeView
from wafer.builtins.commands.foldertree import folder_file_items, run_on_folder_files
from wafer.core.common.paths import child_prefix, normalize_path
from wafer.core.lang.manager import t
from wafer.qt.commands.bridge import ActionKit, Context, Menu
from wafer.qt.common.dpi import dpix

from .rules import METRICS, HighlightRule
from .stats import DiskTree, FolderValues

DISK_TOOLTIP = "Count on disk"
BADGE_TEXT_COLOR = QtGui.QColor("#ffffff")
RULE_FILE_ACTIONS = (
    ("cut_direct", "{rule} · Cut direct files", "file.cut", False),
    ("copy_direct", "{rule} · Copy direct files", "file.copy", False),
    ("cut_all", "{rule} · Cut all files below", "file.cut", True),
    ("copy_all", "{rule} · Copy all files below", "file.copy", True),
)
DISK_METRICS = ("folders", "all_folders")
UNSCANNED = object()

Badge = tuple[str, str | None]


class FolderStatsModel(LazyFolderTreeModel):
    EXTRA_COLUMNS = ("Files", "All files", "Folders", "All folders")
    paths_changed = QtCore.Signal(list)
    stats_changed = QtCore.Signal()

    def __init__(self, roots, excluded=None, ignore_pattern_re=None):
        super().__init__(roots, excluded, ignore_pattern_re)
        self.disk: DiskTree | None = None
        self.rule_counts: list[tuple[HighlightRule, dict[str, tuple[int, int]]]] = []
        self.values_cache: dict[str, FolderValues | None] = {}

    def refresh_stats(self) -> None:
        self.values_cache.clear()
        self.stats_changed.emit()

    def disk_values(self, path: str) -> FolderValues | None:
        values = self.values_cache.get(path, UNSCANNED)
        if values is UNSCANNED:
            values = self.disk.values(path) if self.disk is not None else None
            self.values_cache[path] = values
        return values

    def data(self, index, role=QtCore.Qt.DisplayRole):
        column = index.column()
        if column == 0:
            return super().data(index, role)
        if role == QtCore.Qt.DisplayRole:
            return self.disk_text(index.siblingAtColumn(0).data(USER_ROLE_PATH), column)
        if role == QtCore.Qt.ToolTipRole:
            return DISK_TOOLTIP
        if role == QtCore.Qt.TextAlignmentRole:
            return int(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        return super().data(index, role)

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role == QtCore.Qt.ToolTipRole and orientation == QtCore.Qt.Horizontal and section > 0:
            return DISK_TOOLTIP
        return super().headerData(section, orientation, role)

    def disk_text(self, path: str | None, column: int) -> str:
        values = self.disk_values(path) if path else None
        if values is None:
            return ""
        value = getattr(values, METRICS[column - 1])
        return "" if value < 0 else f"{value:,}"

    def badges(self, path: str) -> list[Badge]:
        values = self.disk_values(path)
        unknown = set(DISK_METRICS) if values is None else {metric for metric in DISK_METRICS if getattr(values, metric) < 0}
        folders, all_folders = (values.folders, values.all_folders) if values is not None else (0, 0)
        found = []
        for rule, counts in self.rule_counts:
            if not rule.enabled:
                continue
            if unknown and any(condition.metric in unknown for condition in rule.conditions):
                continue
            direct, total = counts.get(path, (0, 0))
            if rule.matches(FolderValues(direct, total, folders, all_folders)):
                found.append((rule.color, str(direct) if rule.shows_count() else None))
        return found

    def _rename_item(self, item, new_name):
        old_path = normalize_path(item.data(USER_ROLE_PATH))
        renamed = super()._rename_item(item, new_name)
        if renamed and self._is_valid_item(item) and normalize_path(item.data(USER_ROLE_PATH)) != old_path:
            self.paths_changed.emit([posixpath.dirname(old_path)])
        return renamed

    def _move_item(self, item, new_parent_item):
        old_path = normalize_path(item.data(USER_ROLE_PATH))
        moved = super()._move_item(item, new_parent_item)
        if not moved:
            return moved
        new_parent = normalize_path(new_parent_item.data(USER_ROLE_PATH))
        old_parent = posixpath.dirname(old_path)
        if new_parent != old_parent:
            self.paths_changed.emit([old_parent, new_parent])
        return moved


class BadgeDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, badges_for: Callable[[str], list[Badge]], parent=None):
        super().__init__(parent)
        self.badges_for = badges_for

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        path = index.data(USER_ROLE_PATH)
        badges = self.badges_for(path) if path else None
        if not badges:
            return
        opt = QtWidgets.QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        widget = opt.widget
        style = widget.style() if widget is not None else QtWidgets.QApplication.style()
        text_rect = style.subElementRect(QtWidgets.QStyle.SE_ItemViewItemText, opt, widget)
        margin = style.pixelMetric(QtWidgets.QStyle.PM_FocusFrameHMargin, None, widget) + 1
        metrics = QtGui.QFontMetrics(opt.font)
        gap = dpix(4)
        x = text_rect.left() + margin + min(metrics.horizontalAdvance(opt.text), text_rect.width()) + gap
        center_y = QtCore.QRectF(option.rect).center().y()
        height = max(dpix(10), metrics.height() - dpix(2))
        painter.save()
        painter.setClipRect(option.rect)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setFont(opt.font)
        for color, label in badges:
            if x >= option.rect.right():
                break
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(color))
            if label is None:
                size = dpix(10)
                painter.drawEllipse(QtCore.QRectF(x, center_y - size / 2, size, size))
                x += size + gap
                continue
            width = max(height, metrics.horizontalAdvance(label) + dpix(10))
            rect = QtCore.QRectF(x, center_y - height / 2, width, height)
            painter.drawRoundedRect(rect, height / 2, height / 2)
            painter.setPen(BADGE_TEXT_COLOR)
            painter.drawText(rect, QtCore.Qt.AlignCenter, label)
            x += width + gap
        painter.restore()


def ancestors_within_roots(path: str, roots: Sequence[str]) -> list[str]:
    root = max((r for r in roots if path.startswith(child_prefix(r))), key=len, default=None)
    if root is None:
        return []
    chain = []
    current = path
    while current != root:
        current = posixpath.dirname(current)
        chain.append(current)
    return chain[::-1]


class FolderManagerTreeView(LazyFolderTreeView):
    MODEL_CLASS = FolderStatsModel
    BINDING_SCOPE = "FolderManagerTree"

    def __init__(self, roots=None, excluded=None, ignore_pattern_re=None):
        super().__init__(roots, excluded, ignore_pattern_re, instance_name="FolderManagerTree")
        self.rules_source: Callable[[], list[HighlightRule]] = list
        self.hidden_columns: set[int] = set()
        self.expand_serial = 0
        self.setHeaderHidden(False)
        self.setItemDelegateForColumn(0, BadgeDelegate(self.model_.badges, self))
        self.header().setStretchLastSection(False)
        self.model_.columnsInserted.connect(self.apply_header)
        self.model_.stats_changed.connect(self.on_stats_changed)
        self.apply_header()

    def apply_header(self, *_):
        header = self.header()
        header.setSectionResizeMode(QtWidgets.QHeaderView.ResizeToContents)
        header.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        for column in range(1, self.model_.columnCount()):
            self.setColumnHidden(column, column in self.hidden_columns)

    def on_stats_changed(self) -> None:
        self.header().resizeSections()
        self.viewport().update()

    def set_column_visible(self, column: int, visible: bool) -> None:
        if column == 0:
            return
        if visible:
            self.hidden_columns.discard(column)
        else:
            self.hidden_columns.add(column)
        self.setColumnHidden(column, not visible)

    def set_rules_source(self, rules: Callable[[], list[HighlightRule]]) -> None:
        self.rules_source = rules

    def show_context_menu(self, position):
        gp = self.viewport().mapToGlobal(position)
        ctx = Context.create_menu_context(self, self.binding_scope(), pos=position, global_pos=gp)
        ctx.extras.update(self.extend_context(ctx, None, source="menu") or {})
        if not ctx.get("path"):
            return
        items = ["ft.show_in_tree", "-", *folder_file_items()]
        last_files_item = max(n for n, item in enumerate(items) if item.startswith("Files in Folder/"))
        items[last_files_item + 1 : last_files_item + 1] = self.rule_file_actions()
        session = Menu.from_context(ctx)
        if session is None:
            return
        spec = session.menu(items)
        if spec is not None:
            spec.exec()

    def rule_file_actions(self) -> list:
        actions = []
        labels = set()
        for number, rule in enumerate(self.rules_source()):
            entries = rule.filter_entries() if rule.enabled else []
            if not entries:
                continue
            label = rule.name.strip() or f"Rule {number + 1}"
            if label in labels:
                label = f"{label} ({number + 1})"
            labels.add(label)
            actions.append("Files in Folder/-")
            for key, template, command_id, recursive in RULE_FILE_ACTIONS:
                actions.append(
                    ActionKit.Action(
                        path=f"Files in Folder/inline.folder_manager.rule{number}.{key}",
                        display=t(template, rule=label),
                        translate=False,
                        func=lambda ctx, entries=entries, command_id=command_id, recursive=recursive: self.run_rule_file_action(ctx, entries, command_id, recursive),
                    )
                )
        return actions

    def run_rule_file_action(self, ctx, entries: list[tuple], command_id: str, recursive: bool) -> None:
        ctx.extras["filter_entries"] = entries
        run_on_folder_files(ctx, command_id, recursive)

    def expand_to(self, paths: Sequence[str]) -> None:
        roots = [normalize_path(root) for root in self.model_.roots or ()]
        ancestors = list(dict.fromkeys(a for path in paths for a in ancestors_within_roots(normalize_path(path), roots)))
        batch_size = EXPAND_RECURSIVE_BATCH_SIZE
        chunks = [ancestors[i : i + batch_size] for i in range(0, len(ancestors), batch_size)]
        self.expand_serial += 1
        serial = self.expand_serial

        def expand_chunk(number: int) -> None:
            if serial != self.expand_serial or number >= len(chunks):
                return
            self.expand_paths_async(chunks[number], on_complete=lambda: expand_chunk(number + 1))

        expand_chunk(0)

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from ...utils.formatting import dpix
from ...core.color.theme import ThemeManager

if TYPE_CHECKING:
    from .engine import RenameResult, RenameColumn


INLINE_EDITOR_TYPES = (
    QtWidgets.QLineEdit,
    QtWidgets.QPlainTextEdit,
    QtWidgets.QTextEdit,
    QtWidgets.QComboBox,
    QtWidgets.QAbstractSpinBox,
)


class PreviewModel(QtCore.QAbstractTableModel):
    HEADERS = ["Original", "Result"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[RenameResult] = []
        self._colors: ColorSet | None = None

    def set_colors(self, colors: ColorSet):
        self._colors = colors

    def refresh(self, results: list[RenameResult]):
        self.beginResetModel()
        self._results = results
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._results)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else 2

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            if section < 2:
                return self.HEADERS[section]
            return ""
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        r = self._results[index.row()]
        col = index.column()
        if role == Qt.DisplayRole:
            if col == 0:
                return r.original
            has_issue = r.conflict or r.errors or r.missing
            if r.missing:
                return f"\u2716 {r.new_name}"
            if has_issue:
                return f"\u26a0 {r.new_name}"
            return r.new_name
        c = self._colors
        if c is None:
            return None
        has_issue = r.conflict or r.errors or r.missing
        if role == Qt.ForegroundRole:
            if col == 0:
                return c.missing_fg if r.missing else c.muted
            return c.warn if has_issue else c.accent
        if role == Qt.BackgroundRole:
            if col == 1 and has_issue:
                return c.err_bg
            return None
        if role == Qt.FontRole:
            if col == 0 and r.missing:
                return c.strikeout_font
        return None

    def flags(self, index):
        return Qt.ItemIsEnabled | Qt.ItemIsSelectable


class SegmentModel(QtCore.QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: list[RenameResult] = []
        self._columns: list[RenameColumn] = []
        self._ext_column: RenameColumn | None = None
        self._headers: list[str] = []
        self._add_section = 0
        self._ext_section = 1
        self._colors: ColorSet | None = None
        self._paths: list = []

    def set_colors(self, colors: ColorSet):
        self._colors = colors

    def configure(
        self,
        columns: list[RenameColumn],
        ext_column: RenameColumn,
        add_label: str,
        ext_label: str,
    ):
        self.beginResetModel()
        self._columns = columns
        self._ext_column = ext_column
        self._add_section = len(columns)
        self._ext_section = len(columns) + 1
        self._build_headers(add_label, ext_label)
        self.endResetModel()

    def _build_headers(self, add_label: str = "", ext_label: str = ""):
        if not add_label and self._headers:
            add_label = self._headers[self._add_section] if self._add_section < len(self._headers) else ""
        if not ext_label and self._ext_column:
            ext_label = self._ext_column.source.DISPLAY
        headers = []
        for col in self._columns:
            prefix = "" if col.enabled else "\u25cc "
            headers.append(f"{prefix}{col.source.DISPLAY}")
        headers.append(add_label)
        headers.append(ext_label)
        self._headers = headers

    def refresh(self, results: list[RenameResult], paths: list | None = None):
        self.beginResetModel()
        self._results = results
        if paths is not None:
            self._paths = paths
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._results)

    def columnCount(self, parent=QtCore.QModelIndex()):
        return 0 if parent.isValid() else len(self._headers)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self._headers[section] if section < len(self._headers) else ""
        return None

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None
        row, col = index.row(), index.column()
        r = self._results[row]
        seg_n = len(self._columns)

        if col == self._add_section:
            return None

        if role in (Qt.DisplayRole, Qt.EditRole):
            if col < seg_n:
                return r.segments[col] if col < len(r.segments) else ""
            if col == self._ext_section:
                return r.segments[-1] if r.segments else ""
            return None

        c = self._colors
        if c is None:
            return None
        has_issue = r.conflict or r.errors or r.missing

        if role == Qt.ForegroundRole:
            if col < seg_n:
                if not self._columns[col].enabled:
                    return c.disabled_fg
                if self._is_overridden(row, col):
                    return c.overridden_fg
                return c.warn if has_issue else c.ok
            if col == self._ext_section:
                if self._is_overridden(row, col):
                    return c.overridden_fg
                return c.warn if has_issue else c.ok
            return None

        if role == Qt.BackgroundRole:
            if col == self._ext_section:
                return c.ext_bg
            return None

        return None

    def flags(self, index):
        col = index.column()
        base = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if col < self._add_section or col == self._ext_section:
            return base | Qt.ItemIsEditable
        return base

    def setData(self, index, value, role=Qt.EditRole):
        if role != Qt.EditRole:
            return False
        col = index.column()
        row = index.row()
        if col < self._add_section:
            self._results[row].segments[col] = str(value)
            self.dataChanged.emit(index, index, [Qt.DisplayRole])
            return True
        if col == self._ext_section and self._results[row].segments:
            self._results[row].segments[-1] = str(value)
            self.dataChanged.emit(index, index, [Qt.DisplayRole])
            return True
        return False

    def _is_overridden(self, row, col):
        if not self._paths or row >= len(self._paths):
            return False
        key = str(self._paths[row])
        if col < len(self._columns):
            return key in self._columns[col].overrides
        if col == self._ext_section and self._ext_column is not None:
            return key in self._ext_column.overrides
        return False


class ColorSet:
    __slots__ = (
        "accent",
        "disabled_fg",
        "err_bg",
        "ext_bg",
        "missing_fg",
        "muted",
        "ok",
        "overridden_fg",
        "strikeout_font",
        "warn",
    )

    def __init__(self, palette, mono_font: QtGui.QFont):
        self.muted = QtGui.QColor(palette.text_muted)
        self.warn = QtGui.QColor(palette.warning)
        self.ok = QtGui.QColor(palette.text_primary)
        self.accent = QtGui.QColor(palette.text_accent)
        self.err_bg = QtGui.QBrush(QtGui.QColor(palette.bg_hover))
        self.disabled_fg = QtGui.QColor(palette.text_muted)
        self.ext_bg = QtGui.QBrush(QtGui.QColor(palette.bg_secondary))
        self.missing_fg = QtGui.QColor(palette.text_muted)
        self.overridden_fg = QtGui.QColor(palette.text_accent)
        f = QtGui.QFont(mono_font)
        f.setStrikeOut(True)
        self.strikeout_font = f


class PreviewDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._pen = QtGui.QPen(QtGui.QColor(color), dpix(1))

    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.column() == 0:
            painter.save()
            painter.setPen(self._pen)
            x = option.rect.right()
            painter.drawLine(x, option.rect.top(), x, option.rect.bottom())
            painter.restore()


class SyncedView(QtWidgets.QTableView):
    editing_finished = QtCore.Signal()
    rows_reordered = QtCore.Signal(list, int)

    def __init__(self, forward_target=None, parent=None, vertical_tab_navigation=False, row_wheel=False):
        super().__init__(parent)
        self._fwd = forward_target
        self._row_wheel = row_wheel
        self._vertical_tab_navigation = vertical_tab_navigation
        self._reorder_rows: list[int] = []
        self._reorder_active = False
        self._reorder_press_pos = QtCore.QPoint()
        self._drop_line = QtWidgets.QFrame(self.viewport())
        self._drop_line.setFrameShape(QtWidgets.QFrame.HLine)
        self._drop_line.setFixedHeight(dpix(2))
        self._drop_line.setStyleSheet(f"background: {ThemeManager.instance().palette.accent}; border: none;")
        self._drop_line.hide()

    def set_forward_target(self, target):
        self._fwd = target

    def set_vertical_tab_navigation(self, enabled):
        self._vertical_tab_navigation = enabled

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

    def _editor_index(self, editor):
        index = self.currentIndex()
        try:
            pos = editor.mapTo(self.viewport(), editor.rect().center())
            editor_index = self.indexAt(pos)
        except RuntimeError:
            editor_index = QtCore.QModelIndex()
        return editor_index if editor_index.isValid() else index

    def _vertical_tab_target(self, index, hint):
        if not index.isValid():
            return QtCore.QModelIndex()
        model = self.model()
        if model is None:
            return QtCore.QModelIndex()
        delta = 1 if hint == QtWidgets.QAbstractItemDelegate.EditNextItem else -1
        row = index.row() + delta
        if row < 0 or row >= model.rowCount(index.parent()):
            return QtCore.QModelIndex()
        target = model.index(row, index.column(), index.parent())
        if not target.isValid() or not (model.flags(target) & Qt.ItemIsEditable):
            return QtCore.QModelIndex()
        return target

    def _edit_after_close(self, row, column):
        model = self.model()
        if model is None:
            return
        target = model.index(row, column)
        if not target.isValid():
            return
        self.setCurrentIndex(target)
        self.scrollTo(target, QtWidgets.QAbstractItemView.EnsureVisible)
        self.edit(target)

    def commitData(self, editor):
        super().commitData(editor)

    def closeEditor(self, editor, hint):
        if self._vertical_tab_navigation and hint in (
            QtWidgets.QAbstractItemDelegate.EditNextItem,
            QtWidgets.QAbstractItemDelegate.EditPreviousItem,
        ):
            target = self._vertical_tab_target(self._editor_index(editor), hint)
            super().closeEditor(editor, QtWidgets.QAbstractItemDelegate.NoHint)
            if target.isValid():
                QtCore.QTimer.singleShot(0, lambda r=target.row(), c=target.column(): self._edit_after_close(r, c))
            self.editing_finished.emit()
            return
        super().closeEditor(editor, hint)
        self.editing_finished.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
            index = self.currentIndex()
            model = self.model()
            if index.isValid() and model is not None and model.flags(index) & Qt.ItemIsEditable:
                self.edit(index)
                event.accept()
                return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton:
            row = self.rowAt(event.position().toPoint().y())
            if row >= 0:
                sm = self.selectionModel()
                selected = {i.row() for i in sm.selectedIndexes()} if sm else set()
                self._reorder_rows = sorted(selected) if row in selected else [row]
                self._reorder_press_pos = event.position().toPoint()
                self._reorder_active = False
                event.accept()
                return
        if event.button() == QtCore.Qt.RightButton:
            idx = self.indexAt(event.position().toPoint())
            selection_model = self.selectionModel()
            if idx.isValid() and selection_model is not None and selection_model.isSelected(idx):
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._reorder_rows and event.buttons() & QtCore.Qt.MiddleButton:
            if not self._reorder_active:
                if (event.position().toPoint() - self._reorder_press_pos).manhattanLength() < QtWidgets.QApplication.startDragDistance():
                    return
                self._reorder_active = True
                self.setCursor(QtCore.Qt.ClosedHandCursor)
            self._update_drop_line(event.position().toPoint().y())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == QtCore.Qt.MiddleButton and self._reorder_rows:
            rows = self._reorder_rows
            active = self._reorder_active
            self._reorder_rows = []
            self._reorder_active = False
            self._drop_line.hide()
            self.unsetCursor()
            if active:
                target = self._drop_target(event.position().toPoint().y())
                self.rows_reordered.emit(rows, target)
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def _drop_target(self, y):
        model = self.model()
        total = model.rowCount() if model is not None else 0
        row = self.rowAt(y)
        if row < 0:
            return total
        rect = self.visualRect(model.index(row, 0))
        return row + 1 if y > rect.center().y() else row

    def _update_drop_line(self, y):
        model = self.model()
        if model is None:
            return
        target = self._drop_target(y)
        total = model.rowCount()
        if target >= total:
            rect = self.visualRect(model.index(total - 1, 0))
            line_y = rect.bottom()
        else:
            rect = self.visualRect(model.index(target, 0))
            line_y = rect.top()
        self._drop_line.setGeometry(0, line_y - dpix(1), self.viewport().width(), dpix(2))
        self._drop_line.show()
        self._drop_line.raise_()

    def wheelEvent(self, event):
        if self._fwd:
            sb = self._fwd.verticalScrollBar()
            row_h = self._fwd.verticalHeader().defaultSectionSize() or 1
            steps = event.angleDelta().y() // 120
            sb.setValue(sb.value() - steps * row_h)
            event.accept()
        elif self._row_wheel:
            sb = self.verticalScrollBar()
            row_h = self.verticalHeader().defaultSectionSize() or 1
            steps = event.angleDelta().y() // 120
            sb.setValue(sb.value() - steps * row_h)
            event.accept()
        else:
            super().wheelEvent(event)

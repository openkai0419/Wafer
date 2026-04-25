from __future__ import annotations

import itertools
from dataclasses import dataclass

from PySide6 import QtCore, QtGui, QtWidgets

from ....utils.formatting import dpix
from ....utils.logs import AppLogger
from ....core.lang.manager import t
from ....core.color.theme import ThemeManager
from ....core.qt.icon_engine import icon_draw, themed_icon
from ....ui.panel.meta_viewer import CollapsibleCard, truncate_text
from .tag_edit_service import TagEditService


_KEY_COL_MIN = 80
_KEY_COL_MAX = 220
_BTN_SIZE = 16


def _color_with_alpha(hex_color: str, alpha: int) -> str:
    c = QtGui.QColor(hex_color)
    return f"rgba({c.red()},{c.green()},{c.blue()},{alpha})"


def _label_bg_css() -> str:
    bg = ThemeManager.instance().palette.bg_secondary
    return f"QLabel {{ background-color: {bg}; border-radius: 3px; padding: 2px 4px;}}"


def _edit_bg_css() -> str:
    palette = ThemeManager.instance().palette
    return f"QLineEdit, QPlainTextEdit {{ background-color: {palette.bg_tertiary}; border: 1px solid {palette.border_default}; border-radius: 3px; padding: 1px 3px;}}"


@dataclass
class RowEdit:
    is_new: bool = False
    deleted: bool = False
    new_key: str | None = None
    new_value: str | None = None
    new_locked: bool | None = None
    initial_value: str = ""
    initial_locked: bool = False


@dataclass
class RowDisplay:
    row_id: str
    key: str
    value: str
    locked: bool
    deleted: bool
    added: bool
    edited: bool
    in_flight: str


class LineEditor(QtWidgets.QLineEdit):
    committed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self._cancelled = False
        self._committed = False
        self.setStyleSheet(_edit_bg_css())

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        if e.key() == QtCore.Qt.Key_Escape:
            self._cancelled = True
            self.cancelled.emit()
            return
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter):
            self._commit()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(e)
        if e.reason() == QtCore.Qt.PopupFocusReason:
            return
        self._commit()

    def _commit(self) -> None:
        if self._cancelled or self._committed:
            return
        self._committed = True
        self.committed.emit(self.text())


class PlainEditor(QtWidgets.QPlainTextEdit):
    committed = QtCore.Signal(str)
    cancelled = QtCore.Signal()

    _MIN_H = 60
    _MAX_H = 400

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
        self.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        self.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setPlainText(text)
        self._cancelled = False
        self._committed = False
        self.setStyleSheet(_edit_bg_css())
        self.document().contentsChanged.connect(self._adjust_height)
        QtCore.QTimer.singleShot(0, self, self._adjust_height)

    def _visual_line_count(self) -> int:
        doc = self.document()
        total = 0
        block = doc.firstBlock()
        while block.isValid():
            layout = block.layout()
            if layout is not None:
                total += max(1, layout.lineCount())
            else:
                total += 1
            block = block.next()
        return max(1, total)

    def _adjust_height(self) -> None:
        fm = self.fontMetrics()
        lines = self._visual_line_count()
        margin = self.contentsMargins()
        frame = self.frameWidth() * 2
        content = fm.lineSpacing() * lines + dpix(8)
        h = content + frame + margin.top() + margin.bottom()
        h = max(dpix(self._MIN_H), min(dpix(self._MAX_H), h))
        if h != self.height():
            self.setFixedHeight(h)
            self.updateGeometry()
        if h >= dpix(self._MAX_H):
            self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        else:
            self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)

    def sizeHint(self) -> QtCore.QSize:
        base = super().sizeHint()
        return QtCore.QSize(base.width(), self.height() if self.height() > 0 else dpix(self._MIN_H))

    def minimumSizeHint(self) -> QtCore.QSize:
        base = super().minimumSizeHint()
        return QtCore.QSize(base.width(), self.height() if self.height() > 0 else dpix(self._MIN_H))

    def resizeEvent(self, e: QtGui.QResizeEvent) -> None:
        super().resizeEvent(e)
        self._adjust_height()

    def keyPressEvent(self, e: QtGui.QKeyEvent) -> None:
        if e.key() == QtCore.Qt.Key_Escape:
            self._cancelled = True
            self.cancelled.emit()
            return
        if e.key() in (QtCore.Qt.Key_Return, QtCore.Qt.Key_Enter) and (e.modifiers() & QtCore.Qt.ControlModifier):
            self._commit()
            return
        super().keyPressEvent(e)

    def focusOutEvent(self, e: QtGui.QFocusEvent) -> None:
        super().focusOutEvent(e)
        if e.reason() == QtCore.Qt.PopupFocusReason:
            return
        self._commit()

    def _commit(self) -> None:
        if self._cancelled or self._committed:
            return
        self._committed = True
        self.committed.emit(self.toPlainText())


class _EditableCell(QtWidgets.QWidget):
    edit_committed = QtCore.Signal(str)

    def __init__(self, *, key_role: bool, editor_kind: str, parent=None):
        super().__init__(parent)
        self._raw = ""
        self._editing = False
        self._editor_kind = editor_kind
        self._key_role = key_role

        self._stack = QtWidgets.QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._label = QtWidgets.QLabel(self)
        self._label.setWordWrap(True)
        self._label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
        self._label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
        self._label.setTextFormat(QtCore.Qt.PlainText)
        self._label.setCursor(QtCore.Qt.IBeamCursor)
        self._label.setToolTip(t("Double-click to edit"))
        self._label.installEventFilter(self)
        self._extra_label_css = ""
        self._apply_label_style()
        self._stack.addWidget(self._label)

        self._editor: QtWidgets.QWidget | None = None

    def set_text(self, text: str) -> None:
        self._raw = text
        if not self._editing:
            self._label.setText(truncate_text(text))
            self._label.setToolTip(t("Double-click to edit"))

    def text(self) -> str:
        return self._raw

    def is_editing(self) -> bool:
        return self._editing

    def set_label_style(self, css: str) -> None:
        self._extra_label_css = css or ""
        self._apply_label_style()

    def _apply_label_style(self) -> None:
        self._label.setStyleSheet(_label_bg_css() + self._extra_label_css)

    def eventFilter(self, obj, ev):
        if obj is self._label and ev.type() == QtCore.QEvent.MouseButtonDblClick:
            self.start_edit()
            return True
        return super().eventFilter(obj, ev)

    def start_edit(self) -> None:
        if self._editing:
            return
        if self._editor_kind == "line":
            ed = LineEditor(self._raw, self)
        else:
            ed = PlainEditor(self._raw, self)
        ed.committed.connect(self._on_commit)
        ed.cancelled.connect(self._on_cancel)
        self._editor = ed
        self._stack.addWidget(ed)
        self._stack.setCurrentWidget(ed)
        ed.setFocus()
        if isinstance(ed, LineEditor):
            ed.selectAll()
        self._editing = True

    def _on_commit(self, text: str) -> None:
        if not self._editing:
            return
        new_text = text
        self._end_edit()
        if new_text != self._raw:
            self._raw = new_text
            self.set_text(new_text)
            self.edit_committed.emit(new_text)
        else:
            self.set_text(self._raw)

    def _on_cancel(self) -> None:
        self._end_edit()
        self.set_text(self._raw)

    def _end_edit(self) -> None:
        if self._editor is not None:
            self._stack.removeWidget(self._editor)
            self._editor.deleteLater()
            self._editor = None
        self._stack.setCurrentWidget(self._label)
        self._editing = False


class _LockButton(QtWidgets.QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setFixedSize(dpix(_BTN_SIZE), dpix(_BTN_SIZE))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(t("Lock tag from collector overwrite"))

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        palette = ThemeManager.instance().palette
        color = QtGui.QColor(palette.text_primary if self.isChecked() else palette.text_muted)
        if not self.isChecked():
            color.setAlpha(120)
        rect = QtCore.QRectF(0, 0, self.width(), self.height()).adjusted(2, 2, -2, -2)
        icon_draw("lock" if self.isChecked() else "lock_open", p, rect, color)
        p.end()


class _DeleteButton(QtWidgets.QToolButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setAutoRaise(True)
        self.setFixedSize(dpix(_BTN_SIZE), dpix(_BTN_SIZE))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setToolTip(t("Mark for deletion"))

    def paintEvent(self, _event):
        p = QtGui.QPainter(self)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        palette = ThemeManager.instance().palette
        if self.isChecked():
            color = QtGui.QColor(palette.error)
            icon_key = "refresh"
        else:
            color = QtGui.QColor(palette.text_muted)
            icon_key = "cross"
        rect = QtCore.QRectF(0, 0, self.width(), self.height()).adjusted(3, 3, -3, -3)
        icon_draw(icon_key, p, rect, color)
        p.end()


class _TagRow(QtWidgets.QFrame):
    key_committed = QtCore.Signal(str, str)
    value_committed = QtCore.Signal(str, str)
    lock_toggled = QtCore.Signal(str, bool)
    delete_toggled = QtCore.Signal(str, bool)

    def __init__(self, row_id: str, parent=None):
        super().__init__(parent)
        self._row_id = row_id
        self.setObjectName("editableTagRow")

        lay = QtWidgets.QHBoxLayout(self)
        lay.setContentsMargins(dpix(8), dpix(4), dpix(8), dpix(4))
        lay.setSpacing(dpix(12))

        self.key_cell = _EditableCell(key_role=True, editor_kind="line", parent=self)
        self.key_cell.edit_committed.connect(lambda v: self.key_committed.emit(self._row_id, v))

        self.value_cell = _EditableCell(key_role=False, editor_kind="plain", parent=self)
        self.value_cell.edit_committed.connect(lambda v: self.value_committed.emit(self._row_id, v))

        self.lock_btn = _LockButton(self)
        self.lock_btn.toggled.connect(lambda v: self.lock_toggled.emit(self._row_id, v))

        self.delete_btn = _DeleteButton(self)
        self.delete_btn.toggled.connect(lambda v: self.delete_toggled.emit(self._row_id, v))

        lay.addWidget(self.key_cell)
        lay.addWidget(self.value_cell, 1)
        lay.addWidget(self.lock_btn, 0, QtCore.Qt.AlignTop)
        lay.addWidget(self.delete_btn, 0, QtCore.Qt.AlignTop)

    def row_id(self) -> str:
        return self._row_id

    def set_data(self, d: RowDisplay, key_col_w: int) -> None:
        self.key_cell.setFixedWidth(key_col_w)
        self.key_cell.set_text(d.key)
        self.value_cell.set_text(d.value)
        self._block_and_set(self.lock_btn, d.locked)
        self._block_and_set(self.delete_btn, d.deleted)
        self._apply_state_style(d)

    @staticmethod
    def _block_and_set(btn: QtWidgets.QToolButton, value: bool) -> None:
        if btn.isChecked() == value:
            return
        btn.blockSignals(True)
        btn.setChecked(value)
        btn.blockSignals(False)

    def _apply_state_style(self, d: RowDisplay) -> None:
        palette = ThemeManager.instance().palette
        opacity = 1.0
        border = "none"
        bg = "transparent"
        if d.in_flight in ("saving",):
            opacity = 0.55
            border = "dashed"
        elif d.in_flight in ("save_failed", "delete_failed"):
            border = "solid"
            bg = _color_with_alpha(palette.error, 40)
        elif d.deleted:
            opacity = 0.5
            border = "dashed"
            bg = _color_with_alpha(palette.error, 30)
        elif d.added:
            border = "solid"
            bg = _color_with_alpha(palette.success, 30)
        elif d.edited:
            border = "solid"
            bg = _color_with_alpha(palette.warning, 30)

        accent = palette.text_primary
        self.setStyleSheet(
            f"""
            QFrame#editableTagRow {{
                border: 1px {border} palette(mid);
                border-radius: 3px;
                background: {bg};
            }}
            QFrame#editableTagRow QLabel {{
                color: {accent};
            }}
            """
        )

        value_css = ""
        if d.deleted:
            value_css = "QLabel { text-decoration: line-through; }"
        self.value_cell.set_label_style(value_css)
        key_css = "QLabel { text-decoration: line-through; }" if d.deleted else ""
        self.key_cell.set_label_style(key_css)

        eff = self.graphicsEffect()
        if not isinstance(eff, QtWidgets.QGraphicsOpacityEffect):
            eff = QtWidgets.QGraphicsOpacityEffect(self)
            self.setGraphicsEffect(eff)
        eff.setOpacity(opacity)


class _AddTagDialog(QtWidgets.QDialog):
    def __init__(self, parent: QtWidgets.QWidget, existing_keys: set[str]):
        super().__init__(parent)
        self.setWindowTitle(t("Add new tag"))
        self.resize(dpix(540), dpix(320))
        self._existing = existing_keys

        lay = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        self._key_edit = QtWidgets.QLineEdit(self)
        self._key_edit.setPlaceholderText(t("key"))
        self._value_edit = QtWidgets.QPlainTextEdit(self)
        self._value_edit.setPlaceholderText(t("value"))
        form.addRow(t("Key:"), self._key_edit)
        form.addRow(t("Value:"), self._value_edit)
        lay.addLayout(form)

        self._hint = QtWidgets.QLabel("", self)
        self._hint.setStyleSheet(f"QLabel {{ color: {ThemeManager.instance().palette.warning}; }}")
        lay.addWidget(self._hint)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, parent=self)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self._key_edit.textChanged.connect(self._update_hint)

    def _update_hint(self, text: str) -> None:
        text = text.strip()
        if text and text in self._existing:
            self._hint.setText(t("Key already exists; will be auto-renamed on add."))
        else:
            self._hint.setText("")

    def values(self) -> tuple[str, str]:
        return self._key_edit.text(), self._value_edit.toPlainText()


class EditableTagCard(CollapsibleCard):
    def __init__(self, prefix: str = "", parent=None):
        title = t(prefix) if prefix else t("tag")
        section_id = f"tag:{prefix}" if prefix else "tag"
        super().__init__(title, section_id, parent=parent)
        self._prefix = prefix
        self._tags: dict[str, str] = {}
        self._locks: dict[str, bool] = {}
        self._path: str = ""
        self._file_hash: str = ""
        self._db: str = ""
        self.local_edits: dict[str, RowEdit] = {}
        self._new_id_counter = itertools.count(1)
        self.widgets: dict[str, _TagRow] = {}

        inner = QtWidgets.QWidget(self)
        inner_lay = QtWidgets.QVBoxLayout(inner)
        inner_lay.setContentsMargins(0, 0, 0, 0)
        inner_lay.setSpacing(dpix(4))

        self._rows_container = QtWidgets.QWidget(inner)
        self._rows_layout = QtWidgets.QVBoxLayout(self._rows_container)
        self._rows_layout.setContentsMargins(0, 0, 0, 0)
        self._rows_layout.setSpacing(dpix(2))
        inner_lay.addWidget(self._rows_container)

        toolbar = QtWidgets.QWidget(inner)
        tbl = QtWidgets.QHBoxLayout(toolbar)
        tbl.setContentsMargins(dpix(4), dpix(4), dpix(4), 0)
        tbl.setSpacing(dpix(6))

        self._add_btn = QtWidgets.QToolButton(toolbar)
        self._add_btn.setIcon(themed_icon("plus"))
        self._add_btn.setToolTip(t("Add new tag"))
        self._add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._add_btn.setToolButtonStyle(QtCore.Qt.ToolButtonIconOnly)
        self._add_btn.clicked.connect(self._on_add_clicked)

        self._save_btn = QtWidgets.QPushButton(t("Save"), toolbar)
        self._save_btn.clicked.connect(self._on_save_clicked)
        self._revert_btn = QtWidgets.QPushButton(t("Revert"), toolbar)
        self._revert_btn.clicked.connect(self._on_revert_clicked)

        tbl.addStretch(1)
        tbl.addWidget(self._add_btn, 0, QtCore.Qt.AlignLeft)
        tbl.addWidget(self._save_btn)
        tbl.addWidget(self._revert_btn)
        inner_lay.addWidget(toolbar)

        self.set_content_widget(inner)

        TagEditService.instance().overlay_changed.connect(self._on_overlay_changed)
        TagEditService.instance().commit_confirmed.connect(self._on_commit_confirmed)

        self._overlay_cache: tuple[dict[str, str], dict[str, bool], dict[str, str]] = ({}, {}, {})
        self._refresh_action_buttons()

    # ---- Public API ----------------------------------------------------

    def update_data(
        self,
        tags: dict[str, str],
        locks: dict[str, bool] | None,
        states: dict[str, str] | None,
        path: str,
        file_hash: str,
        db: str,
    ):
        prev_hash = self._file_hash
        self._tags = dict(tags)
        self._locks = dict(locks or {})
        self._path = path
        self._file_hash = file_hash or ""
        self._db = db or ""
        if prev_hash != self._file_hash:
            self.local_edits.clear()
        self._refresh_overlay_cache()
        self._render()

    # ---- Render --------------------------------------------------------

    def _to_full(self, short_key: str) -> str:
        return f"{self._prefix}.{short_key}" if self._prefix else short_key

    def _to_short(self, full_key: str) -> str | None:
        if not self._prefix:
            return None if "." in full_key else full_key
        head = self._prefix + "."
        if full_key.startswith(head):
            return full_key[len(head) :]
        return None

    def _refresh_overlay_cache(self) -> None:
        full_tags = {self._to_full(k): v for k, v in self._tags.items()}
        full_locks = {self._to_full(k): v for k, v in self._locks.items()}
        merged_tags, merged_locks, states = TagEditService.instance().apply_overlay(self._file_hash, full_tags, full_locks)
        short_tags: dict[str, str] = {}
        short_locks: dict[str, bool] = {}
        short_states: dict[str, str] = {}
        for full_key, value in merged_tags.items():
            short = self._to_short(full_key)
            if short is None:
                continue
            short_tags[short] = value
            if full_key in merged_locks:
                short_locks[short] = merged_locks[full_key]
            if full_key in states:
                short_states[short] = states[full_key]
        self._overlay_cache = (short_tags, short_locks, short_states)

    def _render(self):
        base_tags, base_locks, in_flight = self._overlay_cache
        rendered: list[RowDisplay] = []
        for base_key, base_value in base_tags.items():
            edit = self.local_edits.get(base_key)
            if edit is None:
                rendered.append(
                    RowDisplay(
                        row_id=base_key,
                        key=base_key,
                        value=base_value,
                        locked=base_locks.get(base_key, False),
                        deleted=False,
                        added=False,
                        edited=False,
                        in_flight=in_flight.get(base_key, ""),
                    )
                )
                continue
            display_key = edit.new_key if edit.new_key is not None else base_key
            display_value = edit.new_value if edit.new_value is not None else base_value
            display_lock = edit.new_locked if edit.new_locked is not None else base_locks.get(base_key, False)
            edited = edit.new_key is not None or edit.new_value is not None or edit.new_locked is not None
            rendered.append(
                RowDisplay(
                    row_id=base_key,
                    key=display_key,
                    value=display_value,
                    locked=bool(display_lock),
                    deleted=edit.deleted,
                    added=False,
                    edited=edited and not edit.deleted,
                    in_flight=in_flight.get(base_key, ""),
                )
            )

        for row_id, edit in self.local_edits.items():
            if not edit.is_new:
                continue
            rendered.append(
                RowDisplay(
                    row_id=row_id,
                    key=edit.new_key if edit.new_key is not None else "",
                    value=edit.new_value if edit.new_value is not None else edit.initial_value,
                    locked=bool(edit.new_locked if edit.new_locked is not None else edit.initial_locked),
                    deleted=edit.deleted,
                    added=True,
                    edited=False,
                    in_flight="",
                )
            )

        self._sync_rows(rendered)
        self._refresh_action_buttons()
        visible_count = sum(1 for d in rendered if not d.deleted)
        self.update_title_count(visible_count)

    def _sync_rows(self, rendered: list[RowDisplay]) -> None:
        wanted_ids = [d.row_id for d in rendered]
        for rid in list(self.widgets):
            if rid not in wanted_ids:
                w = self.widgets.pop(rid)
                self._rows_layout.removeWidget(w)
                w.setParent(None)
                w.deleteLater()

        fm = self.fontMetrics()
        max_key_w = max((fm.horizontalAdvance(d.key) for d in rendered), default=0)
        key_col_w = min(max(dpix(_KEY_COL_MIN), max_key_w + dpix(8)), dpix(_KEY_COL_MAX))

        for i, d in enumerate(rendered):
            row = self.widgets.get(d.row_id)
            if row is None:
                row = _TagRow(d.row_id, self._rows_container)
                row.key_committed.connect(self._on_row_key_committed)
                row.value_committed.connect(self._on_row_value_committed)
                row.lock_toggled.connect(self._on_row_lock_toggled)
                row.delete_toggled.connect(self._on_row_delete_toggled)
                self.widgets[d.row_id] = row
                self._rows_layout.insertWidget(i, row)
            else:
                self._rows_layout.removeWidget(row)
                self._rows_layout.insertWidget(i, row)
            row.set_data(d, key_col_w)

    # ---- Local edit handlers -------------------------------------------

    def _on_row_key_committed(self, row_id: str, new_key: str):
        new_key = new_key.strip()
        if not new_key:
            return
        new_key = self._dedupe_key(new_key, exclude_row_id=row_id)
        edit = self.local_edits.get(row_id) or RowEdit()
        if edit.is_new:
            edit.new_key = new_key
        else:
            edit.new_key = None if new_key == row_id else new_key
        self.local_edits[row_id] = edit
        self._cleanup_edit(row_id)
        self._render()

    def _on_row_value_committed(self, row_id: str, new_value: str):
        edit = self.local_edits.get(row_id) or RowEdit()
        if edit.is_new:
            edit.new_value = new_value
        else:
            base_val = self._tags.get(row_id, "")
            edit.new_value = None if new_value == base_val else new_value
        self.local_edits[row_id] = edit
        self._cleanup_edit(row_id)
        self._render()

    def _on_row_lock_toggled(self, row_id: str, locked: bool):
        edit = self.local_edits.get(row_id) or RowEdit()
        if edit.is_new:
            edit.new_locked = locked
        else:
            base = self._locks.get(row_id, False)
            edit.new_locked = None if locked == base else locked
        self.local_edits[row_id] = edit
        self._cleanup_edit(row_id)
        self._render()

    def _on_row_delete_toggled(self, row_id: str, mark: bool):
        edit = self.local_edits.get(row_id)
        if edit is None:
            edit = RowEdit()
        if edit.is_new and mark:
            self.local_edits.pop(row_id, None)
            self._render()
            return
        edit.deleted = mark
        self.local_edits[row_id] = edit
        self._cleanup_edit(row_id)
        self._render()

    def _cleanup_edit(self, row_id: str) -> None:
        edit = self.local_edits.get(row_id)
        if edit is None or edit.is_new:
            return
        if not edit.deleted and edit.new_key is None and edit.new_value is None and edit.new_locked is None:
            self.local_edits.pop(row_id, None)

    def _dedupe_key(self, key: str, exclude_row_id: str | None = None) -> str:
        used: set[str] = set()
        base_tags, _, _ = self._overlay_cache
        for base_key in base_tags:
            edit = self.local_edits.get(base_key)
            if base_key == exclude_row_id:
                continue
            if edit and edit.deleted:
                continue
            display_key = edit.new_key if edit and edit.new_key is not None else base_key
            used.add(display_key)
        for rid, edit in self.local_edits.items():
            if rid == exclude_row_id or not edit.is_new or edit.deleted:
                continue
            if edit.new_key:
                used.add(edit.new_key)
        if key not in used:
            return key
        i = 2
        while f"{key}_{i}" in used:
            i += 1
        return f"{key}_{i}"

    # ---- Add / Save / Revert -------------------------------------------

    def _on_add_clicked(self) -> None:
        if not self._validate_context(allow_no_hash=True):
            return
        existing = self._current_displayed_keys()
        dlg = _AddTagDialog(self, existing)
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        key, value = dlg.values()
        key = key.strip()
        if not key:
            return
        key = self._dedupe_key(key)
        rid = f"__new__{next(self._new_id_counter)}"
        self.local_edits[rid] = RowEdit(
            is_new=True,
            new_key=key,
            new_value=value,
            new_locked=False,
            initial_value=value,
        )
        self._render()

    def _current_displayed_keys(self) -> set[str]:
        keys: set[str] = set()
        base_tags, _, _ = self._overlay_cache
        for base_key in base_tags:
            edit = self.local_edits.get(base_key)
            if edit and edit.deleted:
                continue
            keys.add(edit.new_key if edit and edit.new_key is not None else base_key)
        for edit in self.local_edits.values():
            if not edit.is_new or edit.deleted:
                continue
            if edit.new_key:
                keys.add(edit.new_key)
        return keys

    def _on_save_clicked(self) -> None:
        if not self._validate_context():
            return
        upserts: list[tuple[str, str, bool]] = []
        deletes: list[str] = []
        renames: list[tuple[str, str, str, bool]] = []

        for rid, edit in self.local_edits.items():
            if edit.is_new:
                if edit.deleted:
                    continue
                key = (edit.new_key or "").strip()
                if not key:
                    continue
                value = edit.new_value if edit.new_value is not None else edit.initial_value
                locked = bool(edit.new_locked) if edit.new_locked is not None else bool(edit.initial_locked)
                upserts.append((key, value, locked))
            else:
                if edit.deleted:
                    deletes.append(rid)
                    continue
                effective_value = edit.new_value if edit.new_value is not None else self._tags.get(rid, "")
                effective_lock = edit.new_locked if edit.new_locked is not None else self._locks.get(rid, False)
                if edit.new_key is not None and edit.new_key != rid:
                    renames.append((rid, edit.new_key, effective_value, bool(effective_lock)))
                else:
                    upserts.append((rid, effective_value, bool(effective_lock)))

        all_target_keys = [k for (k, _, _) in upserts] + [nk for (_, nk, _, _) in renames]
        if len(all_target_keys) != len(set(all_target_keys)):
            QtWidgets.QMessageBox.warning(
                self,
                t("Save tags"),
                t("Duplicate keys remain after edits. Please fix and try again."),
            )
            AppLogger.warning(f"[EditableTagCard] save aborted: duplicate keys in {all_target_keys}")
            return

        if not upserts and not deletes and not renames:
            return

        upserts = [(self._to_full(k), v, lk) for (k, v, lk) in upserts]
        deletes = [self._to_full(k) for k in deletes]
        renames = [(self._to_full(old), self._to_full(new), v, lk) for (old, new, v, lk) in renames]

        rid = TagEditService.instance().submit([self._path], upserts, deletes, self._db, renames=renames, file_hash=self._file_hash)
        if rid is None:
            return
        self.local_edits.clear()
        self._render()

    def _on_revert_clicked(self) -> None:
        if not self.local_edits:
            return
        self.local_edits.clear()
        self._render()

    def _refresh_action_buttons(self) -> None:
        has_changes = bool(self.local_edits)
        self._save_btn.setEnabled(has_changes)
        self._revert_btn.setEnabled(has_changes)
        self._add_btn.setEnabled(bool(self._file_hash))

    # ---- Service callbacks ---------------------------------------------

    def _on_overlay_changed(self, file_hash: str):
        if not file_hash or file_hash != self._file_hash:
            return
        self._refresh_overlay_cache()
        self._render()

    def _on_commit_confirmed(self, file_hash: str, applied: dict, deleted: list):
        if not file_hash or file_hash != self._file_hash:
            return
        for full_key, (value, locked) in applied.items():
            short = self._to_short(full_key)
            if short is None:
                continue
            self._tags[short] = value
            self._locks[short] = bool(locked)
        for full_key in deleted:
            short = self._to_short(full_key)
            if short is None:
                continue
            self._tags.pop(short, None)
            self._locks.pop(short, None)
        self._refresh_overlay_cache()

    def _validate_context(self, *, allow_no_hash: bool = False) -> bool:
        if not self._path or not self._db or (not allow_no_hash and not self._file_hash):
            AppLogger.warning(f"[EditableTagCard] missing context path={bool(self._path)} hash={bool(self._file_hash)} db={bool(self._db)}")
            return False
        return True

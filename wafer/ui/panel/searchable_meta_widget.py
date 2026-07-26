from __future__ import annotations

import html
import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.formatting import dpix, display_prefixed_key
from ...utils.logs import AppLogger
from ...utils.paths import list_setting_db_names
from ...core.lang.manager import t
from ...core.color.theme import ThemeManager
from ...core.commands.bridge import ActionKit, Menu
from ...core.qt.dispatcher import Dispatcher, CancelSlot
from ...core.qt.icon_engine import icon_draw, themed_icon
from ...core.qt.thread import utility_pool
from ...plugin import KeyFilter
from ..dialogs import ConfirmDialog
from .tag_edit_service import TagEditService

SHORT_VALUE_LIMIT = 1000
SNIPPET_BUDGET = SHORT_VALUE_LIMIT * 2
SNIPPET_MIN_CONTEXT = 20
MAX_VISIBLE_SNIPPETS = 20
SAFETY_CHAR_LIMIT = 1_000_000

_PAD = 6
_SPACING = 4


def build_highlight_ctx(query: str):
    escaped_query = html.escape(query)
    pattern = re.compile(f"({re.escape(escaped_query)})", re.IGNORECASE)
    raw_pattern = re.compile(re.escape(query), re.IGNORECASE)
    palette = ThemeManager.instance().palette
    tag = f'<span style="background:{palette.accent};color:{palette.accent_text};border-radius:2px;">'
    return pattern, tag, raw_pattern


def highlight_html(text: str, query: str, _ctx=None) -> str:
    escaped = html.escape(text)
    if not query:
        return escaped.replace("\n", "<br>")
    if _ctx is None:
        _ctx = build_highlight_ctx(query)
    pattern, tag = _ctx[0], _ctx[1]
    parts = pattern.split(escaped)
    out = []
    for i, part in enumerate(parts):
        out.append(f"{tag}{part}</span>" if i % 2 else part)
    return "".join(out).replace("\n", "<br>")


def build_value_html(text: str, query: str, ctx=None) -> str:
    original_len = len(text)
    if original_len > SAFETY_CHAR_LIMIT:
        text = text[:SAFETY_CHAR_LIMIT]
    if len(text) <= SHORT_VALUE_LIMIT:
        return highlight_html(text, query, ctx)
    palette = ThemeManager.instance().palette
    chars_info = f'<span style="color:{palette.text_accent};">({original_len:,} chars total)</span>'
    if not query:
        return html.escape(text[:SHORT_VALUE_LIMIT]).replace("\n", "<br>") + f" … {chars_info}"
    if ctx is None:
        ctx = build_highlight_ctx(query)
    raw_pattern = ctx[2]
    matches = list(raw_pattern.finditer(text))
    if not matches:
        return html.escape(text[:SHORT_VALUE_LIMIT]).replace("\n", "<br>") + f" … {chars_info}"
    n = len(matches)
    context_each = max(SNIPPET_MIN_CONTEXT * 2, SNIPPET_BUDGET // n)
    half = context_each // 2
    max_range_len = SNIPPET_BUDGET // max(1, min(n, MAX_VISIBLE_SNIPPETS))
    ranges: list[list[int]] = []
    for m in matches:
        s = max(0, m.start() - half)
        e = min(len(text), m.end() + half)
        if ranges and s <= ranges[-1][1]:
            merged_len = e - ranges[-1][0]
            if merged_len <= max_range_len:
                ranges[-1][1] = max(ranges[-1][1], e)
            else:
                ranges.append([s, e])
        else:
            ranges.append([s, e])
    visible = ranges[:MAX_VISIBLE_SNIPPETS]
    visible_count = sum(1 for m in matches if any(s <= m.start() < e for s, e in visible))
    remaining = n - visible_count
    parts = []
    for s, e in visible:
        frag = highlight_html(text[s:e], query, ctx)
        prefix = "… " if s > 0 else ""
        suffix = " …" if e < len(text) else ""
        parts.append(f"{prefix}{frag}{suffix}")
    result = "<br>".join(parts)
    footer = chars_info
    if remaining > 0:
        footer = f'<span style="color:{palette.text_accent};">+{remaining} more found</span> / {chars_info}'
    result += f"<br>{footer}"
    return result


_KEY_HTML_ROLE = QtCore.Qt.ItemDataRole.UserRole + 1
_VAL_HTML_ROLE = QtCore.Qt.ItemDataRole.UserRole + 2
_LOCKED_ROLE = QtCore.Qt.ItemDataRole.UserRole + 3
_STATE_ROLE = QtCore.Qt.ItemDataRole.UserRole + 4


@dataclass(frozen=True)
class SearchKvContext:
    scope: str = "tag"
    prefix: str = ""
    path: str = ""
    file_hash: str = ""
    db: str = ""


class _MetaListModel(QtCore.QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str, bool, str]] = []

    def reset_rows(self, rows: list[tuple[str, str, bool, str]]):
        self.beginResetModel()
        self._rows = rows
        self.endResetModel()

    def rowCount(self, parent=QtCore.QModelIndex()):
        if parent.isValid():
            return 0
        return len(self._rows)

    def data(self, index, role=QtCore.Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r = index.row()
        if r < 0 or r >= len(self._rows):
            return None
        if role == _KEY_HTML_ROLE:
            return self._rows[r][0]
        if role == _VAL_HTML_ROLE:
            return self._rows[r][1]
        if role == _LOCKED_ROLE:
            return self._rows[r][2]
        if role == _STATE_ROLE:
            return self._rows[r][3]
        return None


class _MetaItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.key_width = dpix(120)
        self._doc_cache: dict[int, tuple[QtGui.QTextDocument, QtGui.QTextDocument, int, int]] = {}
        self._last_width: int = 0

    def invalidate_cache(self):
        self._doc_cache.clear()
        self._last_width = 0

    def _get_docs(self, index, font, total_w):
        if self._last_width != total_w:
            self._doc_cache.clear()
            self._last_width = total_w

        row = index.row()
        cached = self._doc_cache.get(row)
        if cached is not None:
            return cached

        pad = dpix(_PAD)
        spacing = dpix(_SPACING)
        key_w = min(self.key_width, int(total_w * 0.4))
        side_w = dpix(18)
        val_w = total_w - key_w - spacing - side_w

        doc_key = QtGui.QTextDocument()
        doc_key.setDocumentMargin(0)
        doc_key.setDefaultFont(font)
        doc_key.setTextWidth(key_w)
        doc_key.setHtml(index.data(_KEY_HTML_ROLE) or "")

        doc_val = QtGui.QTextDocument()
        doc_val.setDocumentMargin(0)
        doc_val.setDefaultFont(font)
        doc_val.setTextWidth(max(val_w, dpix(50)))
        doc_val.setHtml(index.data(_VAL_HTML_ROLE) or "")

        h = max(int(doc_key.size().height()), int(doc_val.size().height())) + 2 * pad

        entry = (doc_key, doc_val, h, side_w)
        self._doc_cache[row] = entry
        return entry

    def paint(self, painter: QtGui.QPainter, option, index):
        painter.save()
        pad = dpix(_PAD)
        spacing = dpix(_SPACING)
        rect = option.rect.adjusted(pad, pad, -pad, -pad)
        view = option.widget
        total_w = (view.viewport().width() - 2 * pad) if view else dpix(400)
        key_w = min(self.key_width, int(total_w * 0.4))
        doc_key, doc_val, _, side_w = self._get_docs(index, option.font, total_w)
        painter.translate(rect.x(), rect.y())
        doc_key.drawContents(painter)
        painter.translate(key_w + spacing, 0)
        doc_val.drawContents(painter)
        painter.translate(max(doc_val.textWidth(), 0) + dpix(4), 0)
        self._draw_lock_icon(painter, QtCore.QRectF(0, 0, side_w, option.rect.height()), index)
        painter.restore()

    def _draw_lock_icon(self, painter: QtGui.QPainter, rect: QtCore.QRectF, index: QtCore.QModelIndex):
        palette = ThemeManager.instance().palette
        state = index.data(_STATE_ROLE) or ""
        locked = bool(index.data(_LOCKED_ROLE))
        if not locked:
            return
        color = QtGui.QColor(palette.warning)
        if state in ("saving", "deleting"):
            color = QtGui.QColor(palette.text_muted)
        elif state in ("save_failed", "delete_failed"):
            color = QtGui.QColor(palette.error)
        size = dpix(10)
        icon_rect = QtCore.QRectF(rect.right() - size, rect.top() + dpix(3), size, size)
        icon_draw("lock", painter, icon_rect, color)

    def sizeHint(self, option, index):
        pad = dpix(_PAD)
        view = option.widget
        total_w = (view.viewport().width() - 2 * pad) if view else dpix(400)
        _, _, h, _ = self._get_docs(index, option.font, total_w)
        return QtCore.QSize(total_w + 2 * pad, h)


class SearchKvDetailDialog(QtWidgets.QDialog):
    delete_requested = QtCore.Signal()

    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        *,
        title: str,
        key: str = "",
        value: str = "",
        locked: bool = False,
        add_mode: bool = False,
        existing_keys: set[str] | None = None,
        duplicate_hint: str | None = None,
    ):
        super().__init__(parent)
        self._initial_key = key
        self._initial_value = value
        self._initial_locked = locked
        self._existing_keys = set(existing_keys or set())
        self._duplicate_hint = duplicate_hint or t("Key already exists; will be auto-renamed on save.")
        if not add_mode:
            self._existing_keys.discard(key)

        self.setWindowTitle(title)
        self.resize(dpix(820), dpix(560))

        layout = QtWidgets.QVBoxLayout(self)

        form = QtWidgets.QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        self._add_form_prefix_rows(form)

        self.key_edit = QtWidgets.QLineEdit(key, self)
        self.key_edit.setPlaceholderText(t("key"))
        self.value_edit = QtWidgets.QPlainTextEdit(self)
        self.value_edit.setPlainText(value)
        self.value_edit.setLineWrapMode(QtWidgets.QPlainTextEdit.WidgetWidth)
        form.addRow(t("Key:"), self.key_edit)
        form.addRow(t("Value:"), self.value_edit)
        layout.addLayout(form)

        self.hint_label = QtWidgets.QLabel("", self)
        self.hint_label.setStyleSheet(f"QLabel {{ color: {ThemeManager.instance().palette.warning}; }}")
        layout.addWidget(self.hint_label)

        buttons = QtWidgets.QWidget(self)
        button_layout = QtWidgets.QHBoxLayout(buttons)
        button_layout.setContentsMargins(0, dpix(4), 0, 0)
        button_layout.setSpacing(dpix(6))

        self.lock_check = QtWidgets.QCheckBox(t("Lock"), buttons)
        self.lock_check.setChecked(locked)
        self.delete_btn = QtWidgets.QPushButton(t("Delete"), buttons)
        self.delete_btn.setIcon(themed_icon("cross", margin=0.12))
        self.delete_btn.setVisible(not add_mode)
        self.delete_btn.clicked.connect(self.delete_requested)
        self.revert_btn = QtWidgets.QPushButton(t("Revert"), buttons)
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn = QtWidgets.QPushButton(t("Save"), buttons)
        self.save_btn.clicked.connect(self._on_save_clicked)
        self.cancel_btn = QtWidgets.QPushButton(t("Cancel"), buttons)
        self.cancel_btn.clicked.connect(self.reject)

        button_layout.addWidget(self.delete_btn)
        button_layout.addWidget(self.lock_check)
        button_layout.addStretch(1)
        button_layout.addWidget(self.revert_btn)
        button_layout.addWidget(self.save_btn)
        button_layout.addWidget(self.cancel_btn)
        layout.addWidget(buttons)

        self.key_edit.textChanged.connect(self._update_hint)
        self._connect_hint_dependencies()
        self._update_hint(self.key_edit.text())

    def _add_form_prefix_rows(self, form: QtWidgets.QFormLayout):
        pass

    def _connect_hint_dependencies(self):
        pass

    def _on_save_clicked(self):
        if not self.key().strip():
            self.hint_label.setText(t("Key is required."))
            return
        self.accept()

    def _update_hint(self, text: str):
        key = text.strip()
        if key and key in self._existing_keys_for_hint():
            self.hint_label.setText(self._duplicate_hint)
        else:
            self.hint_label.setText("")

    def _existing_keys_for_hint(self) -> set[str]:
        return self._existing_keys

    def revert(self):
        self.key_edit.setText(self._initial_key)
        self.value_edit.setPlainText(self._initial_value)
        self.lock_check.setChecked(self._initial_locked)

    def key(self) -> str:
        return self.key_edit.text().strip()

    def value(self) -> str:
        return self.value_edit.toPlainText()

    def locked(self) -> bool:
        return self.lock_check.isChecked()


class ScopedSearchKvAddDialog(SearchKvDetailDialog):
    def __init__(
        self,
        parent: QtWidgets.QWidget | None,
        *,
        title: str,
        existing_keys_by_scope: Mapping[str, set[str]] | None = None,
        duplicate_hint: str | None = None,
        scope_options: tuple[tuple[str, str], ...],
        initial_scope: str = "tag",
    ):
        self._scope_combo: QtWidgets.QComboBox | None = None
        self._scope_options = scope_options
        self._initial_scope = initial_scope
        self._existing_keys_by_scope = {scope: set(keys) for scope, keys in (existing_keys_by_scope or {}).items()}
        super().__init__(
            parent,
            title=title,
            add_mode=True,
            duplicate_hint=duplicate_hint or t("Key already exists; will be auto-renamed on add."),
        )

    def _add_form_prefix_rows(self, form: QtWidgets.QFormLayout):
        self._scope_combo = QtWidgets.QComboBox(self)
        for scope, label in self._scope_options:
            self._scope_combo.addItem(label, scope)
        initial_index = max(0, self._scope_combo.findData(self._initial_scope))
        self._scope_combo.setCurrentIndex(initial_index)
        form.addRow(t("Type:"), self._scope_combo)

    def _connect_hint_dependencies(self):
        if self._scope_combo is not None:
            self._scope_combo.currentIndexChanged.connect(lambda _idx: self._update_hint(self.key_edit.text()))

    def _existing_keys_for_hint(self) -> set[str]:
        return self._existing_keys_by_scope.get(self.scope(), set())

    def scope(self) -> str:
        if self._scope_combo is None:
            return ""
        return str(self._scope_combo.currentData() or "")


class SearchableMetaWidget(QtWidgets.QWidget):
    count_changed = QtCore.Signal(int)
    DEBOUNCE_MS = 50

    def __init__(self, parent: QtWidgets.QWidget | None = None, *, scope: str = "tag", prefix: str = "") -> None:
        super().__init__(parent)
        self._base_data: dict[str, str] = {}
        self._base_locks: dict[str, bool] = {}
        self._data: dict[str, Any] = {}
        self._locks: dict[str, bool] = {}
        self._states: dict[str, str] = {}
        self._filtered_keys: list[str] = []
        self._search_index: dict[str, str] | None = None
        self._context = SearchKvContext(scope=scope, prefix=prefix)
        self._dispatcher = Dispatcher(utility_pool, parent=self)
        self._index_cancel = CancelSlot()

        self._debounce_timer = QtCore.QTimer(self)
        self._debounce_timer.setSingleShot(True)
        self._debounce_timer.setInterval(self.DEBOUNCE_MS)
        self._debounce_timer.timeout.connect(self._on_debounce_timeout)

        self._search = QtWidgets.QLineEdit(self)
        self._search.setPlaceholderText(t("Search key or value…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._on_search_changed)

        self._status_label = QtWidgets.QLabel(self)
        self._status_label.setAlignment(QtCore.Qt.AlignRight)
        self._status_label.setStyleSheet(f"color: palette(dark); font-size: {dpix(11)}px;")

        self._model = _MetaListModel(self)
        self._delegate = _MetaItemDelegate(self)

        self._list_view = QtWidgets.QListView(self)
        self._list_view.setModel(self._model)
        self._list_view.setItemDelegate(self._delegate)
        self._list_view.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
        self._list_view.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_view.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._list_view.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.NoSelection)
        self._list_view.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
        self._list_view.setSizeAdjustPolicy(QtWidgets.QAbstractScrollArea.SizeAdjustPolicy.AdjustToContents)
        self._list_view.setSizePolicy(
            QtWidgets.QSizePolicy.Policy.Preferred,
            QtWidgets.QSizePolicy.Policy.Preferred,
        )
        self._list_view.setContextMenuPolicy(QtCore.Qt.ContextMenuPolicy.CustomContextMenu)
        self._list_view.customContextMenuRequested.connect(self._on_context_menu)
        self._list_view.doubleClicked.connect(self._on_double_clicked)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(6))
        layout.addWidget(self._search)
        layout.addWidget(self._status_label)
        layout.addWidget(self._list_view)

        footer = QtWidgets.QWidget(self)
        footer_lay = QtWidgets.QHBoxLayout(footer)
        footer_lay.setContentsMargins(0, 0, 0, 0)
        footer_lay.addStretch(1)
        self._add_btn = QtWidgets.QToolButton(footer)
        self._add_btn.setIcon(themed_icon("plus"))
        self._add_btn.setAutoRaise(True)
        self._add_btn.setCursor(QtCore.Qt.PointingHandCursor)
        self._add_btn.setToolTip(t("Add tag or metadata"))
        self._add_btn.clicked.connect(self._on_add_clicked)
        footer_lay.addWidget(self._add_btn)
        layout.addWidget(footer)

        TagEditService.instance().kv_overlay_changed.connect(self._on_kv_overlay_changed)
        TagEditService.instance().kv_commit_confirmed.connect(self._on_kv_commit_confirmed)

    def current_query(self) -> str:
        return self._search.text().strip().lower()

    def _display_key(self, key: str) -> str:
        return display_prefixed_key(key)

    def set_data(self, data: dict[str, Any], locks: dict[str, bool] | None = None):
        self._set_data(data, locks or {})

    def set_context(
        self,
        data: dict[str, Any],
        locks: dict[str, bool] | None,
        *,
        path: str,
        file_hash: str = "",
        db: str,
        scope: str | None = None,
        prefix: str | None = None,
    ):
        self._context = SearchKvContext(
            scope=scope or self._context.scope,
            prefix=self._context.prefix if prefix is None else prefix,
            path=path or "",
            file_hash=file_hash or "",
            db=db or "",
        )
        self._set_data(data, locks or {})

    def _set_data(self, data: dict[str, Any], locks: dict[str, bool]):
        self._base_data = {str(k): str(v) for k, v in dict(data).items()}
        self._base_locks = {str(k): bool(v) for k, v in dict(locks).items()}
        self._render()

    def _render(self):
        full_data = {self._to_full(k): v for k, v in self._base_data.items()}
        full_locks = {self._to_full(k): v for k, v in self._base_locks.items()}
        merged, merged_locks, states = TagEditService.instance().apply_overlay(self._target_id(), full_data, full_locks, scope=self._context.scope)
        short_data: dict[str, str] = {}
        short_locks: dict[str, bool] = {}
        short_states: dict[str, str] = {}
        for full_key, value in merged.items():
            short = self._to_short(full_key)
            if short is None:
                continue
            short_data[short] = str(value)
            short_locks[short] = bool(merged_locks.get(full_key, False))
            if full_key in states:
                short_states[short] = states[full_key]
        self._data = short_data
        self._locks = short_locks
        self._states = short_states
        self._search_index = None
        self._update_key_width()
        self._apply_filter(self._search.text())
        self._build_index_async()
        self._sync_add_enabled()

    def _to_full(self, key: str) -> str:
        prefix = self._context.prefix
        return f"{prefix}.{key}" if prefix else key

    def _to_short(self, full_key: str) -> str | None:
        prefix = self._context.prefix
        if not prefix:
            return None if "." in full_key else full_key
        head = prefix + "."
        if full_key.startswith(head):
            return full_key[len(head) :]
        return None

    def _target_id(self) -> str:
        return self._context.file_hash if self._context.scope == "tag" else self._context.path

    def _can_submit(self) -> bool:
        if not self._context.path or not self._context.db:
            return False
        if self._context.scope == "tag" and not self._context.file_hash:
            return False
        return self._context.scope in ("tag", "meta_info")

    def _sync_add_enabled(self):
        self._add_btn.setEnabled(self._can_submit())

    def _update_key_width(self):
        if not self._data:
            return
        fm = QtGui.QFontMetrics(self.font())
        max_w = dpix(60)
        for key in self._data:
            display = self._display_key(key)
            max_w = max(max_w, fm.horizontalAdvance(display) + dpix(8))
        self._delegate.key_width = min(max_w, dpix(250))

    def _build_index_async(self):
        cancel = self._index_cancel.renew()
        snapshot = dict(self._data)

        def build():
            index = {k: str(v).lower() for k, v in snapshot.items()}
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._on_index_ready(index, cancel))

        self._dispatcher.post(build, priority=3, cancel=cancel)

    def _on_index_ready(self, index: dict[str, str], cancel):
        if cancel.is_cancelled():
            return
        self._search_index = index

    def _on_search_changed(self, text: str):
        self._debounce_timer.start()

    def _on_debounce_timeout(self):
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str):
        query = text.strip().lower()
        if not query:
            self._filtered_keys = list(self._data.keys())
        elif self._search_index is not None:
            self._filtered_keys = [k for k in self._data if query in k.lower() or query in self._search_index.get(k, "")]
        else:
            self._filtered_keys = [k for k, v in self._data.items() if query in k.lower() or query in str(v).lower()]
        self._update_view()

    def _update_view(self):
        query = self.current_query()
        ctx = build_highlight_ctx(query) if query else None

        total = len(self._data)
        shown = len(self._filtered_keys)
        if total > 0 and shown != total:
            self._status_label.setText(f"{shown} / {total}")
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

        rows = []
        for key in self._filtered_keys:
            display_key = self._display_key(key)
            key_html = highlight_html(display_key, query, ctx)
            val = str(self._data.get(key, ""))
            val_html = build_value_html(val, query, ctx)
            rows.append((key_html, val_html, bool(self._locks.get(key, False)), self._states.get(key, "")))

        self._delegate.invalidate_cache()
        self._model.reset_rows(rows)
        self.count_changed.emit(len(self._data))

    def _key_for_row(self, row: int) -> str | None:
        if 0 <= row < len(self._filtered_keys):
            return self._filtered_keys[row]
        return None

    def _full_value(self, key: str) -> str:
        return str(self._data.get(key, ""))

    def _on_double_clicked(self, index: QtCore.QModelIndex):
        if not index.isValid():
            return
        key = self._key_for_row(index.row())
        if key is None:
            return
        self._open_edit_dialog(key)

    def _open_edit_dialog(self, key: str):
        dlg = SearchKvDetailDialog(
            self,
            title=t("Edit metadata - {key}", key=self._display_key(key)),
            key=key,
            value=self._full_value(key),
            locked=bool(self._locks.get(key, False)),
            existing_keys=self._current_displayed_keys(),
        )
        dlg.delete_requested.connect(lambda: self._confirm_delete(key, parent=dlg, on_deleted=dlg.reject))
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        new_key = self._dedupe_key(dlg.key(), exclude=key)
        self._submit_save(key, new_key, dlg.value(), dlg.locked())

    def _on_add_clicked(self):
        if not self._can_submit():
            AppLogger.warning(f"[SearchKV] add aborted: scope={self._context.scope} path={bool(self._context.path)} file_hash={bool(self._context.file_hash)} db={bool(self._context.db)}")
            return
        dlg = SearchKvDetailDialog(
            self,
            title=t("Add metadata"),
            add_mode=True,
            existing_keys=self._current_displayed_keys(),
        )
        if dlg.exec() != QtWidgets.QDialog.Accepted:
            return
        key = self._dedupe_key(dlg.key())
        if not key:
            return
        self._submit_upsert(key, dlg.value(), dlg.locked())

    def _submit_save(self, old_key: str, new_key: str, value: str, locked: bool):
        if not self._can_submit():
            AppLogger.warning(f"[SearchKV] save aborted: missing context scope={self._context.scope}")
            return
        if new_key != old_key:
            old_full = self._to_full(old_key)
            new_full = self._to_full(new_key)
            rid = TagEditService.instance().submit(
                [self._context.path],
                [],
                [],
                self._context.db,
                scope=self._context.scope,
                renames=[(old_full, new_full, value, locked)],
                file_hash=self._context.file_hash if self._context.scope == "tag" else None,
                target_id=self._context.path if self._context.scope == "meta_info" else None,
            )
        else:
            rid = self._submit_upsert(new_key, value, locked)
        if rid:
            AppLogger.info(f"[SearchKV] save submitted scope={self._context.scope} key={self._to_full(new_key)}")

    def _submit_upsert(self, key: str, value: str, locked: bool, *, lock_only: bool = False) -> str | None:
        if not self._can_submit():
            return None
        return TagEditService.instance().submit(
            [self._context.path],
            [(self._to_full(key), value, locked)],
            [],
            self._context.db,
            scope=self._context.scope,
            lock_only=lock_only,
            file_hash=self._context.file_hash if self._context.scope == "tag" else None,
            target_id=self._context.path if self._context.scope == "meta_info" else None,
        )

    def _submit_delete(self, key: str):
        if not self._can_submit():
            AppLogger.warning(f"[SearchKV] delete aborted: missing context scope={self._context.scope}")
            return
        rid = TagEditService.instance().submit(
            [self._context.path],
            [],
            [self._to_full(key)],
            self._context.db,
            scope=self._context.scope,
            file_hash=self._context.file_hash if self._context.scope == "tag" else None,
            target_id=self._context.path if self._context.scope == "meta_info" else None,
        )
        if rid:
            AppLogger.info(f"[SearchKV] delete submitted scope={self._context.scope} key={self._to_full(key)}")

    def _current_displayed_keys(self) -> set[str]:
        return set(self._data)

    def _dedupe_key(self, key: str, *, exclude: str | None = None) -> str:
        key = key.strip()
        if not key:
            return ""
        used = set(self._data)
        if exclude is not None:
            used.discard(exclude)
        if key not in used:
            return key
        i = 2
        while f"{key}_{i}" in used:
            i += 1
        return f"{key}_{i}"

    def _on_kv_overlay_changed(self, scope: str, target_id: str):
        if scope == self._context.scope and target_id == self._target_id():
            self._render()

    def _on_kv_commit_confirmed(self, scope: str, target_id: str, applied: dict, deleted: list):
        if scope != self._context.scope or target_id != self._target_id():
            return
        for full_key, item in (applied or {}).items():
            short = self._to_short(full_key)
            if short is None:
                continue
            value, locked = item
            self._base_data[short] = str(value)
            self._base_locks[short] = bool(locked)
        for full_key in deleted or []:
            short = self._to_short(full_key)
            if short is None:
                continue
            self._base_data.pop(short, None)
            self._base_locks.pop(short, None)
        self._render()

    def _on_context_menu(self, pos: QtCore.QPoint):
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        key = self._key_for_row(index.row())
        if key is None:
            return
        display_key = self._display_key(key)
        value = self._full_value(key)
        self._build_context_menu(index.row(), key, display_key, value).exec(self._list_view.viewport().mapToGlobal(pos))

    def _build_context_menu(self, row: int, key: str, display_key: str, value: str) -> QtWidgets.QMenu:
        clipboard = QtWidgets.QApplication.clipboard()
        uid = f"{id(self):x}.{row}"
        locked = bool(self._locks.get(key, False))
        lock_label = "Unlock" if locked else "Lock"
        spec = Menu.session(self).menu(
            [
                ":Meta",
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_key", display="Copy key", func=lambda ctx: clipboard.setText(display_key)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_value", display="Copy value", func=lambda ctx: clipboard.setText(value)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_row", display="Copy row", func=lambda ctx: clipboard.setText(f"{display_key}: {value}")),
                "-",
                ActionKit.Action(path=f"inline.meta_list.{uid}.edit", display="Edit…", func=lambda ctx: self._open_edit_dialog(key)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.lock", display=lock_label, func=lambda ctx: self._toggle_lock(key)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.delete", display="Delete…", func=lambda ctx: self._confirm_delete(key)),
            ]
        )
        menu = spec.build() if spec is not None else None
        return menu if menu is not None else QtWidgets.QMenu(self)

    def _toggle_lock(self, key: str):
        if not self._can_submit():
            AppLogger.warning(f"[SearchKV] lock aborted: missing context scope={self._context.scope}")
            return
        locked = bool(self._locks.get(key, False))
        self._submit_upsert(key, self._full_value(key), not locked, lock_only=True)

    def _confirm_delete(self, key: str, *, parent: QtWidgets.QWidget | None = None, on_deleted=None):
        display_key = self._to_full(key)
        this_only = t("Only from this file")
        all_dbs = t("From All databases + filter")
        cancel = t("Cancel")
        has_prefix = bool(self._context.prefix)
        result = ConfirmDialog.ask(
            t('Do you want to delete key:\n"{key}"\nfrom table?', key=display_key),
            title=t("Delete metadata"),
            buttons=(this_only, all_dbs, cancel),
            disabled=() if has_prefix else (all_dbs,),
            parent=parent or self,
        )
        if result == this_only:
            self._submit_delete(key)
        elif result == all_dbs and has_prefix:
            self._delete_key_everywhere(key)
        else:
            return
        if on_deleted is not None:
            on_deleted()

    def _delete_key_everywhere(self, key: str):
        prefix = self._context.prefix
        if not prefix:
            return
        db_names = list_setting_db_names()
        if not db_names:
            AppLogger.warning("[SearchKV] delete-all aborted: no setting DBs")
            return
        full_key = self._to_full(key)
        KeyFilter.send_delete_keys(db_names, [full_key], prefix, re_collect=False)
        KeyFilter.apply_key_states(prefix, {key: False})
        AppLogger.info(f"[SearchKV] delete-all submitted prefix={prefix} key={full_key} dbs={len(db_names)}")


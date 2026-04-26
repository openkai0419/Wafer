from __future__ import annotations

import html
import re
from typing import Any

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.formatting import dpix, display_prefixed_key
from ...core.lang.manager import t
from ...core.color.theme import ThemeManager
from ...core.commands.bridge import ActionKit, Menu
from ...core.qt.dispatcher import Dispatcher, CancelSlot
from ...core.qt.thread import utility_pool
from .value_viewer_dialog import open_value_viewer

SHORT_VALUE_LIMIT = 1000
SNIPPET_BUDGET = SHORT_VALUE_LIMIT * 2
SNIPPET_MIN_CONTEXT = 20
MAX_VISIBLE_SNIPPETS = 20
SAFETY_CHAR_LIMIT = 1_000_000

_PAD = 6
_SPACING = 10


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


class _MetaListModel(QtCore.QAbstractListModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list[tuple[str, str]] = []

    def reset_rows(self, rows: list[tuple[str, str]]):
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
        return None


class _MetaItemDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.key_width = dpix(120)
        self._doc_cache: dict[int, tuple[QtGui.QTextDocument, QtGui.QTextDocument, int]] = {}
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
        val_w = total_w - key_w - spacing

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

        key_h = QtGui.QFontMetrics(font).height()
        h = max(key_h, int(doc_val.size().height())) + 2 * pad

        entry = (doc_key, doc_val, h)
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
        doc_key, doc_val, _ = self._get_docs(index, option.font, total_w)
        painter.translate(rect.x(), rect.y())
        doc_key.drawContents(painter)
        painter.translate(key_w + spacing, 0)
        doc_val.drawContents(painter)
        painter.restore()

    def sizeHint(self, option, index):
        pad = dpix(_PAD)
        view = option.widget
        total_w = (view.viewport().width() - 2 * pad) if view else dpix(400)
        _, _, h = self._get_docs(index, option.font, total_w)
        return QtCore.QSize(total_w + 2 * pad, h)


class SearchableMetaWidget(QtWidgets.QWidget):
    DEBOUNCE_MS = 50

    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, Any] = {}
        self._filtered_keys: list[str] = []
        self._search_index: dict[str, str] | None = None
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

    def current_query(self) -> str:
        return self._search.text().strip().lower()

    def _display_key(self, key: str) -> str:
        return display_prefixed_key(key)

    def set_data(self, data: dict[str, Any]):
        self._data = dict(data)
        self._search_index = None
        self._update_key_width()
        self._apply_filter(self._search.text())
        self._build_index_async()

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
            rows.append((key_html, val_html))

        self._delegate.invalidate_cache()
        self._model.reset_rows(rows)

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
        open_value_viewer(self, self._display_key(key), self._full_value(key))

    def _on_context_menu(self, pos: QtCore.QPoint):
        index = self._list_view.indexAt(pos)
        if not index.isValid():
            return
        key = self._key_for_row(index.row())
        if key is None:
            return
        display_key = self._display_key(key)
        value = self._full_value(key)
        self._build_context_menu(index.row(), display_key, value).exec(self._list_view.viewport().mapToGlobal(pos))

    def _build_context_menu(self, row: int, display_key: str, value: str) -> QtWidgets.QMenu:
        clipboard = QtWidgets.QApplication.clipboard()
        uid = f"{id(self):x}.{row}"
        spec = Menu.session(self).menu(
            [
                ":Meta",
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_key", display="Copy key", func=lambda ctx: clipboard.setText(display_key)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_value", display="Copy value", func=lambda ctx: clipboard.setText(value)),
                ActionKit.Action(path=f"inline.meta_list.{uid}.copy_row", display="Copy row", func=lambda ctx: clipboard.setText(f"{display_key}: {value}")),
                "-",
                ActionKit.Action(path=f"inline.meta_list.{uid}.open_value", display="Open value viewer…", func=lambda ctx: open_value_viewer(self, display_key, value)),
            ]
        )
        menu = spec.build() if spec is not None else None
        return menu if menu is not None else QtWidgets.QMenu(self)

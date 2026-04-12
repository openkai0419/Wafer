from __future__ import annotations

import json
from typing import Any
from collections.abc import Callable, Mapping

from PySide6 import QtCore, QtGui, QtWidgets

from ....utils.formatting import dpix, display_prefixed_key
from ....utils.logs import AppLogger
from ....core.lang.manager import t
from ....core.qt.icon_engine import icon_draw
from ....core.color.theme import ThemeManager

MAX_INLINE_CHARS = 4000
MAX_INLINE_SEQ_ITEMS = 50
MAX_INLINE_MAP_PAIRS = 50


def _truncate_text(s: str, limit: int = MAX_INLINE_CHARS) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n… ({len(s):,} chars total)"


def _preview_sequence(seq) -> str:
    shown = []
    for i, v in enumerate(seq):
        if i >= MAX_INLINE_SEQ_ITEMS:
            shown.append(f"… (+{len(seq) - MAX_INLINE_SEQ_ITEMS} more)")
            break
        shown.append(str(v))
    return ", ".join(shown)


def _preview_mapping(mp: Mapping[str, Any]) -> str:
    parts = []
    for i, (k, v) in enumerate(mp.items()):
        if i >= MAX_INLINE_MAP_PAIRS:
            parts.append(f"… (+{len(mp) - MAX_INLINE_MAP_PAIRS} more)")
            break
        parts.append(f"{k}: {v!r}")
    return "{ " + ", ".join(parts) + " }"


_TITLE_HEIGHT = 16
_ICON_SIZE = 8
_CARD_PADDING = 6


class CollapsibleCard(QtWidgets.QFrame):
    toggled_card = QtCore.Signal(str, bool)

    def __init__(self, title: str, key: str, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._key = key
        self._expanded = True
        self._title_base = title
        self._title_display = title

        self.setObjectName("collapsibleCard")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self._apply_stylesheet()
        self.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        th = dpix(_TITLE_HEIGHT)
        pad = dpix(_CARD_PADDING)

        self._content_layout = QtWidgets.QVBoxLayout(self)
        self._content_layout.setContentsMargins(pad, th + pad, pad, pad)
        self._content_layout.setSpacing(0)
        self._content_widget: QtWidgets.QWidget | None = None

    @property
    def key(self) -> str:
        return self._key

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool):
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._sync_content_visibility()

    def set_content_widget(self, widget: QtWidgets.QWidget):
        if self._content_widget is not None:
            self._content_layout.removeWidget(self._content_widget)
            self._content_widget.setParent(None)
            self._content_widget.deleteLater()
        self._content_widget = widget
        self._content_layout.addWidget(widget)
        self._sync_content_visibility()

    def content_widget(self) -> QtWidgets.QWidget | None:
        return self._content_widget

    def update_title_count(self, count: int):
        suffix = f"  ({count})" if count > 0 else ""
        self._title_display = f"{self._title_base}{suffix}"
        self.update()

    def title(self) -> str:
        return self._title_display

    def mousePressEvent(self, event: QtGui.QMouseEvent) -> None:
        th = dpix(_TITLE_HEIGHT)
        if event.position().y() <= th:
            self._expanded = not self._expanded
            self._sync_content_visibility()
            self.toggled_card.emit(self._key, self._expanded)
            event.accept()
            return
        super().mousePressEvent(event)

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)

        palette = ThemeManager.instance().palette
        color = QtGui.QColor(palette.text_primary)

        th = dpix(_TITLE_HEIGHT)
        pad = dpix(_CARD_PADDING)
        isz = dpix(_ICON_SIZE)

        icon_y = (th - isz) / 2
        icon_rect = QtCore.QRectF(pad, icon_y, isz, isz)
        icon_key = "chevron_down" if self._expanded else "chevron_right"
        icon_draw(icon_key, painter, icon_rect, color)

        font = painter.font()
        font.setPixelSize(dpix(11))
        painter.setFont(font)
        painter.setPen(color)
        text_x = pad + isz + dpix(4)
        text_rect = QtCore.QRectF(text_x, 0, self.width() - text_x - pad, th)
        painter.drawText(text_rect, QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft, self._title_display)

        if self._expanded:
            line_color = QtGui.QColor(palette.text_primary)
            line_color.setAlpha(40)
            painter.setPen(QtGui.QPen(line_color, 1))
            painter.drawLine(QtCore.QPointF(pad, th), QtCore.QPointF(self.width() - pad, th))

        painter.end()

    def _sync_content_visibility(self):
        th = dpix(_TITLE_HEIGHT)
        pad = dpix(_CARD_PADDING)
        if self._expanded:
            self._content_layout.setContentsMargins(pad, th + pad, pad, pad)
        else:
            self._content_layout.setContentsMargins(0, th, 0, 0)
        if self._content_widget is not None:
            self._content_widget.setVisible(self._expanded)
        self._apply_stylesheet()
        self.update()

    def _apply_stylesheet(self):
        r = dpix(6)
        self.setStyleSheet(
            f"""
            QFrame#collapsibleCard {{
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: {r}px;
            }}
            """
        )


class MetaRowWidget(QtWidgets.QFrame):
    rowActivated = QtCore.Signal(int, dict)

    def __init__(
        self,
        index: int,
        data: Mapping[str, Any],
        key_names: Mapping[str, str] | None = None,
        value_formatters: Mapping[str, Callable[[Any], str]] | None = None,
        rich_text_keys: set[str] | None = None,
        compact: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._data = dict(data)
        self._keys = list(self._data.keys())
        self._key_names = dict(key_names or {})
        self._value_formatters = dict(value_formatters or {})
        self._rich_text_keys = rich_text_keys or set()
        self._compact = compact
        self._formatter_failed_keys = set()

        self.setObjectName("dictRow")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet(
            """
            QLabel[keyRole="true"] {
                font-weight: 600;
            }
            """
        )

        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(dpix(8), dpix(4), dpix(8), dpix(8))
        self._grid.setHorizontalSpacing(dpix(12))
        self._grid.setVerticalSpacing(dpix(6) if compact else dpix(8))
        self._build()

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.mouseDoubleClickEvent = self._emit_activated  # type: ignore[assignment]

    # ---- UI events ----
    def _emit_activated(self, event: QtGui.QMouseEvent) -> None:
        self.rowActivated.emit(self._index, self._data)

    def _show_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        act_copy_json = menu.addAction(t("Copy row as JSON (full)"))
        act_copy_text_preview = menu.addAction(t("Copy preview text"))
        act_copy_value = menu.addAction(t("Copy single value\u2026"))
        act_view_value = menu.addAction(t("Open value viewer\u2026"))
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_copy_json:
            # 大きくてもユーザー操作時のみ。ここはブロックが起きても許容しやすい
            QtWidgets.QApplication.clipboard().setText(json.dumps(self._data, ensure_ascii=False, indent=2))
        elif chosen is act_copy_text_preview:
            QtWidgets.QApplication.clipboard().setText(self._to_plain_text(preview=True))
        elif chosen is act_copy_value:
            self._copy_single_value_dialog()
        elif chosen is act_view_value:
            self._open_value_viewer_dialog()

    # ---- helpers for menu ----
    def _copy_single_value_dialog(self) -> None:
        # キー選択 → 値全文コピー（巨大でもOK：ユーザー明示操作）
        key, ok = QtWidgets.QInputDialog.getItem(self, t("Copy single value"), t("Key:"), self._keys, 0, False)
        if not ok or not key:
            return
        QtWidgets.QApplication.clipboard().setText(self._stringify_full(self._data.get(key)))

    def _open_value_viewer_dialog(self) -> None:
        # キー選択 → QPlainTextEdit で全文表示
        key, ok = QtWidgets.QInputDialog.getItem(self, t("Open value viewer"), t("Key:"), self._keys, 0, False)
        if not ok or not key:
            return
        text = self._stringify_full(self._data.get(key))

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(t("Value viewer - {key}", key=key))
        dlg.resize(dpix(900), dpix(600))
        lay = QtWidgets.QVBoxLayout(dlg)
        edit = QtWidgets.QPlainTextEdit(dlg)
        edit.setReadOnly(True)
        edit.setPlainText(text)  # ✔ プレーンテキスト。大でも比較的軽い
        lay.addWidget(edit)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close, parent=dlg)
        btns.rejected.connect(dlg.reject)
        lay.addWidget(btns)
        dlg.exec()

    # ---- render helpers ----
    def _to_plain_text(self, preview: bool) -> str:
        parts = []
        for k in self._keys:
            val = self._data.get(k)
            if preview:
                parts.append(f"{self._display_key(k)}: {self._stringify_preview(k, val)}")
            else:
                parts.append(f"{self._display_key(k)}: {self._stringify_full(val)}")
        return "\n".join(parts)

    def _display_key(self, key: str) -> str:
        if key in self._key_names:
            return self._key_names[key]
        return display_prefixed_key(key)

    def _stringify_preview(self, key: str, value: Any) -> str:
        # フォーマッタはプレビューにも適用。ただし戻り値が巨大なら切る
        if key in self._value_formatters:
            try:
                s = str(self._value_formatters[key](value))
                return _truncate_text(s)
            except Exception as e:
                if key not in self._formatter_failed_keys:
                    self._formatter_failed_keys.add(key)
                    AppLogger.debug(f"MetaRowWidget formatter failed: {key} ({e})")

        if value is None:
            return "—"
        if isinstance(value, str):
            return _truncate_text(value)
        if isinstance(value, (list, tuple, set)):
            return _preview_sequence(value)
        if isinstance(value, Mapping):
            # フルJSONは重いので、軽い概要だけ
            return _preview_mapping(value)
        if isinstance(value, (QtCore.QDate, QtCore.QDateTime, QtCore.QTime)):
            return str(value.toString(QtCore.Qt.ISODate))
        return _truncate_text(str(value))

    def _stringify_full(self, value: Any) -> str:
        # フル版（ユーザーが明示操作した時のみ使う）
        if value is None:
            return "—"
        if isinstance(value, Mapping):
            try:
                return json.dumps(value, ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                return str(value)
        if isinstance(value, (list, tuple, set)):
            try:
                return json.dumps(list(value), ensure_ascii=False, indent=2)
            except (TypeError, ValueError):
                return str(value)
        if isinstance(value, (QtCore.QDate, QtCore.QDateTime, QtCore.QTime)):
            return str(value.toString(QtCore.Qt.ISODate))
        return str(value)

    def _build(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._val_labels = {}
        for row, key in enumerate(self._keys):
            key_label = QtWidgets.QLabel(self._display_key(key), self)
            key_label.setProperty("keyRole", True)
            key_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            key_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            key_label.setTextFormat(QtCore.Qt.PlainText)

            val = self._stringify_preview(key, self._data.get(key))
            val_label = QtWidgets.QLabel(val, self)
            val_label.setWordWrap(True)
            val_label.setTextFormat(QtCore.Qt.RichText if key in self._rich_text_keys else QtCore.Qt.PlainText)
            val_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            val_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

            self._grid.addWidget(key_label, row, 0)
            self._grid.addWidget(val_label, row, 1)
            self._val_labels[key] = val_label

        self._grid.setColumnStretch(1, 1)

    def update_data(self, data: Mapping[str, Any]) -> None:
        new_keys = list(data.keys())
        if new_keys == self._keys and hasattr(self, "_val_labels"):
            self._data = dict(data)
            for key in self._keys:
                val = self._stringify_preview(key, self._data.get(key))
                self._val_labels[key].setText(val)
        else:
            self._data = dict(data)
            self._keys = new_keys
            self._build()

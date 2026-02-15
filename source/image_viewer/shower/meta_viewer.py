from __future__ import annotations

import json
from typing import Any, Callable, Iterable, Mapping

from PySide6 import QtCore, QtGui, QtWidgets

from ...common.funcs import uipx
from ...common.profiling import profiler
from ...common.logs import AppLogger


# ---- 追加：巨大値対策のしきい値 ----
MAX_INLINE_CHARS = 4000          # ラベルにそのまま載せる最大文字数
MAX_INLINE_SEQ_ITEMS = 50         # 配列/集合のプレビュー最大要素数
MAX_INLINE_MAP_PAIRS = 50         # マップのプレビュー最大ペア数


def _truncate_text(s: str, limit: int = MAX_INLINE_CHARS) -> str:
    if len(s) <= limit:
        return s
    return s[:limit] + f"\n… ({len(s):,} chars total)"


def _preview_sequence(seq) -> str:
    shown = []
    for i, v in enumerate(seq):
        if i >= MAX_INLINE_SEQ_ITEMS:
            shown.append(f"… (+{len(seq)-MAX_INLINE_SEQ_ITEMS} more)")
            break
        shown.append(str(v))
    return ", ".join(shown)


def _preview_mapping(mp: Mapping[str, Any]) -> str:
    parts = []
    for i, (k, v) in enumerate(mp.items()):
        if i >= MAX_INLINE_MAP_PAIRS:
            parts.append(f"… (+{len(mp)-MAX_INLINE_MAP_PAIRS} more)")
            break
        parts.append(f"{k}: {v!r}")
    return "{ " + ", ".join(parts) + " }"


class MetaRowWidget(QtWidgets.QFrame):
    rowActivated = QtCore.Signal(int, dict)

    def __init__(
        self,
        index: int,
        data: Mapping[str, Any],
        key_names: Mapping[str, str] | None = None,
        value_formatters: Mapping[str, Callable[[Any], str]] | None = None,
        compact: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._data = dict(data)
        self._keys = list(self._data.keys())  # 行ごとに自身のキー順
        self._key_names = dict(key_names or {})
        self._value_formatters = dict(value_formatters or {})
        self._compact = compact
        self._formatter_failed_keys = set()

        self.setObjectName("dictRow")
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setStyleSheet(
            """
            QFrame#dictRow {
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: 12px;
            }
            QLabel[keyRole="true"] {
                font-weight: 600;
            }
            """
        )

        self._grid = QtWidgets.QGridLayout(self)
        self._grid.setContentsMargins(uipx(12), uipx(12), uipx(12), uipx(12))
        self._grid.setHorizontalSpacing(uipx(12))
        self._grid.setVerticalSpacing(uipx(6) if compact else uipx(8))
        self._build()

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.mouseDoubleClickEvent = self._emit_activated  # type: ignore[assignment]

    # ---- UI events ----
    def _emit_activated(self, event: QtGui.QMouseEvent) -> None:
        self.rowActivated.emit(self._index, self._data)

    def _show_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        act_copy_json = menu.addAction("Copy row as JSON (full)")
        act_copy_text_preview = menu.addAction("Copy preview text")
        act_copy_value = menu.addAction("Copy single value…")
        act_view_value = menu.addAction("Open value viewer…")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_copy_json:
            # 大きくてもユーザー操作時のみ。ここはブロックが起きても許容しやすい
            QtWidgets.QApplication.clipboard().setText(
                json.dumps(self._data, ensure_ascii=False, indent=2)
            )
        elif chosen is act_copy_text_preview:
            QtWidgets.QApplication.clipboard().setText(self._to_plain_text(preview=True))
        elif chosen is act_copy_value:
            self._copy_single_value_dialog()
        elif chosen is act_view_value:
            self._open_value_viewer_dialog()

    # ---- helpers for menu ----
    def _copy_single_value_dialog(self) -> None:
        # キー選択 → 値全文コピー（巨大でもOK：ユーザー明示操作）
        key, ok = QtWidgets.QInputDialog.getItem(
            self, "Copy single value", "Key:", self._keys, 0, False
        )
        if not ok or not key:
            return
        QtWidgets.QApplication.clipboard().setText(self._stringify_full(self._data.get(key)))

    def _open_value_viewer_dialog(self) -> None:
        # キー選択 → QPlainTextEdit で全文表示
        key, ok = QtWidgets.QInputDialog.getItem(
            self, "Open value viewer", "Key:", self._keys, 0, False
        )
        if not ok or not key:
            return
        text = self._stringify_full(self._data.get(key))

        dlg = QtWidgets.QDialog(self)
        dlg.setWindowTitle(f"Value viewer - {key}")
        dlg.resize(900, 600)
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
        return self._key_names.get(key, key)

    def _stringify_preview(self, key: str, value: Any) -> str:
        # フォーマッタはプレビューにも適用。ただし戻り値が巨大なら切る
        if key in self._value_formatters:
            try:
                s = str(self._value_formatters[key](value))
                return _truncate_text(s)
            except Exception as e:
                if key not in self._formatter_failed_keys:
                    self._formatter_failed_keys.add(key)
                    AppLogger.debug(f'MetaRowWidget formatter failed: {key} ({e})')

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
            except Exception:
                return str(value)
        if isinstance(value, (list, tuple, set)):
            try:
                return json.dumps(list(value), ensure_ascii=False, indent=2)
            except Exception:
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
        row = 0
        for key in self._keys:
            key_label = QtWidgets.QLabel(self._display_key(key), self)
            key_label.setProperty("keyRole", True)
            key_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            key_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            key_label.setTextFormat(QtCore.Qt.PlainText)

            val = self._stringify_preview(key, self._data.get(key))
            val_label = QtWidgets.QLabel(val, self)
            val_label.setWordWrap(True)
            val_label.setTextFormat(QtCore.Qt.PlainText)
            val_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            val_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

            self._grid.addWidget(key_label, row, 0)
            self._grid.addWidget(val_label, row, 1)
            self._val_labels[key] = val_label
            row += 1

        self._grid.setColumnStretch(1, 1)

    def update_data(self, data: Mapping[str, Any]) -> None:
        new_keys = list(data.keys())
        if new_keys == self._keys and hasattr(self, '_val_labels'):
            self._data = dict(data)
            for key in self._keys:
                val = self._stringify_preview(key, self._data.get(key))
                self._val_labels[key].setText(val)
        else:
            self._data = dict(data)
            self._keys = new_keys
            self._build()


class MetaListWidget(QtWidgets.QWidget):
    rowActivated = QtCore.Signal(int, dict)

    def __init__(
        self,
        items: Iterable[Mapping[str, Any]] | None = None,
        key_names: Mapping[str, str] | None = None,
        value_formatters: Mapping[str, Callable[[Any], str]] | None = None,
        compact: bool = True,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list[dict] = []
        self._key_names = dict(key_names or {})
        self._value_formatters = dict(value_formatters or {})
        self._compact = compact

        self.setObjectName("dictList")
        self.setStyleSheet(
            """
            QWidget#dictList {
                background: transparent;
            }
            """
        )

        self._layout = QtWidgets.QVBoxLayout(self)
        self._layout.setContentsMargins(0, uipx(5), uipx(4), uipx(5))
        self._layout.setSpacing(uipx(10) if compact else uipx(14))
        self._layout.addStretch(1)

        if items is not None:
            self.set_data(items)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(760, super().sizeHint().height())

    def set_data(self, items: Iterable[Mapping[str, Any]]) -> None:
        new_items = [dict(i) for i in items]
        if len(new_items) == len(self._items):
            for idx, it in enumerate(new_items):
                self._items[idx] = it
                w = self._layout.itemAt(idx).widget()
                if isinstance(w, MetaRowWidget):
                    w.update_data(it)
            return
        self.clear()
        self._items = new_items
        for idx, it in enumerate(self._items):
            row = MetaRowWidget(
                idx,
                it,
                key_names=self._key_names,
                value_formatters=self._value_formatters,
                compact=self._compact,
                parent=self,
            )
            row.rowActivated.connect(self.rowActivated.emit)
            self._layout.insertWidget(self._layout.count() - 1, row)

    def clear(self) -> None:
        for i in reversed(range(self._layout.count())):
            item = self._layout.itemAt(i)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        if self._layout.count() == 0:
            self._layout.addStretch(1)
        self._items.clear()

    def add_item(self, item: Mapping[str, Any]) -> None:
        idx = len(self._items)
        self._items.append(dict(item))
        row = MetaRowWidget(
            idx,
            self._items[-1],
            key_names=self._key_names,
            value_formatters=self._value_formatters,
            compact=self._compact,
            parent=self,
        )
        row.rowActivated.connect(self.rowActivated.emit)
        self._layout.insertWidget(self._layout.count() - 1, row)

    def update_item(self, index: int, item: Mapping[str, Any]) -> None:
        if index < 0 or index >= len(self._items):
            return
        self._items[index] = dict(item)
        w = self._layout.itemAt(index).widget()  # type: ignore[assignment]
        if isinstance(w, MetaRowWidget):
            w.update_data(self._items[index])

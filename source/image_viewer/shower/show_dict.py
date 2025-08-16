from __future__ import annotations

import json
from collections import OrderedDict
from typing import Any, Callable, Iterable, Mapping, Sequence

from PySide6 import QtCore, QtGui, QtWidgets


class DictRowWidget(QtWidgets.QFrame):
    rowActivated = QtCore.Signal(int, dict)

    def __init__(
        self,
        index: int,
        data: Mapping[str, Any],
        keys: Sequence[str],
        key_names: Mapping[str, str] | None = None,
        value_formatters: Mapping[str, Callable[[Any], str]] | None = None,
        compact: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._index = index
        self._data = dict(data)
        self._keys = list(keys)
        self._key_names = dict(key_names or {})
        self._value_formatters = dict(value_formatters or {})
        self._compact = compact

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
        self._grid.setContentsMargins(12, 10, 12, 10)
        self._grid.setHorizontalSpacing(12)
        self._grid.setVerticalSpacing(6 if compact else 8)
        self._build()

        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self.mouseDoubleClickEvent = self._emit_activated  # type: ignore[assignment]

    def _emit_activated(self, event: QtGui.QMouseEvent) -> None:
        self.rowActivated.emit(self._index, self._data)

    def _show_menu(self, pos: QtCore.QPoint) -> None:
        menu = QtWidgets.QMenu(self)
        act_copy_json = menu.addAction("Copy row as JSON")
        act_copy_text = menu.addAction("Copy as plain text")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_copy_json:
            QtWidgets.QApplication.clipboard().setText(json.dumps(self._data, ensure_ascii=False, indent=2))
        elif chosen is act_copy_text:
            QtWidgets.QApplication.clipboard().setText(self._to_plain_text())

    def _to_plain_text(self) -> str:
        parts = []
        for k in self._keys:
            parts.append(f"{self._display_key(k)}: {self._stringify(k, self._data.get(k))}")
        return "\n".join(parts)

    def _display_key(self, key: str) -> str:
        return self._key_names.get(key, key)

    def _stringify(self, key: str, value: Any) -> str:
        if key in self._value_formatters:
            try:
                return str(self._value_formatters[key](value))
            except Exception:
                pass
        if value is None:
            return "—"
        if isinstance(value, (list, tuple, set)):
            return ", ".join(map(self._stringify_default, value))
        if isinstance(value, Mapping):
            try:
                return json.dumps(value, ensure_ascii=False)
            except Exception:
                return str(value)
        return self._stringify_default(value)

    def _stringify_default(self, v: Any) -> str:
        if isinstance(v, (QtCore.QDate, QtCore.QDateTime, QtCore.QTime)):
            return str(v.toString(QtCore.Qt.ISODate))
        return str(v)

    def _build(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        row = 0
        for key in self._keys:
            key_label = QtWidgets.QLabel(self._display_key(key), self)
            key_label.setProperty("keyRole", True)
            key_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            key_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)

            val_label = QtWidgets.QLabel(self._stringify(key, self._data.get(key)), self)
            val_label.setWordWrap(True)
            val_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse | QtCore.Qt.LinksAccessibleByMouse)
            val_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

            self._grid.addWidget(key_label, row, 0)
            self._grid.addWidget(val_label, row, 1)
            row += 1
        self._grid.setColumnStretch(1, 1)

    def update_data(self, data: Mapping[str, Any]) -> None:
        self._data = dict(data)
        self._build()


class DictListWidget(QtWidgets.QWidget):
    rowActivated = QtCore.Signal(int, dict)

    def __init__(
        self,
        items: Iterable[Mapping[str, Any]] | None = None,
        keys: Sequence[str] | None = None,
        key_names: Mapping[str, str] | None = None,
        value_formatters: Mapping[str, Callable[[Any], str]] | None = None,
        compact: bool = False,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._items: list[dict] = []
        self._keys: list[str] = list(keys) if keys else []
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
        self._layout.setContentsMargins(12, 12, 12, 12)
        self._layout.setSpacing(10 if compact else 14)
        self._layout.addStretch(1)

        if items is not None:
            self.set_data(items)

    def sizeHint(self) -> QtCore.QSize:
        return QtCore.QSize(760, super().sizeHint().height())

    def set_data(self, items: Iterable[Mapping[str, Any]]) -> None:
        self.clear()
        resolved = [dict(i) for i in items]
        if not self._keys:
            seen = OrderedDict()
            for it in resolved:
                for k in it.keys():
                    if k not in seen:
                        seen[k] = None
            self._keys = list(seen.keys())
        self._items = resolved
        for idx, it in enumerate(self._items):
            row = DictRowWidget(
                idx,
                it,
                self._keys,
                key_names=self._key_names,
                value_formatters=self._value_formatters,
                compact=self._compact,
                parent=self,
            )
            row.rowActivated.connect(self.rowActivated)
            self._layout.insertWidget(self._layout.count() - 1, row)

    def clear(self) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            w.setParent(None)
            w.deleteLater()
        self._layout.addStretch(1)
        self._items.clear()

    def add_item(self, item: Mapping[str, Any]) -> None:
        idx = len(self._items)
        self._items.append(dict(item))
        row = DictRowWidget(
            idx,
            self._items[-1],
            self._keys or list(self._items[-1].keys()),
            key_names=self._key_names,
            value_formatters=self._value_formatters,
            compact=self._compact,
            parent=self,
        )
        row.rowActivated.connect(self.rowActivated)
        self._layout.insertWidget(self._layout.count() - 1, row)

    def update_item(self, index: int, item: Mapping[str, Any]) -> None:
        if index < 0 or index >= len(self._items):
            return
        self._items[index] = dict(item)
        row = self._layout.itemAt(index).widget()  # type: ignore[assignment]
        if isinstance(row, DictRowWidget):
            row.update_data(self._items[index])

    def set_keys(self, keys: Sequence[str]) -> None:
        self._keys = list(keys)
        for i in range(len(self._items)):
            row = self._layout.itemAt(i).widget()  # type: ignore[assignment]
            if isinstance(row, DictRowWidget):
                row._keys = self._keys
                row._build()


def create_scrolled(widget: QtWidgets.QWidget, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QScrollArea:
    area = QtWidgets.QScrollArea(parent)
    area.setWidgetResizable(True)
    area.setFrameShape(QtWidgets.QFrame.NoFrame)
    area.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    area.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
    area.setWidget(widget)
    return area


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)

    sample = [
        {
            "id": 1,
            "title": "Sunset at the beach",
            "tags": ["sunset", "sea", "travel"],
            "rating": 4.7,
            "path": "C:/images/2025-08-12/sunset.jpg",
        },
        {
            "id": 2,
            "title": "Mountain trail",
            "tags": ["hike", "nature"],
            "rating": 4.2,
            "path": "C:/images/2025-07-05/mountain.png",
            "note": "Shot on Pixel in RAW",
        },
        {
            "id": 3,
            "title": "City skyline",
            "tags": ["city", "night"],
            "rating": 4.9,
            "path": "C:/images/2025-08-01/city.webp",
        },
    ]

    key_names = {"id": "ID", "title": "Title", "tags": "Tags", "rating": "Rating", "path": "Path", "note": "Note"}

    view = DictListWidget(sample, compact=False)
    area = create_scrolled(view)

    w = QtWidgets.QMainWindow()
    w.setWindowTitle("DictListWidget Demo")
    w.setCentralWidget(area)
    w.resize(880, 680)
    w.show()

    sys.exit(app.exec())

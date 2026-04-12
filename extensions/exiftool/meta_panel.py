from __future__ import annotations

from typing import Any

from PySide6 import QtCore, QtWidgets

from wafer.plugin import BaseMetaPanelPlugin
from wafer.utils.formatting import dpix
from wafer.core.lang.manager import t


class ExifToolMetaPanelPlugin(BaseMetaPanelPlugin):
    NAME = "exiftool_meta_panel"
    PREFIX = "exiftool"
    DISPLAY_NAME = "ExifTool"
    DEFAULT_ENABLED = True
    PRIORITY = 50

    def __init__(self):
        self._widget: _ExifToolMetaWidget | None = None

    def create_widget(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._widget = _ExifToolMetaWidget(parent)
        return self._widget

    def update_data(self, data: dict) -> None:
        if self._widget is not None:
            self._widget.set_data(data)


class _ExifToolMetaWidget(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget | None = None) -> None:
        super().__init__(parent)
        self._data: dict[str, Any] = {}
        self._filtered_keys: list[str] = []

        self._search = QtWidgets.QLineEdit(self)
        self._search.setPlaceholderText(t("Search key or value…"))
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._apply_filter)

        self._grid_container = QtWidgets.QWidget(self)
        self._grid_container.setObjectName("exifMetaGrid")
        self._grid_container.setStyleSheet(
            f"""
            QWidget#exifMetaGrid {{
                background: palette(base);
                border: 1px solid palette(mid);
                border-radius: {dpix(12)}px;
            }}
            QLabel[keyRole="true"] {{
                font-weight: 600;
            }}
            """
        )
        self._grid = QtWidgets.QGridLayout(self._grid_container)
        self._grid.setContentsMargins(dpix(12), dpix(12), dpix(12), dpix(12))
        self._grid.setHorizontalSpacing(dpix(12))
        self._grid.setVerticalSpacing(dpix(6))

        self._status_label = QtWidgets.QLabel(self)
        self._status_label.setAlignment(QtCore.Qt.AlignRight)
        self._status_label.setStyleSheet(f"color: palette(dark); font-size: {dpix(11)}px;")

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(6))
        layout.addWidget(self._search)
        layout.addWidget(self._status_label)
        layout.addWidget(self._grid_container)

    def set_data(self, data: dict[str, Any]):
        self._data = dict(data)
        self._apply_filter(self._search.text())

    def _apply_filter(self, text: str):
        query = text.strip().lower()
        if not query:
            self._filtered_keys = list(self._data.keys())
        else:
            self._filtered_keys = [k for k, v in self._data.items() if query in k.lower() or query in str(v).lower()]
        self._rebuild_grid()

    def _rebuild_grid(self):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        total = len(self._data)
        shown = len(self._filtered_keys)
        if total > 0 and shown != total:
            self._status_label.setText(f"{shown} / {total}")
            self._status_label.setVisible(True)
        else:
            self._status_label.setVisible(False)

        for row, key in enumerate(self._filtered_keys):
            key_label = QtWidgets.QLabel(key, self._grid_container)
            key_label.setProperty("keyRole", True)
            key_label.setAlignment(QtCore.Qt.AlignTop | QtCore.Qt.AlignLeft)
            key_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            key_label.setTextFormat(QtCore.Qt.PlainText)

            val = str(self._data.get(key, ""))
            if len(val) > 4000:
                val = val[:4000] + f"\n… ({len(val):,} chars total)"
            val_label = QtWidgets.QLabel(val, self._grid_container)
            val_label.setTextFormat(QtCore.Qt.PlainText)
            val_label.setWordWrap(True)
            val_label.setTextInteractionFlags(QtCore.Qt.TextSelectableByMouse)
            val_label.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)

            self._grid.addWidget(key_label, row, 0)
            self._grid.addWidget(val_label, row, 1)

        self._grid.setColumnStretch(1, 1)

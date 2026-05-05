from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from wafer.core.commands.bridge import ActionKit, Menu
from wafer.core.color.theme import ThemeManager
from wafer.plugin import BaseTagPanelPlugin
from wafer.ui.panel.meta_viewer import CollapsibleCard
from wafer.ui.widgets import FlowLayout
from wafer.utils.formatting import dpix

from ._color import packed_to_hex
from .commands import apply_color_filter, apply_selected_color
from .settings import ColorSettings, palette_keys


class ColorTagPanelPlugin(BaseTagPanelPlugin):
    NAME = "color_panel"
    PREFIX = "color"
    DEFAULT_ENABLED = True
    PRIORITY = 45

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._row: _PaletteRow | None = None
        self._tags: dict[str, str] = {}
        ColorSettings.instance().changed.connect(self._refresh_colors)

    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._card = CollapsibleCard(self.PREFIX, f"tag:{self.PREFIX}", parent)
        self._row = _PaletteRow(self._card)
        self._card.set_content_widget(self._row)
        return self._card

    def update_data(self, tags: dict[str, str], locks: dict[str, bool], path: str, file_hash: str, db: str) -> None:
        self._tags = dict(tags or {})
        self._refresh_colors()

    def _refresh_colors(self) -> None:
        colors = [packed_to_hex(self._tags.get(key)) for key in palette_keys()]
        colors = [c for c in colors if c]
        if self._row is not None:
            self._row.set_colors(colors)
        if self._card is not None:
            self._card.update_title_count(len(colors))


class _PaletteRow(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._buttons: list[_ColorButton] = []
        self._layout = FlowLayout(self, margin=dpix(2), spacing=dpix(4))
        self.setLayout(self._layout)

    def set_colors(self, colors: list[str]):
        for btn in self._buttons:
            self._layout.removeWidget(btn)
            btn.setParent(None)
            btn.deleteLater()
        self._buttons.clear()
        for color in colors:
            btn = _ColorButton(color, self)
            self._buttons.append(btn)
            self._layout.addWidget(btn)
        self.updateGeometry()


class _ColorButton(QtWidgets.QToolButton):
    def __init__(self, hex_color: str, parent=None):
        super().__init__(parent)
        self._hex = hex_color
        self.setFixedSize(dpix(30), dpix(20))
        self.setCursor(QtCore.Qt.PointingHandCursor)
        self.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.clicked.connect(self._add_to_filter)
        self.customContextMenuRequested.connect(self._show_menu)
        self._sync_style()

    def _sync_style(self):
        p = ThemeManager.instance().palette
        self.setToolTip(self._hex)
        self.setStyleSheet(
            f"QToolButton {{ background: {self._hex}; border: 1px solid {p.border_default}; border-radius: {dpix(4)}px; }}QToolButton:hover {{ border: {dpix(2)}px solid {p.text_primary}; }}"
        )

    def _show_menu(self, pos: QtCore.QPoint):
        spec = Menu.session(self).menu(self._menu_items())
        if spec is not None:
            spec.exec(self.mapToGlobal(pos))

    def _menu_items(self) -> list:
        uid = f"{id(self):x}"
        return [
            ":Color Search",
            ActionKit.Action(path=f"inline.color.{uid}.apply_selected", display="Override selected color", func=lambda ctx: self._apply_selected()),
            "-",
            ActionKit.Action(path=f"inline.color.{uid}.append", display="Add to color filter", func=lambda ctx: self._add_to_filter()),
        ]

    def _apply_selected(self):
        apply_selected_color(hex_color=self._hex)

    def _add_to_filter(self):
        apply_color_filter(hex_color=self._hex, tolerance=0.2)

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from wafer.core.commands.bridge import ActionKit, Command, Menu
from wafer.core.color.theme import ThemeManager
from wafer.plugin import BaseTagPanelPlugin
from wafer.ui.panel.meta_viewer import CollapsibleCard
from wafer.ui.widgets import FlowLayout
from wafer.utils.formatting import dpix

from ._color import PALETTE_KEYS, packed_to_hex


class ColorTagPanelPlugin(BaseTagPanelPlugin):
    NAME = "color_panel"
    PREFIX = "color"
    DEFAULT_ENABLED = True
    PRIORITY = 45

    def __init__(self):
        self._card: CollapsibleCard | None = None
        self._row: _PaletteRow | None = None

    def create_card(self, parent: QtWidgets.QWidget | None = None) -> QtWidgets.QWidget:
        self._card = CollapsibleCard(self.PREFIX, f"tag:{self.PREFIX}", parent)
        self._row = _PaletteRow(self._card)
        self._card.set_content_widget(self._row)
        return self._card

    def update_data(self, tags: dict[str, str], locks: dict[str, bool], path: str, file_hash: str, db: str) -> None:
        colors = [packed_to_hex(tags.get(key)) for key in PALETTE_KEYS]
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
        self.clicked.connect(lambda: Command.invoke("color_search.apply_selected_color", hex_color=self._hex))
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
            ActionKit.Action(path=f"inline.color.{uid}.apply_selected", display="Apply to selected color", func=lambda ctx: self._apply_selected()),
            "-",
            ActionKit.Action(path=f"inline.color.{uid}.append_and", display="Add as row AND", func=lambda ctx: self._append("append_and")),
            ActionKit.Action(path=f"inline.color.{uid}.append_or", display="Add as row OR", func=lambda ctx: self._append("append_or")),
        ]

    def _apply_selected(self):
        Command.invoke("color_search.apply_selected_color", hex_color=self._hex)

    def _append(self, mode: str):
        Command.invoke("color_search.apply_filter", hex_color=self._hex, tolerance=0.2, mode=mode, join="OR")

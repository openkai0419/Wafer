from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from os import stat_result
from pathlib import Path

from PySide6 import QtCore, QtWidgets
from PySide6.QtCore import Qt, Signal

from ..registry import PluginBase
from ...utils.formatting import dpix
from ...core.color.theme import ThemeManager


@dataclass
class SegmentInfo:
    index: int
    total: int
    original_path: Path
    stem: str
    ext: str
    metadata: dict[str, str] = field(default_factory=dict)
    stat: stat_result | None = None


def style_input(p):
    return (
        f"background: {p.bg_primary}; color: {p.text_primary}; "
        f"border: 1px solid {p.border_subtle}; border-radius: {dpix(3)}px; "
        f"padding: {dpix(2)}px {dpix(4)}px; font-size: {dpix(11)}px;"
    )


def style_dropdown(p):
    return (
        f"QPushButton {{ background: transparent; color: {p.text_primary}; "
        f"border: 1px solid {p.border_subtle}; border-radius: {dpix(3)}px; "
        f"padding: {dpix(2)}px {dpix(6)}px; font-size: {dpix(11)}px; text-align: left; }}"
        f"QPushButton:hover {{ background: {p.bg_hover}; }}"
    )


def style_action(p):
    return (
        f"QPushButton {{ color: {p.text_primary}; background: transparent; "
        f"border: 1px solid {p.border_subtle}; border-radius: {dpix(3)}px; "
        f"padding: {dpix(3)}px {dpix(8)}px; font-size: {dpix(11)}px; }}"
        f"QPushButton:hover {{ background: {p.bg_hover}; }}"
    )


def style_toggle(p):
    return (
        f"QPushButton {{ color: {p.text_primary}; background: transparent; "
        f"border: 1px solid {p.border_subtle}; border-radius: {dpix(3)}px; "
        f"padding: {dpix(3)}px {dpix(8)}px; font-size: {dpix(11)}px; text-align: left; }}"
        f"QPushButton:hover {{ background: {p.bg_hover}; }}"
        f"QPushButton:checked {{ border-color: {p.accent}; }}"
    )


def style_spinbox(p):
    bw = dpix(16)
    ah = dpix(4)
    return (
        f"QSpinBox {{ background: {p.bg_primary}; color: {p.text_primary}; "
        f"border: 1px solid {p.border_subtle}; border-radius: {dpix(3)}px; "
        f"padding: {dpix(2)}px {bw + dpix(2)}px {dpix(2)}px {dpix(4)}px; "
        f"font-size: {dpix(11)}px; }}"
        f"QSpinBox::up-button, QSpinBox::down-button {{ "
        f"width: {bw}px; border: none; background: transparent; }}"
        f"QSpinBox::up-button:hover, QSpinBox::down-button:hover {{ "
        f"background: {p.bg_hover}; }}"
        f"QSpinBox::up-arrow {{ "
        f"width: 0; height: 0; "
        f"border-left: {ah}px solid transparent; border-right: {ah}px solid transparent; "
        f"border-bottom: {ah}px solid {p.text_secondary}; }}"
        f"QSpinBox::down-arrow {{ "
        f"width: 0; height: 0; "
        f"border-left: {ah}px solid transparent; border-right: {ah}px solid transparent; "
        f"border-top: {ah}px solid {p.text_secondary}; }}"
    )


class DropdownButton(QtWidgets.QPushButton):
    value_changed = Signal(str)

    def __init__(self, label, choices, current='', parent=None):
        super().__init__(parent)
        self._label = label
        self._choices = list(choices)
        self._value = current or (choices[0] if choices else '')
        self.setCursor(Qt.PointingHandCursor)
        self._update_text()
        self.clicked.connect(self._show_menu)

    def _show_menu(self):
        menu = QtWidgets.QMenu(self)
        for c in self._choices:
            act = menu.addAction(c)
            act.triggered.connect(lambda _, v=c: self._pick(v))
        menu.exec(self.mapToGlobal(QtCore.QPoint(0, self.height())))

    def _pick(self, v):
        self._value = v
        self._update_text()
        self.value_changed.emit(v)

    def _update_text(self):
        self.setText(f'{self._label}: {self._value}')

    def value(self):
        return self._value


class ToggleButton(QtWidgets.QPushButton):

    def __init__(self, label, checked=False, parent=None):
        super().__init__(parent)
        self._label = label
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setChecked(checked)
        self._update_text()
        self.toggled.connect(lambda _: self._update_text())

    def _update_text(self):
        indicator = '\u25be' if self.isChecked() else '\u25b8'
        self.setText(f'{indicator} {self._label}')


class RenameConfigWidget(QtWidgets.QWidget):
    changed = Signal()

    def connect_extra(self, target):
        pass


class BaseRenameSourcePlugin(PluginBase, ABC):
    DISPLAY: str = ''

    @abstractmethod
    def evaluate(self, segment: SegmentInfo) -> str: ...

    def serialise(self) -> dict:
        return {'type': self.NAME}

    def _apply(self, data: dict):
        pass

    def create_config_widget(
        self, parent: QtWidgets.QWidget | None = None, **context,
    ) -> RenameConfigWidget | None:
        return None

    def read_config(self, widget: QtWidgets.QWidget):
        pass

    def write_config(self, widget: QtWidgets.QWidget, data: dict):
        pass

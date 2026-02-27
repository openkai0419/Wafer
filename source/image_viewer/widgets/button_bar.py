from PySide6 import QtWidgets
from PySide6.QtCore import QSize
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QSpacerItem, QWidget
from ...common.funcs import uipx

class IconButtonConfig:

    def __init__(self, icon_path, tooltip='', callback=None, checkable=False, checked=False):
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.callback = callback
        self.checkable = checkable
        self.checked = checked

class IconButtonBar(QWidget):

    def __init__(self, left_buttons=None, right_buttons=None, icon_size=None):
        super().__init__()
        self.icon_size = icon_size or QSize(uipx(15), uipx(15))
        self.left_buttons = []
        self.right_buttons = []
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self._add_button_group(left_buttons or [], side='left')
        self._add_spacer()
        self._add_button_group(right_buttons or [], side='right')

    def _add_button_group(self, configs, side='left'):
        for cfg in configs:
            btn = QtWidgets.QPushButton()
            btn.setIcon(QIcon(cfg.icon_path))
            btn.setIconSize(self.icon_size)
            btn.setToolTip(cfg.tooltip)
            btn.setCheckable(cfg.checkable)
            if btn.isCheckable():
                btn.setChecked(cfg.checked)
                if cfg.callback:
                    btn.toggled.connect(cfg.callback)
            elif cfg.callback:
                btn.clicked.connect(cfg.callback)
            self.layout.addWidget(btn)
            if side == 'left':
                self.left_buttons.append(btn)
            else:
                self.right_buttons.append(btn)

    def _add_spacer(self):
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.layout.addItem(spacer)

    def set_button_enabled(self, index, enabled=True, side='left'):
        target = self.left_buttons if side == 'left' else self.right_buttons
        if 0 <= index < len(target):
            target[index].setEnabled(enabled)

    def toggle_button(self, index, checked=None, side='left'):
        target = self.left_buttons if side == 'left' else self.right_buttons
        if 0 <= index < len(target):
            if checked is None:
                checked = not target[index].isChecked()
            target[index].setChecked(checked)

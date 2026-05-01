from PySide6 import QtWidgets
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QHBoxLayout, QSizePolicy, QSpacerItem, QWidget
from ....utils.formatting import dpix
from ....core.qt.icon_engine import themed_icon
from ....core.color.theme import ThemeManager


class IconButtonConfig:
    def __init__(self, icon_key, tooltip="", callback=None, checkable=False, checked=False, margin=0.0):
        self.icon_key = icon_key
        self.tooltip = tooltip
        self.callback = callback
        self.checkable = checkable
        self.checked = checked
        self.margin = margin


class IconButtonBar(QWidget):
    def __init__(self, left_buttons=None, right_buttons=None, icon_size=None):
        super().__init__()
        self.icon_size = icon_size or QSize(dpix(15), dpix(15))
        self.left_buttons = []
        self.right_buttons = []
        self._buttons_by_side_key = {"left": {}, "right": {}}
        self._icon_keys: list[tuple[QtWidgets.QPushButton, str, float]] = []
        self.layout = QHBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self._add_button_group(left_buttons or [], side="left")
        self._add_spacer()
        self._add_button_group(right_buttons or [], side="right")
        ThemeManager.instance().on_theme_changed.connect(self._on_theme_changed)

    def _on_theme_changed(self, palette):
        for btn, key, margin in self._icon_keys:
            btn.setIcon(themed_icon(key, margin=margin))

    def _add_button_group(self, configs, side="left"):
        for cfg in configs:
            btn = QtWidgets.QPushButton()
            btn.setIcon(themed_icon(cfg.icon_key, margin=cfg.margin))
            btn.setIconSize(self.icon_size)
            self._icon_keys.append((btn, cfg.icon_key, cfg.margin))
            self._buttons_by_side_key.setdefault(side, {})[cfg.icon_key] = btn
            btn.setToolTip(cfg.tooltip)
            btn.setCheckable(cfg.checkable)
            if btn.isCheckable():
                btn.setChecked(cfg.checked)
                if cfg.callback:
                    btn.toggled.connect(cfg.callback)
            elif cfg.callback:
                btn.clicked.connect(cfg.callback)
            self.layout.addWidget(btn)
            if side == "left":
                self.left_buttons.append(btn)
            else:
                self.right_buttons.append(btn)

    def _add_spacer(self):
        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        self.layout.addItem(spacer)

    def set_button_enabled(self, index, enabled=True, side="left"):
        target = self.left_buttons if side == "left" else self.right_buttons
        if 0 <= index < len(target):
            target[index].setEnabled(enabled)

    def toggle_button(self, index, checked=None, side="left"):
        target = self.left_buttons if side == "left" else self.right_buttons
        if 0 <= index < len(target):
            if checked is None:
                checked = not target[index].isChecked()
            target[index].setChecked(checked)

    def find_button(self, icon_key: str, side: str | None = None):
        if side:
            return self._buttons_by_side_key.get(side, {}).get(icon_key)
        left = self._buttons_by_side_key.get("left", {})
        if icon_key in left:
            return left[icon_key]
        return self._buttons_by_side_key.get("right", {}).get(icon_key)

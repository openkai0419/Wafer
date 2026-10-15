from __future__ import annotations

from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from wafer.core.lang.manager import t
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.popup import PopupBase

from .tuning import TuningPanel
from .view_settings import VIEW_STAGES, ViewSettings

TUNING_HEIGHT = 600


def set_quietly(button: QtWidgets.QAbstractButton, checked: bool) -> None:
    button.blockSignals(True)
    button.setChecked(checked)
    button.blockSignals(False)


class MapToolbar(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.settings = ViewSettings.instance()
        self.tuning_popup: PopupBase | None = None
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.label_check = QtWidgets.QCheckBox(t("Labels"))
        self.label_check.setToolTip(t("Show group labels."))
        self.label_check.toggled.connect(self.settings.set_labels_shown)
        layout.addWidget(self.label_check)
        self.mode_buttons: dict[str, QtWidgets.QToolButton] = {}
        group = QtWidgets.QButtonGroup(self)
        for mode, text, tip in (("single", t("Single"), t("Select one file at a time.")), ("group", t("Group"), t("Select whole groups."))):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.toggled.connect(partial(self.on_mode_toggled, mode))
            group.addButton(button)
            layout.addWidget(button)
            self.mode_buttons[mode] = button
        self.tuning = TuningPanel(stages=VIEW_STAGES)
        self.tuning.params_changed.connect(self.settings.set_params)
        self.tuning_button = QtWidgets.QToolButton()
        self.tuning_button.setIcon(themed_icon("gear_small"))
        self.tuning_button.setToolTip(t("Display settings"))
        self.tuning_button.clicked.connect(self.toggle_tuning)
        layout.addWidget(self.tuning_button)
        self.settings.changed.connect(self.sync)
        self.sync()

    def on_mode_toggled(self, mode: str, checked: bool) -> None:
        if checked:
            self.settings.set_selection_mode(mode)

    def sync(self, *_) -> None:
        settings = self.settings
        set_quietly(self.label_check, settings.labels_shown)
        for mode, button in self.mode_buttons.items():
            set_quietly(button, mode == settings.selection_mode)
        if self.tuning.params() != settings.params:
            self.tuning.set_params(settings.params)

    def toggle_tuning(self) -> None:
        popup = self.tuning_popup
        if popup is not None and popup.isVisible():
            popup.close()
            return
        if popup is None:
            palette = ThemeManager.instance().palette
            popup = PopupBase(self)
            popup.setStyleSheet(f"PopupBase {{ background: {palette.bg_elevated}; border: 1px solid {palette.border_default}; border-radius: {dpix(6)}px; }}")
            QtWidgets.QVBoxLayout(popup).setContentsMargins(0, 0, 0, 0)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setWidget(self.tuning)
            popup.set_content_widget(scroll)
            self.tuning_popup = popup
        popup.show_below(self.tuning_button, align=Qt.AlignRight, max_height=dpix(TUNING_HEIGHT))

from __future__ import annotations

from dataclasses import replace
from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from wafer.core.lang.manager import t
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.popup import PopupBase

from .params import param_specs
from .tuning import TuningPanel
from .view_settings import TOOLBAR_PARAMS, VIEW_STAGES, ViewSettings

TUNING_HEIGHT = 600
GROUP_SLIDER_WIDTH = 140
GROUP_SPEC = next(spec for name, spec, _ in param_specs() if name == "group_size")
MULTIPLY = "\N{MULTIPLICATION SIGN}"


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
        self.thumbnail_check = QtWidgets.QCheckBox(t("Thumbnails"))
        self.thumbnail_check.setToolTip(t("Show thumbnails instead of dots."))
        self.thumbnail_check.toggled.connect(self.settings.set_thumbnails_shown)
        layout.addWidget(self.thumbnail_check)
        group_label = QtWidgets.QLabel(t(GROUP_SPEC.label))
        group_label.setToolTip(t(GROUP_SPEC.description))
        layout.addWidget(group_label)
        self.group_slider = QtWidgets.QSlider(Qt.Horizontal)
        self.group_slider.setRange(round(GROUP_SPEC.minimum / GROUP_SPEC.step), round(GROUP_SPEC.maximum / GROUP_SPEC.step))
        self.group_slider.setFixedWidth(dpix(GROUP_SLIDER_WIDTH))
        self.group_slider.setToolTip(t(GROUP_SPEC.description))
        self.group_slider.valueChanged.connect(self.on_group_slider)
        layout.addWidget(self.group_slider)
        self.group_value = QtWidgets.QLabel()
        layout.addWidget(self.group_value)
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
        self.tuning = TuningPanel(stages=VIEW_STAGES, exclude=TOOLBAR_PARAMS)
        self.tuning.params_changed.connect(self.settings.set_params)
        self.tuning_button = QtWidgets.QToolButton()
        self.tuning_button.setIcon(themed_icon("gear_small"))
        self.tuning_button.setToolTip(t("Display settings"))
        self.tuning_button.clicked.connect(self.toggle_tuning)
        layout.addWidget(self.tuning_button)
        self.settings.changed.connect(self.sync)
        self.sync()

    def on_group_slider(self, position: int) -> None:
        size = position * GROUP_SPEC.step
        self.group_value.setText(f"{MULTIPLY}{size:.2f}")
        self.settings.set_params(replace(self.settings.params, group_size=size))

    def on_mode_toggled(self, mode: str, checked: bool) -> None:
        if checked:
            self.settings.set_selection_mode(mode)

    def sync(self, *_) -> None:
        settings = self.settings
        set_quietly(self.label_check, settings.labels_shown)
        set_quietly(self.thumbnail_check, settings.thumbnails_shown)
        self.group_slider.blockSignals(True)
        self.group_slider.setValue(round(settings.params.group_size / GROUP_SPEC.step))
        self.group_slider.blockSignals(False)
        self.group_value.setText(f"{MULTIPLY}{settings.params.group_size:.2f}")
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

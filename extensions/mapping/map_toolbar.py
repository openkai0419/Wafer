from __future__ import annotations

import math
from dataclasses import replace
from functools import partial

from PySide6 import QtWidgets
from PySide6.QtCore import Qt

from wafer.core.lang.manager import t
from wafer.qt.common.dpi import dpix
from wafer.qt.common.icon_engine import themed_icon
from wafer.qt.theme import ThemeManager
from wafer.qt.widgets.flow_layout import FlowLayout
from wafer.qt.widgets.popup import PopupBase

from .params import Grouping, TrainParams, ViewParams, param_specs
from .tuning import TuningPanel
from .view_settings import TOOLBAR_PARAMS, GroupingStore, TabSettings, ViewSettings

TUNING_HEIGHT = 600
TOOLBAR_SPACING = 6
SLIDER_WIDTH = 80
STEPS_PER_DOUBLING = 4
SPECS = {name: spec for name, spec, _ in param_specs(ViewParams)}
GROUPING_SPECS = {name: spec for name, spec, _ in param_specs(Grouping)}
SPACING_SPEC = next(spec for name, spec, _ in param_specs(TrainParams) if name == "min_dist")
SPACING_STEPS = round((SPACING_SPEC.maximum - SPACING_SPEC.minimum) / SPACING_SPEC.step)
MULTIPLY = "\N{MULTIPLICATION SIGN}"


def factor_text(value: float) -> str:
    return f"{MULTIPLY}{value:.2g}" if value >= 1 else f"{MULTIPLY}1/{round(1 / value)}"


def slider_position(factor: float) -> int:
    return round(math.log2(factor) * STEPS_PER_DOUBLING)


def slider_factor(position: int) -> float:
    return 2.0 ** (position / STEPS_PER_DOUBLING)


def set_quietly(button: QtWidgets.QAbstractButton, checked: bool) -> None:
    button.blockSignals(True)
    button.setChecked(checked)
    button.blockSignals(False)


class MapToolbar(QtWidgets.QWidget):
    def __init__(self, tab: TabSettings, edits_space_groups: bool = False, parent=None):
        super().__init__(parent)
        self.settings = ViewSettings.instance()
        self.tab = tab
        self.groupings = GroupingStore.instance()
        self.edits_space_groups = edits_space_groups
        self.db_name = ""
        self.tuning_popup: PopupBase | None = None
        layout = FlowLayout(self, spacing=dpix(TOOLBAR_SPACING))
        self.flow = layout
        self.thumbnail_check = QtWidgets.QCheckBox(t("Thumbnails"))
        self.thumbnail_check.setToolTip(t("Show thumbnails instead of dots."))
        self.thumbnail_check.toggled.connect(self.tab.set_thumbnails_shown)
        self.sliders: dict[str, QtWidgets.QSlider] = {}
        self.slider_values: dict[str, QtWidgets.QLabel] = {}
        self.fine_check: QtWidgets.QCheckBox | None = None
        if edits_space_groups:
            for name in ("size", "strictness"):
                self.add_slider(layout, name, GROUPING_SPECS[name], self.set_grouping)
            fine = GROUPING_SPECS["fine"]
            self.fine_check = QtWidgets.QCheckBox(t(fine.label))
            self.fine_check.setToolTip(t(fine.description))
            self.fine_check.toggled.connect(lambda checked: self.set_grouping("fine", int(checked)))
            self.groupings.changed.connect(self.on_grouping_changed)
        else:
            self.add_slider(layout, "subgroup_size", SPECS["subgroup_size"], self.set_param)
            self.add_spacing_slider(layout)
        self.mode_buttons: dict[str, QtWidgets.QToolButton] = {}
        group = QtWidgets.QButtonGroup(self)
        modes = QtWidgets.QWidget()
        pair = QtWidgets.QHBoxLayout(modes)
        pair.setContentsMargins(0, 0, 0, 0)
        pair.setSpacing(dpix(2))
        for mode, text, tip in (("single", t("Single"), t("Select one file at a time.")), ("group", t("Group"), t("Select whole groups."))):
            button = QtWidgets.QToolButton()
            button.setText(text)
            button.setCheckable(True)
            button.setToolTip(tip)
            button.toggled.connect(partial(self.on_mode_toggled, mode))
            group.addButton(button)
            self.mode_buttons[mode] = button
            pair.addWidget(button)
        layout.addWidget(modes)
        self.tuning = TuningPanel(ViewParams, exclude=TOOLBAR_PARAMS)
        self.tuning.params_changed.connect(self.settings.set_params)
        self.popup_content = QtWidgets.QWidget()
        content = QtWidgets.QVBoxLayout(self.popup_content)
        content.setContentsMargins(dpix(10), dpix(8), dpix(10), 0)
        content.addWidget(self.thumbnail_check)
        if self.fine_check is not None:
            content.addWidget(self.fine_check)
        content.addWidget(self.tuning)
        self.popup_content.hide()
        self.tuning_button = QtWidgets.QToolButton()
        self.tuning_button.setIcon(themed_icon("gear_small"))
        self.tuning_button.setToolTip(t("Display settings"))
        self.tuning_button.clicked.connect(self.toggle_tuning)
        layout.addWidget(self.tuning_button)
        self.settings.changed.connect(self.sync)
        self.tab.changed.connect(self.sync)
        self.sync()

    def add_slider(self, layout: FlowLayout, name: str, spec, apply) -> None:
        label = QtWidgets.QLabel(t(spec.label))
        label.setToolTip(t(spec.description))
        slider = QtWidgets.QSlider(Qt.Horizontal)
        slider.setRange(slider_position(spec.minimum), slider_position(spec.maximum))
        slider.setFixedWidth(dpix(SLIDER_WIDTH))
        slider.setToolTip(t(spec.description))
        slider.valueChanged.connect(lambda position: apply(name, slider_factor(position)))
        value = QtWidgets.QLabel()
        value.setFixedWidth(value.fontMetrics().horizontalAdvance(factor_text(2**-10)) + dpix(2))
        for widget in (label, slider, value):
            layout.addWidget(widget)
        self.sliders[name], self.slider_values[name] = slider, value

    def add_spacing_slider(self, layout: FlowLayout) -> None:
        label = QtWidgets.QLabel(t(SPACING_SPEC.label))
        label.setToolTip(t(SPACING_SPEC.description))
        slider = QtWidgets.QSlider(Qt.Horizontal)
        slider.setRange(0, SPACING_STEPS)
        slider.setFixedWidth(dpix(SLIDER_WIDTH))
        slider.setToolTip(t(SPACING_SPEC.description))
        slider.valueChanged.connect(lambda position: self.tab.set_spacing(SPACING_SPEC.minimum + position * SPACING_SPEC.step))
        value = QtWidgets.QLabel()
        value.setFixedWidth(value.fontMetrics().horizontalAdvance("0.00") + dpix(2))
        for widget in (label, slider, value):
            layout.addWidget(widget)
        self.sliders["spacing"], self.slider_values["spacing"] = slider, value

    def prepend(self, widget: QtWidgets.QWidget) -> None:
        self.flow.insertWidget(0, widget)

    def append(self, widget: QtWidgets.QWidget) -> None:
        self.flow.addWidget(widget)

    def set_param(self, name: str, value) -> None:
        self.settings.set_params(replace(self.settings.params, **{name: value}))

    def set_grouping(self, name: str, value) -> None:
        if self.db_name:
            self.groupings.set(self.db_name, replace(self.groupings.get(self.db_name), **{name: value}))

    def set_db(self, db_name: str) -> None:
        if db_name != self.db_name:
            self.db_name = db_name
            self.sync()

    def on_grouping_changed(self, db_name: str) -> None:
        if db_name == self.db_name:
            self.sync()

    def slider_source(self):
        return self.groupings.get(self.db_name) if self.edits_space_groups else self.settings.params

    def on_mode_toggled(self, mode: str, checked: bool) -> None:
        if checked:
            self.tab.set_selection_mode(mode)

    def sync(self, *_) -> None:
        settings = self.settings
        set_quietly(self.thumbnail_check, self.tab.thumbnails_shown)
        source = self.slider_source()
        for name, slider in self.sliders.items():
            if name == "spacing":
                slider.blockSignals(True)
                slider.setValue(round((self.tab.spacing - SPACING_SPEC.minimum) / SPACING_SPEC.step))
                slider.blockSignals(False)
                self.slider_values[name].setText(f"{self.tab.spacing:g}")
                continue
            value = getattr(source, name)
            slider.blockSignals(True)
            slider.setValue(slider_position(value))
            slider.blockSignals(False)
            self.slider_values[name].setText(factor_text(value))
        if self.fine_check is not None:
            set_quietly(self.fine_check, bool(source.fine))
        for mode, button in self.mode_buttons.items():
            set_quietly(button, mode == self.tab.selection_mode)
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
            scroll.setWidget(self.popup_content)
            self.popup_content.show()
            popup.set_content_widget(scroll)
            self.tuning_popup = popup
        popup.show_below(self.tuning_button, align=Qt.AlignRight, max_height=dpix(TUNING_HEIGHT))

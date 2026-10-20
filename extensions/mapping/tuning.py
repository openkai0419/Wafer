from __future__ import annotations

from dataclasses import replace

from PySide6 import QtCore, QtWidgets

from wafer.core.lang.manager import t
from wafer.qt.common.dpi import dpix
from wafer.qt.theme import ThemeManager

from .params import ParamSet, param_specs


class TuningPanel(QtWidgets.QWidget):
    params_changed = QtCore.Signal(object)

    def __init__(self, params_class: type[ParamSet], parent=None):
        super().__init__(parent)
        palette = ThemeManager.instance().palette
        self.params_class = params_class
        self.current = params_class()
        self.syncing = False
        self.controls: dict[str, QtWidgets.QAbstractSpinBox] = {}
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(dpix(10), dpix(8), dpix(10), dpix(8))
        grid = QtWidgets.QGridLayout()
        grid.setVerticalSpacing(dpix(2))
        row = 0
        for name, spec, default in param_specs(params_class):
            label = QtWidgets.QLabel(t(spec.label))
            label.setToolTip(t(spec.description))
            if isinstance(default, int):
                control = QtWidgets.QSpinBox()
                control.setRange(int(spec.minimum), int(spec.maximum))
                control.setSingleStep(int(spec.step))
            else:
                control = QtWidgets.QDoubleSpinBox()
                control.setRange(spec.minimum, spec.maximum)
                control.setSingleStep(spec.step)
                control.setDecimals(2)
            control.setValue(getattr(self.current, name))
            control.setToolTip(t(spec.description))
            control.valueChanged.connect(lambda value, n=name: self.on_value(n, value))
            hint = QtWidgets.QLabel(t(spec.description))
            hint.setWordWrap(True)
            hint.setStyleSheet(f"color: {palette.text_muted}; font-size: {dpix(10)}px;")
            grid.addWidget(label, row, 0)
            grid.addWidget(control, row, 1)
            grid.addWidget(hint, row + 1, 0, 1, 2)
            self.controls[name] = control
            row += 2
        root.addLayout(grid)
        self.reset_button = QtWidgets.QPushButton(t("Reset to defaults"))
        self.reset_button.clicked.connect(self.reset)
        root.addWidget(self.reset_button)

    def params(self) -> ParamSet:
        return self.current

    def set_params(self, params: ParamSet):
        self.current = params
        self.syncing = True
        try:
            for name, control in self.controls.items():
                control.setValue(getattr(params, name))
        finally:
            self.syncing = False

    def on_value(self, name: str, value):
        if self.syncing:
            return
        self.current = replace(self.current, **{name: value})
        self.params_changed.emit(self.current)

    def reset(self):
        self.set_params(self.params_class())
        self.params_changed.emit(self.current)

from __future__ import annotations
from typing import Any
from collections.abc import Callable
from decimal import Decimal
from PySide6 import QtWidgets
from ...lang.manager import TranslatorMixin
from ....utils.logs import AppLogger
from .state import CommandOptionStore


class CommandOptionsDialog(QtWidgets.QDialog, TranslatorMixin):
    def __init__(self, command_class: type, parent=None, execute_callback: Callable[[dict[str, Any]], None] | None = None, binding_mode: bool = False):
        super().__init__(parent)
        self.command_class = command_class
        self.widgets: dict[str, QtWidgets.QWidget] = {}
        store = CommandOptionStore.instance()
        payload = store.get(self.command_class.meta.id)
        self._initial = dict(payload.args or {})
        self._execute_callback = execute_callback
        self._did_save = False
        self._binding_mode = bool(binding_mode)
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(self.t.tr(self.command_class.meta.display) + " " + self.t.tr("Options"))
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        for param in self.command_class.meta.params:
            label = QtWidgets.QLabel(self.t.tr(param.description or param.name))
            widget = self._create_widget(param)
            self.widgets[param.name] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        btn_default = QtWidgets.QPushButton(self.t.tr("Reset"), self)
        btn_default.clicked.connect(self._on_reset_defaults)
        row.addWidget(btn_default)
        row.addStretch(1)
        if self._binding_mode:
            btn_save = QtWidgets.QPushButton(self.t.tr("Apply"), self)
            btn_cancel = QtWidgets.QPushButton(self.t.tr("Cancel"), self)
            btn_save.clicked.connect(self._on_save)
            btn_cancel.clicked.connect(self.reject)
            row.addWidget(btn_save)
            row.addWidget(btn_cancel)
        else:
            btn_execute = QtWidgets.QPushButton(self.t.tr("Execute"), self)
            btn_save = QtWidgets.QPushButton(self.t.tr("Save"), self)
            btn_cancel = QtWidgets.QPushButton(self.t.tr("Cancel"), self)
            btn_execute.clicked.connect(self._on_execute)
            btn_save.clicked.connect(self._on_save)
            btn_cancel.clicked.connect(self.reject)
            row.addWidget(btn_execute)
            row.addWidget(btn_save)
            row.addWidget(btn_cancel)
        layout.addLayout(row)

    def _create_widget(self, param) -> QtWidgets.QWidget:
        resolved_choices = param.resolve_choices()
        if resolved_choices:
            combo = QtWidgets.QComboBox()
            for choice in resolved_choices:
                combo.addItem(str(choice), choice)
            base = self._initial.get(param.name, param.default)
            if base is not None:
                idx = combo.findData(base)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            return combo

        def make_bool():
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(self._initial.get(param.name, param.default)))

            return w

        def make_int():
            w = QtWidgets.QSpinBox()
            base = self._initial.get(param.name, param.default)
            v = int(base or 0)
            if param.min_value is not None:
                w.setMinimum(int(param.min_value))
            else:
                w.setMinimum(int(min(0, v)))
            if param.max_value is not None:
                w.setMaximum(int(param.max_value))
            else:
                w.setMaximum(int(self._infer_int_max(v)))
            w.setValue(v)
            w.setSingleStep(self._infer_int_step(v))
            return w

        def make_float():
            w = QtWidgets.QDoubleSpinBox()
            base = self._initial.get(param.name, param.default)
            v = float(base or 0.0)
            if param.min_value is not None:
                w.setMinimum(float(param.min_value))
            else:
                w.setMinimum(float(min(0.0, v)))
            if param.max_value is not None:
                w.setMaximum(float(param.max_value))
            else:
                w.setMaximum(float(self._infer_float_max(v)))
            w.setValue(v)
            step, decimals = self._infer_float_step(v)
            w.setDecimals(max(2, decimals))
            w.setSingleStep(step)
            return w

        def make_str():
            w = QtWidgets.QLineEdit()
            w.setText(str(self._initial.get(param.name, param.default) or ""))
            return w

        factories = {bool: make_bool, int: make_int, float: make_float}
        f = factories.get(param.type, make_str)
        return f()

    @staticmethod
    def _infer_int_step(v: int) -> int:
        a = abs(int(v))
        if a == 0:
            return 1
        p = 1
        while a % 10 == 0:
            p *= 10
            a //= 10
        return 1 if p <= 1 else max(1, int(p // 2))

    @staticmethod
    def _infer_int_max(v: int) -> int:
        a = abs(int(v))
        if a == 0:
            return 999
        sq = a * a
        digits = len(str(int(sq)))
        return max(999, (10 ** (digits + 1)) - 1)

    @staticmethod
    def _infer_float_step(v: float) -> tuple[float, int]:
        x = float(v)
        if x == 0.0:
            return 1.0, 0
        try:
            d = Decimal(str(round(x, 12))).normalize()
        except Exception:
            return 0.1, 1
        exp = d.as_tuple().exponent
        decimals = max(0, -int(exp))
        if decimals == 0:
            return 0.5, 1
        step = float(Decimal(1).scaleb(-decimals)) / 2.0
        return step, decimals + 1

    @staticmethod
    def _infer_float_max(v: float) -> float:
        a = abs(float(v))
        if a == 0.0:
            return 999.0
        sq = a * a
        digits = len(str(int(sq)))
        return float(max(999, (10 ** (digits + 1)) - 1))

    def get_values(self) -> dict[str, Any]:
        values = {}
        for param in self.command_class.meta.params:
            widget = self.widgets[param.name]
            if isinstance(widget, QtWidgets.QComboBox):
                values[param.name] = widget.currentData()
            elif isinstance(widget, QtWidgets.QCheckBox):
                values[param.name] = widget.isChecked()
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                values[param.name] = widget.value()
            elif isinstance(widget, QtWidgets.QLineEdit):
                text = widget.text()
                if param.type is int:
                    values[param.name] = int(text) if text else param.default
                elif param.type is float:
                    values[param.name] = float(text) if text else param.default
                else:
                    values[param.name] = text
        return values

    def did_save(self) -> bool:
        return bool(self._did_save)

    def _on_execute(self):
        values = self.get_values()
        try:
            if callable(self._execute_callback):
                self._execute_callback(values)
        except Exception as e:
            AppLogger.warning(f"Failed to execute command from dialog: {e}")

    def _on_reset_defaults(self):
        for param in self.command_class.meta.params:
            widget = self.widgets.get(param.name)
            if widget is None:
                continue
            v = param.default
            if isinstance(widget, QtWidgets.QComboBox):
                idx = widget.findData(v)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QtWidgets.QCheckBox):
                widget.setChecked(bool(v))
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                widget.setValue(v if v is not None else 0)
            elif isinstance(widget, QtWidgets.QLineEdit):
                widget.setText(str(v) if v is not None else "")

    def _on_save(self):
        self._did_save = True
        self.accept()

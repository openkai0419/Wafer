from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from wafer.utils.formatting import dpix
from wafer.core.lang.manager import TranslatorMixin
from wafer.plugin.query.widgets import CheckableCombo


class RegexFilterWidget(QtWidgets.QWidget, TranslatorMixin):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def update_translation(self):
        self.regex_input.setPlaceholderText(self.t.tr('Enter regex pattern...'))
        self.case_button.setText(self.t.tr('Aa'))

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))

        self.keys_combo = CheckableCombo()
        self.keys_combo.action_changed.connect(self.changed)

        self.regex_input = QtWidgets.QLineEdit()
        self.regex_input.setPlaceholderText(self.t.tr('Enter regex pattern...'))
        self.regex_input.textChanged.connect(self.changed)

        self.case_button = QtWidgets.QToolButton()
        self.case_button.setText(self.t.tr('Aa'))
        self.case_button.setCheckable(True)
        self.case_button.setFixedSize(dpix(28), dpix(24))
        self.case_button.toggled.connect(lambda: self.changed.emit())

        layout.addWidget(self.keys_combo)
        layout.addWidget(self.case_button)
        layout.addWidget(self.regex_input, 1)

    def read_params(self) -> dict:
        if self.keys_combo.actions:
            keys = self.keys_combo.checked_items()
        else:
            keys = None
        return {
            'keys': keys,
            'pattern': self.regex_input.text(),
            'ignore_case': self.case_button.isChecked(),
        }

    def write_params(self, params: dict):
        if 'pattern' in params:
            self.regex_input.blockSignals(True)
            self.regex_input.setText(params['pattern'])
            self.regex_input.blockSignals(False)
        if 'keys' in params:
            keys = params['keys']
            if isinstance(keys, list):
                self.keys_combo.set_checked(keys)
        if 'ignore_case' in params:
            self.case_button.blockSignals(True)
            self.case_button.setChecked(params['ignore_case'])
            self.case_button.blockSignals(False)

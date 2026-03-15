from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ...utils.formatting import dpix, display_prefixed_key
from ...core.lang.manager import TranslatorMixin


class CheckableCombo(QtWidgets.QToolButton, TranslatorMixin):
    action_changed = QtCore.Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu = QtWidgets.QMenu(self)
        self.actions: list[QtGui.QAction] = []
        self.default_key = '__filepath__'
        self.previous_key = [self.default_key]
        self._update_label()
        if items:
            for name, data in items:
                self.add_item(name, data)
        self.setMenu(self.menu)

    def _update_label(self):
        self.setText(self.t.tr(' Filter '))

    def add_item(self, label, data):
        action = QtGui.QAction(label, self)
        action.setData(data)
        action.setCheckable(True)
        if data in self.previous_key:
            action.setChecked(True)
        action.toggled.connect(self._on_key_changed)
        self.menu.addAction(action)
        self.actions.append(action)

    @QtCore.Slot(list)
    def remake(self, datas):
        self.setUpdatesEnabled(False)
        self.menu.clear()
        self.actions.clear()
        for key, count in datas:
            self.add_item(f'{display_prefixed_key(key)} ({count})', key)
        if not self.checked_items():
            for a in self.actions:
                if a.data() == self.default_key:
                    a.setChecked(True)
                    break
        self.setUpdatesEnabled(True)

    def _on_key_changed(self):
        self.previous_key = self.checked_items()
        self.action_changed.emit()

    def checked_items(self):
        return [a.data() for a in self.actions if a.isChecked()]

    def update_translation(self):
        self._update_label()


class TextFilterWidget(QtWidgets.QWidget, TranslatorMixin):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def update_translation(self):
        self.search_bar.setPlaceholderText(self.t.tr('Enter search terms...'))

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))

        self.keys_combo = CheckableCombo()
        self.keys_combo.action_changed.connect(self.changed)

        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText(self.t.tr('Enter search terms...'))
        self.search_bar.textChanged.connect(self.changed)

        self.option_button = QtWidgets.QPushButton(self.t.tr('\u2699'))
        self.option_button.setFixedWidth(dpix(28))
        self.option_button.clicked.connect(self._toggle_option_popup)

        layout.addWidget(self.keys_combo)
        layout.addWidget(self.search_bar, 1)
        layout.addWidget(self.option_button)

        self._option_popup = _TextFilterPopup(self.option_button, self)
        self._option_popup.changed.connect(self.changed)

    def _toggle_option_popup(self):
        popup = self._option_popup
        if popup.isVisible():
            popup.hide()
        else:
            self._position_popup()
            popup.show()

    def _position_popup(self):
        btn = self.option_button
        pos = btn.mapToGlobal(QtCore.QPoint(0, btn.height()))
        x = pos.x() + btn.width() - self._option_popup.width()
        self._option_popup.move(x, pos.y())

    def read_params(self) -> dict:
        settings = self._option_popup.get_settings()
        if self.keys_combo.actions:
            keys = self.keys_combo.checked_items()
        else:
            keys = None
        return {
            'keys': keys,
            'keywords': self.search_bar.text(),
            'query_mode': settings['query_mode'],
            'keyword_mode': settings['keyword_mode'],
            'keyword_separator': settings['keyword_separator'],
        }

    def write_params(self, params: dict):
        if 'keywords' in params:
            self.search_bar.blockSignals(True)
            self.search_bar.setText(params['keywords'])
            self.search_bar.blockSignals(False)
        if 'keys' in params:
            keys = params['keys']
            if isinstance(keys, list):
                self.keys_combo.previous_key = keys
        self._option_popup.set_settings(params)

    def move_popup(self):
        if self._option_popup.isVisible():
            self._position_popup()


class _TextFilterPopup(QtWidgets.QDialog, TranslatorMixin):
    changed = QtCore.Signal()

    def __init__(self, pos_parent, parent=None):
        super().__init__(parent)
        self.pos_parent = pos_parent
        self.setWindowTitle(self.t.tr('Text Filter Options'))
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self._build_ui()
        self._set_defaults()

    def update_translation(self):
        self.setWindowTitle(self.t.tr('Text Filter Options'))

    def _build_ui(self):
        layout = QtWidgets.QVBoxLayout(self)

        self.query_type_combo = QtWidgets.QComboBox()
        self.query_type_combo.addItem('GLOB', 'GLOB')
        self.query_type_combo.addItem('LIKE', 'LIKE')
        self.query_type_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        layout.addWidget(self.query_type_combo)

        self.keyword_group = QtWidgets.QButtonGroup(self)
        self.and_radio = QtWidgets.QRadioButton('AND')
        self.or_radio = QtWidgets.QRadioButton('OR')
        self.keyword_group.addButton(self.and_radio)
        self.keyword_group.addButton(self.or_radio)
        self.and_radio.toggled.connect(lambda: self.changed.emit())
        self.or_radio.toggled.connect(lambda: self.changed.emit())
        hlayout = QtWidgets.QHBoxLayout()
        hlayout.addWidget(self.and_radio)
        hlayout.addWidget(self.or_radio)
        layout.addLayout(hlayout)

        sep_layout = QtWidgets.QHBoxLayout()
        self.delimiter_input = QtWidgets.QLineEdit()
        self.delimiter_input.textChanged.connect(lambda: self.changed.emit())
        sep_layout.addWidget(QtWidgets.QLabel(self.t.tr('Split by:')))
        sep_layout.addWidget(self.delimiter_input)
        layout.addLayout(sep_layout)

    def _set_defaults(self):
        self.query_type_combo.setCurrentIndex(0)
        self.and_radio.setChecked(True)
        self.delimiter_input.setText(',')

    def get_settings(self) -> dict:
        return {
            'query_mode': self.query_type_combo.currentData(),
            'keyword_mode': 'AND' if self.and_radio.isChecked() else 'OR',
            'keyword_separator': self.delimiter_input.text() or ',',
        }

    def set_settings(self, params: dict):
        if 'query_mode' in params:
            idx = self.query_type_combo.findData(params['query_mode'])
            if idx >= 0:
                self.query_type_combo.blockSignals(True)
                self.query_type_combo.setCurrentIndex(idx)
                self.query_type_combo.blockSignals(False)
        if 'keyword_mode' in params:
            radio = self.and_radio if params['keyword_mode'] == 'AND' else self.or_radio
            radio.blockSignals(True)
            radio.setChecked(True)
            radio.blockSignals(False)
        if 'keyword_separator' in params:
            self.delimiter_input.blockSignals(True)
            self.delimiter_input.setText(params['keyword_separator'])
            self.delimiter_input.blockSignals(False)

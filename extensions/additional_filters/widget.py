from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from wafer.utils.formatting import dpix, display_prefixed_key
from wafer.core.lang.manager import TranslatorMixin
from wafer.core.qt.icon_engine import themed_icon
from wafer.core.color.theme import ThemeManager

from .filter import is_date_key

_TODAY = 'today'
_DATE_FORMAT = 'yyyy/MM/dd'


class _CalendarPopup(QtWidgets.QFrame):

    date_selected = QtCore.Signal(QtCore.QDate)
    today_selected = QtCore.Signal()
    cleared = QtCore.Signal()
    popup_closed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            QtCore.Qt.FramelessWindowHint | QtCore.Qt.Tool)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._calendar = QtWidgets.QCalendarWidget()
        self._calendar.setGridVisible(True)
        self._calendar.setVerticalHeaderFormat(
            QtWidgets.QCalendarWidget.NoVerticalHeader)
        self._calendar.clicked.connect(self._on_calendar_clicked)
        layout.addWidget(self._calendar)

        btn_row = QtWidgets.QHBoxLayout()
        btn_row.setContentsMargins(dpix(4), dpix(2), dpix(4), dpix(4))
        self._today_btn = QtWidgets.QPushButton('Today')
        self._today_btn.clicked.connect(self._on_today)
        self._clear_btn = QtWidgets.QPushButton('Clear')
        self._clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(self._today_btn)
        btn_row.addStretch()
        btn_row.addWidget(self._clear_btn)
        layout.addLayout(btn_row)

    def _on_calendar_clicked(self, date: QtCore.QDate):
        self.date_selected.emit(date)
        self.close()

    def _on_today(self):
        self.today_selected.emit()
        self.close()

    def _on_clear(self):
        self.cleared.emit()
        self.close()

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.close()

    def eventFilter(self, obj, event):
        if event.type() == QtCore.QEvent.WindowDeactivate:
            self.close()
        return super().eventFilter(obj, event)

    def show_at(self, global_pos: QtCore.QPoint,
                current_date: QtCore.QDate | None = None):
        today = QtCore.QDate.currentDate()
        self._calendar.setMaximumDate(today)

        palette = ThemeManager.instance().palette
        self._calendar.setStyleSheet(
            'QCalendarWidget QAbstractItemView::item:selected'
            f'{{ background-color: {palette.accent};'
            f'  color: {palette.accent_text}; }}')

        self._calendar.setDateTextFormat(
            QtCore.QDate(), QtGui.QTextCharFormat())
        today_fmt = QtGui.QTextCharFormat()
        today_fmt.setFontWeight(QtGui.QFont.Bold)
        hl = self.palette().color(QtGui.QPalette.Highlight)
        today_fmt.setForeground(
            self.palette().color(QtGui.QPalette.HighlightedText))
        today_fmt.setBackground(hl.lighter(140))
        self._calendar.setDateTextFormat(today, today_fmt)

        target = (current_date
                  if current_date and current_date.isValid()
                  else today)
        self._calendar.setSelectedDate(target)

        self.move(global_pos)
        self.show()
        self.activateWindow()


class _DateInput(QtWidgets.QWidget):

    value_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._state: str = _TODAY
        self._date: QtCore.QDate | None = None

        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._line = QtWidgets.QLineEdit()
        self._line.setMinimumWidth(dpix(80))
        self._line.editingFinished.connect(self._on_text_edited)
        layout.addWidget(self._line)

        self._drop_btn = QtWidgets.QToolButton()
        self._drop_btn.setIcon(themed_icon('chevron_down'))
        self._drop_btn.setMinimumSize(dpix(20), dpix(22))
        self._drop_btn.setFocusPolicy(QtCore.Qt.NoFocus)
        ThemeManager.instance().on_theme_changed.connect(
            lambda _: self._drop_btn.setIcon(themed_icon('chevron_down')))
        self._drop_btn.released.connect(self._show_popup)
        layout.addWidget(self._drop_btn)

        self._popup: _CalendarPopup | None = None
        self._refresh_display()

    def state(self) -> str:
        return self._state

    def date(self) -> QtCore.QDate | None:
        return self._date

    def set_today(self):
        self._state = _TODAY
        self._date = None
        self._refresh_display()
        self.value_changed.emit()

    def set_date(self, date: QtCore.QDate):
        self._state = 'date'
        self._date = date
        self._refresh_display()
        self.value_changed.emit()

    def set_empty(self):
        self._state = 'empty'
        self._date = None
        self._refresh_display()
        self.value_changed.emit()

    def read_value(self) -> str:
        if self._state == _TODAY:
            return _TODAY
        if self._state == 'date' and self._date is not None:
            return self._date.toString(_DATE_FORMAT)
        return ''

    def write_value(self, val: str):
        if val == _TODAY:
            self._state = _TODAY
            self._date = None
        elif val:
            d = QtCore.QDate.fromString(val, _DATE_FORMAT)
            if d.isValid():
                self._state = 'date'
                self._date = d
            else:
                self._state = 'empty'
                self._date = None
        else:
            self._state = 'empty'
            self._date = None
        self._refresh_display()

    def _refresh_display(self):
        self._line.blockSignals(True)
        if self._state == _TODAY:
            self._line.setText('Today')
        elif self._state == 'date' and self._date is not None:
            self._line.setText(self._date.toString(_DATE_FORMAT))
        else:
            self._line.setText('')
        self._line.blockSignals(False)

    def _on_text_edited(self):
        text = self._line.text().strip()
        if text.lower() == _TODAY:
            self._state = _TODAY
            self._date = None
        elif text:
            d = QtCore.QDate.fromString(text, _DATE_FORMAT)
            if d.isValid():
                self._state = 'date'
                self._date = d
            else:
                self._state = 'empty'
                self._date = None
        else:
            self._state = 'empty'
            self._date = None
        self._refresh_display()
        self.value_changed.emit()

    def _show_popup(self):
        if self._popup is None:
            self._popup = _CalendarPopup(self)
            self._popup.date_selected.connect(self.set_date)
            self._popup.today_selected.connect(self.set_today)
            self._popup.cleared.connect(self.set_empty)
            self._popup.popup_closed.connect(
                lambda: self._drop_btn.setDown(False))
        current = (self._date if self._state == 'date'
                   else QtCore.QDate.currentDate())
        pos = self.mapToGlobal(QtCore.QPoint(0, self.height()))
        self._popup.show_at(pos, current)


class _SectionCombo(QtWidgets.QComboBox):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._section_rows: set[int] = set()

    def rebuild(self, date_keys: list[tuple[str, int]], other_keys: list[tuple[str, int]]):
        prev = self.currentData()
        self.blockSignals(True)
        self.clear()
        self._section_rows.clear()

        if date_keys:
            self._add_section_header('Date keys')
            for key, freq in date_keys:
                self.addItem(f'{display_prefixed_key(key)} ({freq})', key)
        if other_keys:
            self._add_section_header('All keys')
            for key, freq in other_keys:
                self.addItem(f'{display_prefixed_key(key)} ({freq})', key)

        idx = self.findData(prev)
        if idx < 0:
            idx = self.findData('modified')
        if idx < 0:
            for i in range(self.count()):
                if i not in self._section_rows:
                    idx = i
                    break
        if idx >= 0:
            self.setCurrentIndex(idx)

        self.blockSignals(False)

    def _add_section_header(self, label: str):
        idx = self.count()
        self.addItem(f'── {label} ──')
        self._section_rows.add(idx)
        item = self.model().item(idx)
        item.setEnabled(False)
        item.setData('__section__', QtCore.Qt.UserRole)
        font = item.font()
        font.setItalic(True)
        item.setFont(font)


class DateRangeWidget(QtWidgets.QWidget, TranslatorMixin):
    changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def update_translation(self):
        pass

    def _build_ui(self):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))

        self.target_combo = _SectionCombo()
        self.target_combo.setMinimumWidth(dpix(80))
        self.target_combo.currentIndexChanged.connect(lambda: self.changed.emit())

        self.mode_combo = QtWidgets.QComboBox()
        self.mode_combo.addItem('Last', 'preset')
        self.mode_combo.addItem('Between', 'range')
        self.mode_combo.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)

        self.preset_value = QtWidgets.QSpinBox()
        self.preset_value.setRange(1, 999)
        self.preset_value.setValue(7)
        self.preset_value.setMinimumWidth(dpix(48))
        self.preset_value.valueChanged.connect(lambda: self.changed.emit())

        self.preset_unit = QtWidgets.QComboBox()
        for label, data in [('hours', 'hours'), ('days', 'days'), ('weeks', 'weeks'),
                            ('months', 'months'), ('years', 'years')]:
            self.preset_unit.addItem(label, data)
        self.preset_unit.setCurrentIndex(1)
        self.preset_unit.setSizeAdjustPolicy(
            QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.preset_unit.currentIndexChanged.connect(lambda: self.changed.emit())

        self.preset_from_label = QtWidgets.QLabel('from')
        self.preset_ref = _DateInput()
        self.preset_ref.set_today()
        self.preset_ref.value_changed.connect(self.changed)

        self.date_from = _DateInput()
        self.date_from.set_today()
        self.date_from.value_changed.connect(self.changed)

        self.range_sep = QtWidgets.QLabel('to')

        self.date_to = _DateInput()
        self.date_to.set_empty()
        self.date_to.value_changed.connect(self.changed)

        layout.addWidget(self.target_combo, 1)
        layout.addWidget(self.mode_combo)

        self._preset_widgets = [self.preset_value, self.preset_unit,
                                self.preset_from_label, self.preset_ref]
        for w in self._preset_widgets:
            layout.addWidget(w)

        self._range_widgets = [self.date_from, self.range_sep, self.date_to]
        for w in self._range_widgets:
            layout.addWidget(w)

        self._on_mode_changed()

    def _on_mode_changed(self):
        is_preset = self.mode_combo.currentData() == 'preset'
        for w in self._preset_widgets:
            w.setVisible(is_preset)
        for w in self._range_widgets:
            w.setVisible(not is_preset)
        self.changed.emit()

    def _on_key_store_updated(self, data: list[tuple[str, int]]):
        date_keys = [(k, f) for k, f in data if is_date_key(k)]
        other_keys = [(k, f) for k, f in data if not is_date_key(k)]
        self.target_combo.rebuild(date_keys, other_keys)

    def read_params(self) -> dict:
        target_key = self.target_combo.currentData()
        if target_key is None or target_key == '__section__':
            target_key = 'modified'
        mode = self.mode_combo.currentData() or 'preset'
        params: dict = {'target_key': target_key, 'mode': mode}
        if mode == 'preset':
            params['preset_value'] = self.preset_value.value()
            params['preset_unit'] = self.preset_unit.currentData() or 'days'
            params['preset_ref'] = self.preset_ref.read_value()
        else:
            params['range_from'] = self.date_from.read_value()
            params['range_to'] = self.date_to.read_value()
        return params

    def write_params(self, params: dict):
        self.blockSignals(True)
        try:
            if 'target_key' in params:
                idx = self.target_combo.findData(params['target_key'])
                if idx >= 0:
                    self.target_combo.setCurrentIndex(idx)

            if 'mode' in params:
                idx = self.mode_combo.findData(params['mode'])
                if idx >= 0:
                    self.mode_combo.blockSignals(True)
                    self.mode_combo.setCurrentIndex(idx)
                    self.mode_combo.blockSignals(False)
                    self._on_mode_changed()

            if 'preset_value' in params:
                self.preset_value.blockSignals(True)
                self.preset_value.setValue(int(params['preset_value']))
                self.preset_value.blockSignals(False)

            if 'preset_unit' in params:
                idx = self.preset_unit.findData(params['preset_unit'])
                if idx >= 0:
                    self.preset_unit.blockSignals(True)
                    self.preset_unit.setCurrentIndex(idx)
                    self.preset_unit.blockSignals(False)

            if 'preset_ref' in params:
                self.preset_ref.write_value(params['preset_ref'])

            if 'range_from' in params:
                self.date_from.write_value(params['range_from'])

            if 'range_to' in params:
                self.date_to.write_value(params['range_to'])
        finally:
            self.blockSignals(False)

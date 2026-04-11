from __future__ import annotations

import pytest

from PySide6 import QtCore, QtGui

from extensions.additional_filters.widget import (
    DateRangeWidget,
    _SectionCombo,
    _DateInput,
    _CalendarPopup,
)
from extensions.additional_filters.filter import is_date_key


class TestSectionCombo:
    def test_rebuild_sections(self, qtbot):
        combo = _SectionCombo()
        qtbot.addWidget(combo)
        date_keys = [("modified", 100), ("created", 80)]
        other_keys = [("size", 100), ("name", 100)]
        combo.rebuild(date_keys, other_keys)
        assert combo.count() == 6
        assert combo.currentData() == "modified"

    def test_rebuild_preserves_selection(self, qtbot):
        combo = _SectionCombo()
        qtbot.addWidget(combo)
        combo.rebuild([("modified", 10), ("created", 5)], [("size", 10)])
        idx = combo.findData("created")
        combo.setCurrentIndex(idx)
        combo.rebuild([("modified", 10), ("created", 5)], [("size", 10)])
        assert combo.currentData() == "created"

    def test_rebuild_empty(self, qtbot):
        combo = _SectionCombo()
        qtbot.addWidget(combo)
        combo.rebuild([], [])
        assert combo.count() == 0

    def test_section_header_disabled(self, qtbot):
        combo = _SectionCombo()
        qtbot.addWidget(combo)
        combo.rebuild([("modified", 10)], [("size", 10)])
        model = combo.model()
        assert not model.item(0).isEnabled()
        assert model.item(1).isEnabled()
        assert not model.item(2).isEnabled()
        assert model.item(3).isEnabled()


class TestDateInput:
    def test_default_state_today(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_today()
        assert di.state() == "today"
        assert di.read_value() == "today"

    def test_set_date(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_date(QtCore.QDate(2024, 6, 15))
        assert di.state() == "date"
        assert di.read_value() == "2024/06/15"

    def test_set_empty(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_empty()
        assert di.state() == "empty"
        assert di.read_value() == ""

    def test_write_today(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.write_value("today")
        assert di.state() == "today"

    def test_write_date(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.write_value("2024/03/01")
        assert di.state() == "date"
        assert di.date() == QtCore.QDate(2024, 3, 1)

    def test_write_empty(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.write_value("")
        assert di.state() == "empty"

    def test_write_invalid(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.write_value("not-a-date")
        assert di.state() == "empty"

    def test_value_changed_signal(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        signals = []
        di.value_changed.connect(lambda: signals.append(True))
        di.set_date(QtCore.QDate(2024, 1, 1))
        di.set_today()
        di.set_empty()
        assert len(signals) == 3

    def test_display_text_today(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_today()
        assert di._line.text() == "Today"

    def test_display_text_date(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_date(QtCore.QDate(2024, 12, 25))
        assert di._line.text() == "2024/12/25"

    def test_display_text_empty(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di.set_empty()
        assert di._line.text() == ""

    def test_popup_resets_button_down(self, qtbot):
        di = _DateInput()
        qtbot.addWidget(di)
        di._drop_btn.setDown(True)
        di._show_popup()
        assert di._popup is not None
        di._popup.close()
        assert not di._drop_btn.isDown()


class TestCalendarPopup:
    def test_window_flags(self, qtbot):
        popup = _CalendarPopup()
        qtbot.addWidget(popup)
        flags = popup.windowFlags()
        assert flags & QtCore.Qt.FramelessWindowHint
        assert flags & QtCore.Qt.Tool

    def test_close_on_escape(self, qtbot):
        popup = _CalendarPopup()
        qtbot.addWidget(popup)
        popup.show()
        assert popup.isVisible()
        event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
        popup.keyPressEvent(event)
        assert not popup.isVisible()

    def test_popup_closed_signal_on_close(self, qtbot):
        popup = _CalendarPopup()
        qtbot.addWidget(popup)
        popup.show()
        closed = []
        popup.popup_closed.connect(lambda: closed.append(True))
        popup.close()
        assert closed

    def test_close_on_leave(self, qtbot):
        popup = _CalendarPopup()
        qtbot.addWidget(popup)
        popup.show()
        assert popup.isVisible()
        popup.leaveEvent(QtCore.QEvent(QtCore.QEvent.Leave))
        assert not popup.isVisible()


class TestDateRangeWidget:
    def test_read_params_preset_default(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        params = w.read_params()
        assert params["target_key"] == "modified"
        assert params["mode"] == "preset"
        assert params["preset_value"] == 7
        assert params["preset_unit"] == "days"
        assert params["preset_ref"] == "today"

    def test_read_params_preset_with_date_ref(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.preset_ref.set_date(QtCore.QDate(2024, 6, 1))
        params = w.read_params()
        assert params["preset_ref"] == "2024/06/01"

    def test_read_params_range_mode(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.mode_combo.setCurrentIndex(1)
        w.date_from.set_date(QtCore.QDate(2024, 1, 15))
        w.date_to.set_date(QtCore.QDate(2024, 6, 30))
        params = w.read_params()
        assert params["mode"] == "range"
        assert params["range_from"] == "2024/01/15"
        assert params["range_to"] == "2024/06/30"

    def test_read_params_range_today(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.mode_combo.setCurrentIndex(1)
        w.date_from.set_today()
        w.date_to.set_empty()
        params = w.read_params()
        assert params["range_from"] == "today"
        assert params["range_to"] == ""

    def test_read_params_range_cleared(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.mode_combo.setCurrentIndex(1)
        w.date_from.set_empty()
        w.date_to.set_empty()
        params = w.read_params()
        assert params["range_from"] == ""
        assert params["range_to"] == ""

    def test_write_params_preset(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10), ("created", 5)], [])
        w.write_params(
            {
                "target_key": "created",
                "mode": "preset",
                "preset_value": 30,
                "preset_unit": "hours",
                "preset_ref": "today",
            }
        )
        params = w.read_params()
        assert params["target_key"] == "created"
        assert params["mode"] == "preset"
        assert params["preset_value"] == 30
        assert params["preset_unit"] == "hours"
        assert params["preset_ref"] == "today"

    def test_write_params_preset_date_ref(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.write_params(
            {
                "mode": "preset",
                "preset_value": 14,
                "preset_unit": "days",
                "preset_ref": "2024/06/01",
            }
        )
        params = w.read_params()
        assert params["preset_ref"] == "2024/06/01"

    def test_write_params_range(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.write_params(
            {
                "target_key": "modified",
                "mode": "range",
                "range_from": "2024/03/01",
                "range_to": "2024/09/30",
            }
        )
        params = w.read_params()
        assert params["mode"] == "range"
        assert params["range_from"] == "2024/03/01"
        assert params["range_to"] == "2024/09/30"

    def test_write_params_range_today(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.write_params({"mode": "range", "range_from": "today", "range_to": ""})
        params = w.read_params()
        assert params["range_from"] == "today"
        assert params["range_to"] == ""

    def test_write_params_range_empty(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.target_combo.rebuild([("modified", 10)], [])
        w.write_params({"mode": "range", "range_from": "", "range_to": ""})
        params = w.read_params()
        assert params["range_from"] == ""
        assert params["range_to"] == ""

    def test_on_key_store_updated(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        data = [
            ("modified", 100),
            ("created", 80),
            ("collected", 50),
            ("exiftool.DateTimeOriginal", 60),
            ("size", 100),
            ("name", 100),
            ("exiftool.LensMake", 40),
        ]
        w._on_key_store_updated(data)
        all_items = []
        for i in range(w.target_combo.count()):
            d = w.target_combo.itemData(i)
            if d != "__section__":
                all_items.append(d)
        date_items = [d for d in all_items if d and is_date_key(d)]
        assert len(date_items) >= 4

    def test_changed_signal_on_mode_switch(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        signals = []
        w.changed.connect(lambda: signals.append(True))
        w.mode_combo.setCurrentIndex(1)
        assert len(signals) >= 1

    def test_preset_widgets_visible_in_preset_mode(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.mode_combo.setCurrentIndex(0)
        assert not w.preset_value.isHidden()
        assert not w.preset_unit.isHidden()
        assert not w.preset_from_label.isHidden()
        assert not w.preset_ref.isHidden()
        assert w.date_from.isHidden()
        assert w.date_to.isHidden()

    def test_range_widgets_visible_in_range_mode(self, qtbot):
        w = DateRangeWidget()
        qtbot.addWidget(w)
        w.mode_combo.setCurrentIndex(1)
        assert w.preset_value.isHidden()
        assert w.preset_unit.isHidden()
        assert not w.date_from.isHidden()
        assert not w.date_to.isHidden()
        assert not w.range_sep.isHidden()

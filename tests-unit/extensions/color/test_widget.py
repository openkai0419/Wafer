from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from PySide6 import QtCore, QtGui, QtWidgets
import pytest

from extensions.color import widget as color_widget_module
from extensions.color.widget import ColorFilterWidget
from wafer.qt.commands.binding.instance_registry import InstanceRegistry


@pytest.fixture()
def color_widget(qapp):
    return ColorFilterWidget()


class _FakeAppSettingsHolder(QtCore.QObject):
    changed = QtCore.Signal()

    def __init__(self, slots: int):
        super().__init__()
        self._palette_slots = slots
        self.save_palette_slots = MagicMock(side_effect=self.set_palette_slots)

    def palette_slots(self) -> int:
        return self._palette_slots

    def set_palette_slots(self, value: int) -> int:
        self._palette_slots = int(value)
        self.changed.emit()
        return self._palette_slots


def test_color_widget_preserves_last_tolerance_for_new_colors(color_widget):
    color_widget._rows[0]._tolerance.setValue(23.0)
    color_widget.add_color("#00ff00")
    params = color_widget.read_params()
    assert params["colors"][1]["tolerance"] == pytest.approx(0.23)


def test_color_widget_row_height_is_stable(color_widget):
    row = color_widget._rows[0]
    height = row.sizeHint().height()
    assert row.minimumHeight() == row.maximumHeight()
    assert "solid transparent" in row.styleSheet()

    row.set_selected(True)
    assert "solid transparent" not in row.styleSheet()
    assert row.sizeHint().height() == height

    row.setEnabled(False)
    assert row.sizeHint().height() == height


def test_color_widget_drag_handle_reorders_colors(color_widget):
    color_widget.add_color("#111111")
    color_widget.add_color("#222222")

    last = color_widget._rows[-1]
    color_widget._reorder_row_at(last, color_widget._row_box.mapToGlobal(QtCore.QPoint(-100, 0)))
    assert [color["hex"] for color in color_widget.read_params()["colors"]] == ["#222222", "#808080", "#111111"]

    first = color_widget._rows[0]
    color_widget._reorder_row_at(first, color_widget._row_box.mapToGlobal(QtCore.QPoint(10000, 0)))
    assert [color["hex"] for color in color_widget.read_params()["colors"]] == ["#808080", "#111111", "#222222"]


def test_color_widget_replaces_only_selected_color(color_widget):
    color_widget.add_color("#00ff00", 0.2)
    color_widget._select_row(color_widget._rows[1])
    assert color_widget.replace_selected_color("#112233") is True
    colors = color_widget.read_params()["colors"]
    assert colors[0]["hex"] == "#808080"
    assert colors[1]["hex"] == "#112233"
    assert colors[1]["tolerance"] == pytest.approx(0.2)


def test_color_widget_selection_toggles_and_keeps_latest_only(color_widget):
    color_widget.add_color("#00ff00", 0.2)
    first = color_widget._rows[0]
    second = color_widget._rows[1]

    color_widget._select_row(first)
    assert color_widget.has_selection() is True

    color_widget._select_row(first)
    assert color_widget.has_selection() is False

    color_widget._select_row(first)
    color_widget._select_row(second)
    assert first._selected is False
    assert second._selected is True
    assert color_widget._selected_row is second


def test_color_widget_clears_selection_on_peer_widgets(qapp):
    first = ColorFilterWidget()
    second = ColorFilterWidget()
    container = SimpleNamespace(param_widgets=MagicMock(return_value=[first, second]))
    registry = InstanceRegistry.instance()
    original_get_one = registry.get_one
    registry.get_one = lambda name: container if name == "SearchContainer" else original_get_one(name)

    try:
        first._select_row(first._rows[0])
        assert first.has_selection() is True

        second._select_row(second._rows[0])

        assert first.has_selection() is False
        assert second.has_selection() is True
    finally:
        registry.get_one = original_get_one


def test_color_widget_swatch_click_selects_row_and_changes_color(color_widget):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("extensions.color.widget.ColorPickerDialog.get_color", lambda *args, **kwargs: QtGui.QColor("#224466"))
        color_widget._rows[0]._on_swatch_clicked()
    params = color_widget.read_params()
    assert color_widget.has_selection() is True
    assert "QFrame#colorSearchRow" in color_widget._rows[0].styleSheet()
    assert params["colors"][0]["hex"] == "#224466"


def test_color_widget_write_params_roundtrip(color_widget):
    color_widget.write_params({"mode": "AND", "colors": [{"hex": "#ff0000", "tolerance": 0.1}]})
    params = color_widget.read_params()
    assert params["mode"] == "AND"
    assert params["colors"] == [{"hex": "#FF0000", "tolerance": pytest.approx(0.1), "enabled": True}]


def test_color_settings_popup_save_notifies_and_deletes_recollects(qapp, monkeypatch):
    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def delete_data(self):
            return True

        def recollect(self):
            return True

    fake_settings = _FakeAppSettingsHolder(6)
    monkeypatch.setattr(color_widget_module.ColorSettings, "instance", staticmethod(lambda: fake_settings))

    popup = color_widget_module._ColorSettingsPopup()
    popup._slots_spin.setValue(8)
    send_delete = MagicMock()
    monkeypatch.setattr(color_widget_module, "FilterSaveConfirmDialog", AcceptedDialog)
    monkeypatch.setattr(color_widget_module, "list_setting_db_names", lambda: ["db1", "db2"])
    monkeypatch.setattr(color_widget_module._ColorSettingsPopup, "_send_delete_and_recollect", send_delete)
    monkeypatch.setattr(color_widget_module.Notifier, "info", MagicMock())

    popup._on_save()

    fake_settings.save_palette_slots.assert_called_once_with(8)
    send_delete.assert_called_once_with(["db1", "db2"], delete=True, re_collect=True)


def test_color_settings_popup_save_without_delete_only_notifies(qapp, monkeypatch):
    class AcceptedDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QtWidgets.QDialog.Accepted

        def delete_data(self):
            return False

        def recollect(self):
            return False

    fake_settings = _FakeAppSettingsHolder(6)
    monkeypatch.setattr(color_widget_module.ColorSettings, "instance", staticmethod(lambda: fake_settings))

    popup = color_widget_module._ColorSettingsPopup()
    popup._slots_spin.setValue(7)
    send_delete = MagicMock()
    monkeypatch.setattr(color_widget_module, "FilterSaveConfirmDialog", AcceptedDialog)
    monkeypatch.setattr(color_widget_module._ColorSettingsPopup, "_send_delete_and_recollect", send_delete)
    monkeypatch.setattr(color_widget_module.Notifier, "info", MagicMock())

    popup._on_save()

    fake_settings.save_palette_slots.assert_called_once_with(7)
    send_delete.assert_not_called()


def test_color_settings_popup_syncs_shared_palette_slots(qapp, monkeypatch):
    fake_settings = _FakeAppSettingsHolder(6)
    monkeypatch.setattr(color_widget_module.ColorSettings, "instance", staticmethod(lambda: fake_settings))

    first = color_widget_module._ColorSettingsPopup()
    second = color_widget_module._ColorSettingsPopup()
    first._slots_spin.setValue(10)
    first._on_revert()
    assert first._slots_spin.value() == 6

    fake_settings.set_palette_slots(11)
    assert first._slots_spin.value() == 11
    assert second._slots_spin.value() == 11

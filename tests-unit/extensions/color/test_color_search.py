from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image
from PySide6 import QtCore, QtGui, QtWidgets
import pytest

from extensions.color import widget as color_widget_module
from extensions.color._color import hex_to_packed, normalize_tolerance, packed_to_hex, palette_tags, rgb_to_packed
from extensions.color.commands import apply_color_filter, apply_selected_color
from extensions.color.collector import ColorCollector, extract_palette
from extensions.color.filter import ColorFilter
from extensions.color.panel import _ColorButton
from extensions.color.settings import APP_SETTINGS_KEY, ColorSettings, palette_keys
from extensions.color.widget import ColorFilterWidget, _DEFAULT_TOLERANCE
from wafer.core.commands.binding.instance_registry import InstanceRegistry


@pytest.fixture()
def color_widget(qapp):
    return ColorFilterWidget()


class _FakeAppSettings(QtCore.QObject):
    key_changed = QtCore.Signal(str)

    def __init__(self, initial=None):
        super().__init__()
        self.values = dict(initial or {})
        self.commits = 0

    def get(self, key, default=None, value_type=None):
        return self.values.get(key, default)

    def set(self, key, value):
        self.values[key] = value

    def commit(self):
        self.commits += 1


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


def test_palette_tags_always_writes_all_palette_slots():
    keys = palette_keys(6)
    tags = palette_tags([rgb_to_packed(255, 0, 0), rgb_to_packed(0, 255, 0)], slots=6)
    assert tuple(tags.keys()) == keys
    assert tags["palette.1"] == "16711680"
    assert tags["palette.2"] == "65280"
    for key in keys[2:]:
        assert tags[key] == ""


def test_palette_tags_uses_requested_slot_count():
    tags = palette_tags([rgb_to_packed(255, 0, 0), rgb_to_packed(0, 255, 0), rgb_to_packed(0, 0, 255)], slots=2)
    assert tuple(tags.keys()) == ("palette.1", "palette.2")
    assert tags == {"palette.1": "16711680", "palette.2": "65280"}


def test_packed_hex_roundtrip():
    packed = hex_to_packed("#CC4422")
    assert packed == 0xCC4422
    assert packed_to_hex(packed) == "#CC4422"


def test_tolerance_uses_ratio_with_legacy_percent_migration():
    assert normalize_tolerance(0.1) == pytest.approx(0.1)
    assert normalize_tolerance(1) == pytest.approx(1.0)
    assert normalize_tolerance(10) == pytest.approx(0.1)


def test_extract_palette_from_simple_image():
    image = Image.new("RGB", (20, 10), "red")
    colors = extract_palette(image)
    assert colors
    assert colors[0] == rgb_to_packed(255, 0, 0)


def test_color_filter_sql_matches_tolerance():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT, value_num REAL);
            CREATE TABLE sources (source TEXT, file_hash TEXT);
            CREATE TABLE files (path TEXT, source TEXT);
            """
        )
        rows = [
            ("red.jpg", "h1", rgb_to_packed(255, 0, 0)),
            ("mixed.jpg", "h2", rgb_to_packed(230, 20, 20)),
            ("blue.jpg", "h3", rgb_to_packed(0, 0, 255)),
        ]
        for path, file_hash, packed in rows:
            conn.execute("INSERT INTO sources VALUES (?, ?)", (path, file_hash))
            conn.execute("INSERT INTO files VALUES (?, ?)", (path, path))
            conn.execute("INSERT INTO tags VALUES (?, ?, ?, ?)", (file_hash, "color.palette.1", str(packed), packed))
        sql, params = ColorFilter.build_path_query({"colors": [{"hex": "#ff0000", "tolerance": 0.1}], "mode": "OR"}, lambda p: p)
        result = {row[0] for row in conn.execute(sql, params).fetchall()}
        assert result == {"red.jpg", "mixed.jpg"}
    finally:
        conn.close()


def test_color_filter_and_mode_requires_both_colors():
    conn = sqlite3.connect(":memory:")
    try:
        conn.executescript(
            """
            CREATE TABLE tags (file_hash TEXT, key TEXT, value TEXT, value_num REAL);
            CREATE TABLE sources (source TEXT, file_hash TEXT);
            CREATE TABLE files (path TEXT, source TEXT);
            """
        )
        conn.execute("INSERT INTO sources VALUES ('both.jpg', 'h1')")
        conn.execute("INSERT INTO files VALUES ('both.jpg', 'both.jpg')")
        conn.execute("INSERT INTO tags VALUES ('h1', 'color.palette.1', ?, ?)", (str(rgb_to_packed(255, 0, 0)), rgb_to_packed(255, 0, 0)))
        conn.execute("INSERT INTO tags VALUES ('h1', 'color.palette.2', ?, ?)", (str(rgb_to_packed(0, 0, 255)), rgb_to_packed(0, 0, 255)))
        conn.execute("INSERT INTO sources VALUES ('red.jpg', 'h2')")
        conn.execute("INSERT INTO files VALUES ('red.jpg', 'red.jpg')")
        conn.execute("INSERT INTO tags VALUES ('h2', 'color.palette.1', ?, ?)", (str(rgb_to_packed(255, 0, 0)), rgb_to_packed(255, 0, 0)))
        sql, params = ColorFilter.build_path_query(
            {"colors": [{"hex": "#ff0000", "tolerance": 0.01}, {"hex": "#0000ff", "tolerance": 0.01}], "mode": "AND"},
            lambda p: p,
        )
        result = {row[0] for row in conn.execute(sql, params).fetchall()}
        assert result == {"both.jpg"}
    finally:
        conn.close()


def test_color_filter_uses_dynamic_palette_keys(monkeypatch):
    monkeypatch.setattr("extensions.color.filter.palette_keys", lambda: ("palette.1", "palette.2", "palette.3"))
    sql, params = ColorFilter.build_path_query({"colors": [{"hex": "#ff0000", "tolerance": 0.1}], "mode": "OR"}, lambda p: p)
    assert "?,?,?" in sql
    assert params[:3] == ["color.palette.1", "color.palette.2", "color.palette.3"]


def test_color_settings_save_updates_app_settings_and_notifies_collector(qapp, monkeypatch):
    fake_app = _FakeAppSettings({APP_SETTINGS_KEY: 6})
    save_and_notify = MagicMock()
    monkeypatch.setattr(ColorSettings, "_instance", None)
    monkeypatch.setattr(ColorSettings, "_app_settings", staticmethod(lambda: fake_app))
    monkeypatch.setattr("extensions.color.settings.color_config.save_and_notify", save_and_notify)

    settings = ColorSettings.instance()
    changed = MagicMock()
    settings.changed.connect(changed)

    assert settings.save_palette_slots(8) == 8
    assert settings.palette_slots() == 8
    assert fake_app.values[APP_SETTINGS_KEY] == 8
    assert fake_app.commits == 1
    save_and_notify.assert_called_once_with("color", palette_slots=8)
    changed.assert_called_once()


def test_color_settings_reloads_on_remote_app_settings_change(qapp, monkeypatch):
    fake_app = _FakeAppSettings({APP_SETTINGS_KEY: 6})
    monkeypatch.setattr(ColorSettings, "_instance", None)
    monkeypatch.setattr(ColorSettings, "_app_settings", staticmethod(lambda: fake_app))

    settings = ColorSettings.instance()
    changed = MagicMock()
    settings.changed.connect(changed)
    fake_app.values[APP_SETTINGS_KEY] = 9
    fake_app.key_changed.emit(APP_SETTINGS_KEY)

    assert settings.palette_slots() == 9
    changed.assert_called_once()


def test_color_collector_reloads_settings_and_uses_palette_slots(monkeypatch):
    image = Image.new("RGB", (4, 4), "red")
    collector = ColorCollector()
    collector._settings = {"palette_slots": 3}
    calls = {}

    monkeypatch.setattr("extensions.color.collector.image_loader_resolver.load_pil", lambda path, size: image)

    def fake_extract_palette(img, max_colors, sample_size=256):
        calls["max_colors"] = max_colors
        return [rgb_to_packed(255, 0, 0)] * max_colors

    monkeypatch.setattr("extensions.color.collector.extract_palette", fake_extract_palette)
    result = collector.process("sample.jpg", ())
    assert calls["max_colors"] == 3
    assert tuple(result.tags.keys()) == ("palette.1", "palette.2", "palette.3")

    monkeypatch.setattr("extensions.color.collector.color_config.load", lambda: {"palette_slots": 4})
    collector.on_notify({"palette_slots": 4})
    assert collector._settings == {"palette_slots": 4}


def test_color_widget_defaults_to_ratio_tolerance(color_widget):
    params = color_widget.read_params()
    assert params["colors"][0]["tolerance"] == pytest.approx(_DEFAULT_TOLERANCE)
    assert color_widget._rows[0]._tolerance.value() == pytest.approx(_DEFAULT_TOLERANCE * 100.0)


def test_color_widget_preserves_last_tolerance_for_new_colors(color_widget):
    color_widget._rows[0]._tolerance.setValue(23.0)
    color_widget.add_color("#00ff00")
    params = color_widget.read_params()
    assert params["colors"][1]["tolerance"] == pytest.approx(0.23)


def test_color_widget_tolerance_displays_percent(color_widget):
    row = color_widget._rows[0]
    assert row._tolerance.decimals() == 1
    assert row._tolerance.singleStep() == pytest.approx(1.0)
    assert row._tolerance.suffix() == "%"
    assert row._tolerance.maximum() == pytest.approx(100.0)


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


def test_color_widget_write_params_migrates_legacy_percent(color_widget):
    color_widget.write_params({"mode": "AND", "colors": [{"hex": "#ff0000", "tolerance": 10}]})
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


def test_apply_color_filter_appends_ratio_tolerance():
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[]), apply_bars=MagicMock())
    apply_color_filter(search, hex_color="#ff0000", tolerance=1.0, mode="append_and", join="AND")
    bars = search.apply_bars.call_args.args[0]
    assert search.apply_bars.call_args.kwargs["mode"] == "append"
    assert "op" not in bars[0]
    assert bars[0]["params"]["mode"] == "OR"
    assert bars[0]["params"]["colors"][0]["tolerance"] == pytest.approx(1.0)


def test_apply_selected_color_noops_without_selection():
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[]))
    apply_selected_color(search, hex_color="#ff0000")


def test_apply_selected_color_updates_selected_widget():
    widget = SimpleNamespace(has_selection=MagicMock(return_value=True), replace_selected_color=MagicMock(return_value=True))
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[widget]))
    apply_selected_color(search, hex_color="#ff0000")
    widget.replace_selected_color.assert_called_once_with("#FF0000")


def test_apply_color_filter_appends_to_last_color_widget(qapp):
    first = ColorFilterWidget()
    last = ColorFilterWidget()
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[first, last]), apply_bars=MagicMock())

    apply_color_filter(search, hex_color="#112233", tolerance=0.25)

    colors = last.read_params()["colors"]
    assert colors[-1]["hex"] == "#112233".upper()
    assert colors[-1]["tolerance"] == pytest.approx(0.25)
    search.apply_bars.assert_not_called()


def test_apply_color_filter_ignores_existing_duplicate_color(qapp):
    color_widget = ColorFilterWidget()
    color_widget.add_color("#112233", 0.25)
    before = color_widget.read_params()["colors"]
    search = SimpleNamespace(param_widgets=MagicMock(return_value=[color_widget]), apply_bars=MagicMock())

    apply_color_filter(search, hex_color="#112233", tolerance=0.5)

    after = color_widget.read_params()["colors"]
    assert after == before
    search.apply_bars.assert_not_called()


def test_color_panel_context_menu_includes_apply_selected(qapp):
    button = _ColorButton("#224466")
    items = button._menu_items()
    actions = [item for item in items if hasattr(item, "display")]
    assert [action.display for action in actions] == ["Override selected color", "Add to color filter"]

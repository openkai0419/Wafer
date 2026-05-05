from __future__ import annotations

import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image
from PySide6 import QtCore, QtGui
import pytest

from extensions.color_search._color import PALETTE_KEYS, hex_to_packed, normalize_tolerance, packed_to_hex, palette_tags, rgb_to_packed
from extensions.color_search.commands import apply_color_filter, apply_selected_color
from extensions.color_search.collector import extract_palette
from extensions.color_search.filter import ColorFilter
from extensions.color_search.panel import _ColorButton
from extensions.color_search.widget import ColorFilterWidget, _DEFAULT_TOLERANCE


@pytest.fixture()
def color_widget(qapp):
    return ColorFilterWidget()


def test_palette_tags_always_writes_all_palette_slots():
    tags = palette_tags([rgb_to_packed(255, 0, 0), rgb_to_packed(0, 255, 0)])
    assert tuple(tags.keys()) == PALETTE_KEYS
    assert tags["palette.1"] == "16711680"
    assert tags["palette.2"] == "65280"
    for key in PALETTE_KEYS[2:]:
        assert tags[key] == ""


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


def test_color_widget_swatch_click_selects_row_and_changes_color(color_widget):
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("extensions.color_search.widget.ColorPickerDialog.get_color", lambda *args, **kwargs: QtGui.QColor("#224466"))
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


def test_apply_color_filter_appends_ratio_tolerance():
    search = SimpleNamespace(apply_bars=MagicMock())
    window = SimpleNamespace(search_row_widget=search, sync_service_from_ui=MagicMock(), search_service=SimpleNamespace(execute_if_auto=MagicMock()))
    apply_color_filter.__wrapped__(None, w=window, hex_color="#ff0000", tolerance=1.0, mode="append_and", join="AND")
    bars = search.apply_bars.call_args.args[0]
    assert search.apply_bars.call_args.kwargs["mode"] == "append"
    assert bars[0]["op"] == "AND"
    assert bars[0]["params"]["mode"] == "AND"
    assert bars[0]["params"]["colors"][0]["tolerance"] == pytest.approx(1.0)


def test_apply_selected_color_noops_without_selection():
    search = SimpleNamespace(selected_param_widget=MagicMock(return_value=None))
    window = SimpleNamespace(search_row_widget=search, sync_service_from_ui=MagicMock(), search_service=SimpleNamespace(execute_if_auto=MagicMock()))
    apply_selected_color.__wrapped__(None, w=window, hex_color="#ff0000")
    window.sync_service_from_ui.assert_not_called()


def test_apply_selected_color_updates_selected_widget():
    widget = SimpleNamespace(replace_selected_color=MagicMock(return_value=True))
    search = SimpleNamespace(selected_param_widget=MagicMock(return_value=widget))
    window = SimpleNamespace(search_row_widget=search, sync_service_from_ui=MagicMock(), search_service=SimpleNamespace(execute_if_auto=MagicMock()))
    apply_selected_color.__wrapped__(None, w=window, hex_color="#ff0000")
    widget.replace_selected_color.assert_called_once_with("#FF0000")
    window.sync_service_from_ui.assert_called_once()


def test_color_panel_context_menu_includes_apply_selected(qapp):
    button = _ColorButton("#224466")
    items = button._menu_items()
    actions = [item for item in items if hasattr(item, "display")]
    assert [action.display for action in actions] == ["Apply to selected color", "Add as row AND", "Add as row OR"]

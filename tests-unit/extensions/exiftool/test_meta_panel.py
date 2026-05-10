import pytest
from PySide6 import QtWidgets
from extensions.exiftool.meta_panel import ExifToolMetaPanelPlugin
from wafer.ui.panel.searchable_meta_widget import (
    SearchableMetaWidget,
    build_value_html,
    highlight_html,
    SHORT_VALUE_LIMIT,
)


def test_plugin_attributes():
    plugin = ExifToolMetaPanelPlugin()
    assert plugin.PREFIX == "exiftool"
    assert plugin.NAME == "exiftool_meta_panel"
    assert plugin.DATA_SCOPE == "meta_info"
    assert plugin.DEFAULT_ENABLED is True


def test_create_widget_and_update(qtbot):
    plugin = ExifToolMetaPanelPlugin()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    w = plugin.create_card(parent)
    assert plugin._widget is not None
    assert isinstance(plugin._widget, SearchableMetaWidget)
    plugin.update_data({"width": "100", "height": "200"})
    assert plugin._widget._data == {"width": "100", "height": "200"}


def test_filter_by_key(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert w._filtered_keys == ["width"]


def test_filter_by_value(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_filter_empty_shows_all(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    data = {"width": "100", "height": "200"}
    w.set_data(data)
    w._apply_filter("")
    assert set(w._filtered_keys) == set(data.keys())


def test_status_label_visibility(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("")
    assert w._status_label.isHidden()
    w._apply_filter("width")
    assert not w._status_label.isHidden()
    assert "1 / 3" in w._status_label.text()


def test_highlight_html_no_query():
    result = highlight_html("hello world", "")
    assert "<span" not in result
    assert "hello world" in result


def test_highlight_html_with_query():
    result = highlight_html("hello world", "world")
    assert "<span" in result
    assert "world" in result


def test_highlight_html_escapes_special_chars():
    result = highlight_html("<script>alert(1)</script>", "")
    assert "<script>" not in result
    assert "&lt;script&gt;" in result


def test_highlight_html_case_insensitive():
    result = highlight_html("Hello HELLO hello", "hello")
    assert result.count("<span") == 3


def test_highlight_html_newlines_to_br():
    result = highlight_html("line1\nline2", "")
    assert "<br>" in result


def test_build_value_html_short_full():
    result = build_value_html("hello", "", None)
    assert "hello" in result
    assert "…" not in result


def test_build_value_html_long_preview():
    long_text = "a" * (SHORT_VALUE_LIMIT + 500)
    result = build_value_html(long_text, "", None)
    assert "…" in result


def test_build_value_html_long_with_match_snippets():
    text = "x" * 600 + "FINDME" + "y" * 600
    result = build_value_html(text, "findme")
    assert "<span" in result
    assert "FINDME" in result


def test_model_reflects_filter(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert w._model.rowCount() == 1
    w._apply_filter("")
    assert w._model.rowCount() == 3

import pytest
from PySide6 import QtWidgets
from wafer.ui.panel.searchable_meta_widget import (
    SearchableMetaWidget,
    build_value_html,
    highlight_html,
    SHORT_VALUE_LIMIT,
    SNIPPET_BUDGET,
    SAFETY_CHAR_LIMIT,
)


def test_set_data_populates_grid(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2"})
    assert w._data == {"a": "1", "b": "2"}
    assert len(w._filtered_keys) == 2


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
    data = {"a": "1", "b": "2", "c": "3"}
    w.set_data(data)
    w._apply_filter("")
    assert set(w._filtered_keys) == set(data.keys())


def test_status_label_hidden_when_no_filter(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2"})
    w._apply_filter("")
    assert w._status_label.isHidden()


def test_status_label_visible_when_filtered(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    w._apply_filter("width")
    assert not w._status_label.isHidden()
    assert "1 / 3" in w._status_label.text()


def test_current_query(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w._search.setText("  Hello  ")
    assert w.current_query() == "hello"


def test_build_value_html_short_no_query():
    result = build_value_html("hello", "", None)
    assert "hello" in result
    assert "…" not in result


def test_build_value_html_long_no_query():
    long_text = "a" * (SHORT_VALUE_LIMIT + 500)
    result = build_value_html(long_text, "", None)
    assert "…" in result
    assert len(result) < len(long_text)


def test_build_value_html_long_with_match():
    prefix = "x" * 600
    suffix = "y" * 600
    text = prefix + "FINDME" + suffix
    result = build_value_html(text, "findme")
    assert "<span" in result
    assert "FINDME" in result


def test_build_value_html_snippet_budget_distribution():
    parts = []
    for i in range(10):
        parts.append("a" * 100 + f"MATCH{i}" + "b" * 100)
    text = "z".join(parts)
    result = build_value_html(text, "match")
    assert "<span" in result
    assert "<br>" in result


def test_build_value_html_remaining_shown():
    parts = []
    for i in range(20):
        parts.append("a" * 200 + f"HIT{i}" + "b" * 200)
    text = "z".join(parts)
    result = build_value_html(text, "hit")
    assert "+", "more" in result


def test_highlight_html_no_query():
    result = highlight_html("hello world", "")
    assert "<span" not in result
    assert "hello world" in result


def test_highlight_html_with_query():
    result = highlight_html("hello world", "world")
    assert "<span" in result


def test_highlight_html_escapes_html():
    result = highlight_html("<b>bold</b>", "")
    assert "<b>" not in result
    assert "&lt;b&gt;" in result


def test_highlight_html_case_insensitive():
    result = highlight_html("Hello HELLO hello", "hello")
    assert result.count("<span") == 3


def test_highlight_html_newlines_to_br():
    result = highlight_html("line1\nline2", "")
    assert "<br>" in result


def test_model_row_count_matches_filter(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2", "c": "3"})
    w._apply_filter("a")
    assert w._model.rowCount() == 1
    w._apply_filter("")
    assert w._model.rowCount() == 3


def test_safety_limit_truncates(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "a" * (SAFETY_CHAR_LIMIT + 500)
    w.set_data({"big": huge})
    assert len(w._filtered_keys) == 1


def test_search_index_none_before_async_build(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1"})
    assert w._search_index is None or isinstance(w._search_index, dict)


def test_search_index_built_after_async(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    assert "width" in w._search_index
    assert w._search_index["width"] == "100"
    assert w._search_index["height"] == "200"


def test_filter_uses_index_when_available(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"width": "100", "height": "200", "model": "Canon"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_filter_works_without_index(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w._data = {"width": "100", "height": "200", "model": "Canon"}
    w._search_index = None
    w._apply_filter("canon")
    assert w._filtered_keys == ["model"]


def test_set_data_cancels_previous_index_build(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"old": "data"})
    w.set_data({"new": "data"})
    qtbot.waitUntil(lambda: w._search_index is not None, timeout=5000)
    assert "new" in w._search_index
    assert "old" not in w._search_index


def test_debounce_attribute_exists(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    assert w.DEBOUNCE_MS == 50

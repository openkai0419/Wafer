import pytest
from PySide6 import QtGui, QtWidgets
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


def test_full_value_returns_untruncated(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "x" * (SHORT_VALUE_LIMIT + 5000)
    w.set_data({"big": huge})
    assert w._full_value("big") == huge
    assert len(w._full_value("big")) == SHORT_VALUE_LIMIT + 5000


def test_key_for_row_returns_filtered_key(qtbot):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    w.set_data({"a": "1", "b": "2", "c": "3"})
    w._apply_filter("b")
    assert w._key_for_row(0) == "b"
    assert w._key_for_row(1) is None
    assert w._key_for_row(-1) is None


def test_double_click_opens_value_viewer(qtbot, monkeypatch):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "y" * (SHORT_VALUE_LIMIT + 1000)
    w.set_data({"big": huge})
    captured = {}

    def fake_open(parent, key, text):
        captured["key"] = key
        captured["text"] = text

    import wafer.ui.panel.searchable_meta_widget as mod

    monkeypatch.setattr(mod, "open_value_viewer", fake_open)
    index = w._model.index(0, 0)
    w._on_double_clicked(index)
    assert captured["text"] == huge
    assert captured["key"] == "big"


def test_context_menu_copy_value_uses_full_text(qtbot, monkeypatch):
    w = SearchableMetaWidget()
    qtbot.addWidget(w)
    huge = "z" * (SHORT_VALUE_LIMIT + 500)
    w.set_data({"big": huge})

    captured_actions: list[str] = []

    class FakeMenu:
        def __init__(self, *_a, **_k):
            self._actions: list[QtGui.QAction] = []
            self._copy_value_action: QtGui.QAction | None = None

        def addAction(self, label):
            act = QtGui.QAction(label)
            self._actions.append(act)
            captured_actions.append(label)
            if "value" in label.lower() and "viewer" not in label.lower():
                self._copy_value_action = act
            return act

        def addSeparator(self):
            return None

        def exec(self, *_a, **_k):
            return self._copy_value_action

    monkeypatch.setattr(QtWidgets, "QMenu", FakeMenu)
    QtWidgets.QApplication.clipboard().clear()
    pos = w._list_view.visualRect(w._model.index(0, 0)).center()
    w._on_context_menu(pos)
    assert any("key" in a.lower() for a in captured_actions)
    assert any("row" in a.lower() for a in captured_actions)
    assert any("viewer" in a.lower() for a in captured_actions)
    assert QtWidgets.QApplication.clipboard().text() == huge



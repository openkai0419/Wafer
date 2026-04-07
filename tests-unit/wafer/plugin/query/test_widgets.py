import pytest
from PySide6 import QtWidgets

from wafer.builtins.filters import TextFilter


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestTextFilterDisplayName:
    def test_display_name(self):
        assert TextFilter.DISPLAY_NAME == "Text"


class TestTextFilterCreateWidget:
    def test_returns_widget(self, qapp):
        w = TextFilter.create_widget()
        assert w is not None
        assert isinstance(w, QtWidgets.QWidget)

    def test_widget_has_changed_signal(self, qapp):
        w = TextFilter.create_widget()
        assert hasattr(w, "changed")

    def test_widget_has_search_bar(self, qapp):
        w = TextFilter.create_widget()
        assert hasattr(w, "search_bar")

    def test_widget_has_keys_combo(self, qapp):
        w = TextFilter.create_widget()
        assert hasattr(w, "keys_combo")


class TestTextFilterReadParams:
    def test_default_params(self, qapp):
        w = TextFilter.create_widget()
        params = TextFilter.read_params(w)
        assert "keywords" in params
        assert "query_mode" in params
        assert "keyword_mode" in params
        assert "keyword_separator" in params
        assert params["keywords"] == ""
        assert params["query_mode"] == "GLOB"
        assert params["keyword_mode"] == "AND"
        assert params["keyword_separator"] == ","

    def test_default_keys_none_when_combo_empty(self, qapp):
        w = TextFilter.create_widget()
        params = TextFilter.read_params(w)
        assert params["keys"] is None

    def test_keys_empty_list_when_all_unchecked(self, qapp):
        w = TextFilter.create_widget()
        w.keys_combo.remake([("path", 10), ("prompt", 5)])
        for a in w.keys_combo.actions:
            a.setChecked(False)
        params = TextFilter.read_params(w)
        assert params["keys"] == []

    def test_keys_after_remake(self, qapp):
        w = TextFilter.create_widget()
        w.keys_combo.remake([("path", 10), ("prompt", 5)])
        params = TextFilter.read_params(w)
        assert params["keys"] == ["path"]

    def test_after_typing(self, qapp):
        w = TextFilter.create_widget()
        w.search_bar.setText("hello")
        params = TextFilter.read_params(w)
        assert params["keywords"] == "hello"


class TestTextFilterWriteParams:
    def test_write_keywords(self, qapp):
        w = TextFilter.create_widget()
        TextFilter.write_params(w, {"keywords": "test query"})
        assert w.search_bar.text() == "test query"

    def test_write_query_mode(self, qapp):
        w = TextFilter.create_widget()
        TextFilter.write_params(w, {"query_mode": "LIKE"})
        params = TextFilter.read_params(w)
        assert params["query_mode"] == "LIKE"

    def test_write_keyword_mode(self, qapp):
        w = TextFilter.create_widget()
        TextFilter.write_params(w, {"keyword_mode": "OR"})
        params = TextFilter.read_params(w)
        assert params["keyword_mode"] == "OR"

    def test_write_keyword_separator(self, qapp):
        w = TextFilter.create_widget()
        TextFilter.write_params(w, {"keyword_separator": ";"})
        params = TextFilter.read_params(w)
        assert params["keyword_separator"] == ";"

    def test_roundtrip(self, qapp):
        w = TextFilter.create_widget()
        original = {
            "keywords": "foo bar",
            "query_mode": "LIKE",
            "keyword_mode": "OR",
            "keyword_separator": ";",
        }
        TextFilter.write_params(w, original)
        result = TextFilter.read_params(w)
        assert result["keywords"] == original["keywords"]
        assert result["query_mode"] == original["query_mode"]
        assert result["keyword_mode"] == original["keyword_mode"]
        assert result["keyword_separator"] == original["keyword_separator"]


class TestCheckableComboRemake:
    def test_remake_emits_action_changed(self, qapp):
        w = TextFilter.create_widget()
        signals = []
        w.keys_combo.action_changed.connect(lambda: signals.append(True))
        w.keys_combo.remake([("path", 10), ("prompt", 5)])
        assert len(signals) == 1

    def test_remake_twice_emits_each_time(self, qapp):
        w = TextFilter.create_widget()
        signals = []
        w.keys_combo.action_changed.connect(lambda: signals.append(True))
        w.keys_combo.remake([("path", 10)])
        w.keys_combo.remake([("path", 8), ("prompt", 3)])
        assert len(signals) == 2

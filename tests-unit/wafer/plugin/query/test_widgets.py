import pytest
from PySide6 import QtWidgets

from wafer.builtins.filters import TextFilter
from wafer.plugin.query.widgets import CheckableCombo, _KeySelectorPopup


def _active_key_set():
    return _KeySelectorPopup.instance().active_key_set()


def _catalog_keys():
    return [k for k, _ in _KeySelectorPopup.instance().catalog_data()]


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture(autouse=True)
def _reset_popup():
    _KeySelectorPopup._instance = None
    from wafer.core.app_settings import app_settings
    app_settings.settings.remove("filters/active_keys")
    yield
    _KeySelectorPopup._instance = None
    app_settings.settings.remove("filters/active_keys")


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
        w.keys_combo.set_checked([])
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


class TestCheckableComboActiveKeys:
    def test_active_keys_truthy_after_remake(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        assert combo.active_keys

    def test_active_keys_has_default_after_empty_remake(self, qapp):
        combo = CheckableCombo()
        combo.remake([])
        assert combo.active_keys == ["path"]

    def test_active_keys_contains_key(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        assert "path" in combo.active_keys

    def test_checked_items_default_key(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        assert combo.checked_items() == ["path"]

    def test_set_checked_toggles_state(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        combo.set_checked(["prompt"])
        assert "prompt" in combo.checked_items()
        assert "path" not in combo.checked_items()

    def test_set_checked_empty_unchecks_all(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        combo.set_checked([])
        assert combo.checked_items() == []
        assert combo.active_keys

    def test_set_checked_adds_missing_keys(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        combo.set_checked(["artist"])
        assert "artist" in combo.active_keys
        assert "artist" in combo.checked_items()

    def test_per_combo_checked_state(self, qapp):
        combo_a = CheckableCombo()
        combo_b = CheckableCombo()
        combo_a.remake([("path", 10), ("prompt", 5)])
        combo_a.set_checked(["prompt"])
        assert combo_a.checked_items() == ["prompt"]
        assert combo_b.checked_items() == ["path"]

    def test_remove_active_key_propagates(self, qapp):
        combo_a = CheckableCombo()
        combo_b = CheckableCombo()
        combo_a.remake([("path", 10), ("prompt", 5)])
        combo_b.set_checked(["prompt"])
        popup = _KeySelectorPopup.instance()
        popup._remove_active_key("prompt")
        popup._notify_active_keys_changed({"prompt"})
        assert "prompt" not in combo_a.checked_items()
        assert "prompt" not in combo_b.checked_items()


class TestKeySelectorPopupGroups:
    def test_prefixed_keys_grouped(self, qapp):
        combo = CheckableCombo()
        combo.remake([
            ("path", 100),
            ("exif.width", 50),
            ("exif.height", 50),
            ("nai.prompt", 30),
        ])
        popup = _KeySelectorPopup.instance()
        tree = popup._catalog_tree
        root = tree.invisibleRootItem()
        group_labels = []
        for i in range(root.childCount()):
            group_labels.append(root.child(i).text(0))
        assert any("exif" in label for label in group_labels)
        assert any("nai" in label for label in group_labels)

    def test_search_filters_catalog(self, qapp):
        combo = CheckableCombo()
        combo.remake([
            ("path", 100),
            ("exif.width", 50),
            ("exif.height", 50),
            ("nai.prompt", 30),
        ])
        popup = _KeySelectorPopup.instance()
        popup._search_input.setText("exif")
        root = popup._catalog_tree.invisibleRootItem()
        visible = []
        for i in range(root.childCount()):
            item = root.child(i)
            if not item.isHidden():
                visible.append(item.text(0))
        assert any("exif" in v for v in visible)
        assert not any("nai" in v for v in visible)

    def test_uncheck_all_active(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 10), ("prompt", 5)])
        assert combo.active_keys
        combo.set_checked([])
        assert combo.active_keys
        assert combo.checked_items() == []

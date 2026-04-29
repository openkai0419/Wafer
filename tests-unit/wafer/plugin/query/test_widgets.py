import pytest
from PySide6 import QtGui, QtWidgets

from wafer.builtins.filters import TextFilter
from wafer.core.color.theme import ThemeManager
from wafer.core.state import StateStore
from wafer.plugin.query.widgets import CheckableCombo, _CATALOG_KEY_ROLE, _KeySelectorPopup


def _active_key_set():
    return _KeySelectorPopup.instance().active_key_set()


def _catalog_keys():
    return [k for k, _ in _KeySelectorPopup.instance().catalog_data()]


def _tree_item_for_key(popup, key):
    root = popup._catalog_tree.invisibleRootItem()
    for i in range(root.childCount()):
        top_item = root.child(i)
        if top_item.data(0, _CATALOG_KEY_ROLE) == key:
            return top_item
        for j in range(top_item.childCount()):
            child = top_item.child(j)
            if child.data(0, _CATALOG_KEY_ROLE) == key:
                return child
    return None


def _group_item(popup, prefix):
    root = popup._catalog_tree.invisibleRootItem()
    for i in range(root.childCount()):
        item = root.child(i)
        if item.text(0).split("  (")[0] == prefix:
            return item
    return None


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture(autouse=True)
def _reset_popup():
    previous_state = StateStore._instance
    StateStore._instance = None
    _KeySelectorPopup._instance = None
    yield
    _KeySelectorPopup._instance = None
    StateStore._instance = previous_state


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

    def test_option_popup_has_title_label(self, qapp):
        w = TextFilter.create_widget()
        labels = [label.text() for label in w._option_popup.findChildren(QtWidgets.QLabel)]
        assert "Text Filter Options" in labels


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

    def test_save_state_includes_expanded_groups_and_splitter_sizes(self, qapp):
        combo = CheckableCombo()
        combo.remake([
            ("path", 100),
            ("exif.width", 50),
            ("exif.height", 50),
        ])
        popup = _KeySelectorPopup.instance()
        popup.resize(320, 420)
        popup.show()
        qapp.processEvents()
        popup._splitter.setSizes([90, 270])
        group = _group_item(popup, "exif")
        group.setExpanded(True)

        state = popup._save_state()

        assert state["keys"] == ["path"]
        assert state["expanded"] == ["exif"]
        assert len(state["splitter_sizes"]) == 2
        assert any(state["splitter_sizes"])

    def test_restore_state_applies_expanded_groups_after_catalog_rebuild(self, qapp):
        popup = _KeySelectorPopup.instance()
        popup._restore_state({"keys": ["path"], "expanded": ["exif"]})
        popup.set_catalog([
            ("path", 100),
            ("exif.width", 50),
            ("exif.height", 50),
        ])

        group = _group_item(popup, "exif")

        assert group.isExpanded()

    def test_restore_state_applies_splitter_sizes(self, qapp):
        popup = _KeySelectorPopup.instance()
        popup.resize(320, 420)
        popup.show()
        qapp.processEvents()

        popup._restore_state({"splitter_sizes": [80, 240]})
        qapp.processEvents()

        sizes = popup._splitter.sizes()
        assert sizes[0] < sizes[1]

    def test_catalog_colors_are_muted_until_active(self, qapp):
        combo = CheckableCombo()
        combo.remake([("path", 100), ("prompt", 5)])
        popup = _KeySelectorPopup.instance()
        palette = ThemeManager.instance().palette

        path_item = _tree_item_for_key(popup, "path")
        prompt_item = _tree_item_for_key(popup, "prompt")

        assert path_item.foreground(0).color() == QtGui.QColor(palette.text_primary)
        assert prompt_item.foreground(0).color() == QtGui.QColor(palette.text_muted)

    def test_catalog_added_key_is_checked_only_for_current_combo(self, qapp):
        combo_a = CheckableCombo()
        combo_b = CheckableCombo()
        combo_a.remake([("path", 10), ("prompt", 5)])
        popup = _KeySelectorPopup.instance()
        popup.open_for(combo_a)
        qapp.processEvents()

        prompt_item = _tree_item_for_key(popup, "prompt")
        popup._on_catalog_clicked(prompt_item, 0)

        assert "prompt" in combo_a.checked_items()
        assert "prompt" in combo_b.active_keys
        assert "prompt" not in combo_b.checked_items()

        popup.open_for(combo_b)
        qapp.processEvents()
        assert not popup._active_items["prompt"].checked

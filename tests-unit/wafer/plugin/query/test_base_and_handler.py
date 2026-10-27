import pytest

from PySide6 import QtWidgets

from wafer.plugin.query.base import BaseFilterPlugin, BaseSortPlugin, PathScope
from wafer.plugin.query.widgets import KeyStore
from wafer.plugin.query.handler import SortRegistry
from wafer.plugin.query.widgets import _KeySelectorPopup
from wafer.builtins.filters import TextFilter, _normalize_text_inputs


class TestBaseFilterPlugin:
    def test_abstract_build_path_query(self):
        with pytest.raises(TypeError):
            BaseFilterPlugin()


class TestPathScope:
    def test_unrestricted_condition_is_always_true(self):
        scope = PathScope()
        assert not scope.restricted
        assert scope.condition("mi.path") == "1"

    def test_restricted_condition_reads_scope_cte(self):
        scope = PathScope("SELECT path FROM files WHERE path LIKE ?", ["C:/a/%"])
        assert scope.restricted
        assert scope.condition("i.path") == f"i.path IN (SELECT path FROM {PathScope.CTE_NAME})"
        assert scope.params == ["C:/a/%"]


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


@pytest.fixture(autouse=True)
def _reset_popup():
    _KeySelectorPopup._instance = None
    yield
    _KeySelectorPopup._instance = None


class TestKeyStore:
    def test_set_data_emits_signal(self, qapp):
        store = KeyStore()
        received = []
        store.updated.connect(received.append)
        store.set_data([("prompt", 5)])
        assert len(received) == 1
        assert received[0] == [("prompt", 5)]

    def test_multiple_updates(self, qapp):
        store = KeyStore()
        received = []
        store.updated.connect(received.append)
        store.set_data([("a", 1)])
        store.set_data([("b", 2)])
        assert len(received) == 2
        assert store.data == [("b", 2)]


class TestTextFilterInheritableParams:
    def test_exports_settings_only(self):
        params = {
            "keys": ["path", "prompt"],
            "keywords": "sunset",
            "query_mode": "LIKE",
            "keyword_mode": "OR",
            "keyword_separator": " ",
        }
        result = TextFilter.inheritable_params(params)
        assert result == {
            "keys": ["path", "prompt"],
            "query_mode": "LIKE",
            "keyword_mode": "OR",
            "keyword_separator": " ",
        }
        assert "keywords" not in result

    def test_empty_params(self):
        assert TextFilter.inheritable_params({}) == {}

    def test_partial_params(self):
        result = TextFilter.inheritable_params({"keys": ["prompt"]})
        assert result == {"keys": ["prompt"]}


class TestTextFilterBindKeyStore:
    def test_bind_connects_and_applies(self, qapp):
        store = KeyStore()
        store.set_data([("path", 10), ("prompt", 5)])
        widget = TextFilter.create_widget()
        TextFilter.bind_key_store(widget, store)
        assert "path" in widget.keys_combo.active_keys
        assert "path" in widget.keys_combo.checked_items()
        catalog_keys = [k for k, _ in widget.keys_combo._popup.catalog_data()]
        assert "prompt" in catalog_keys

    def test_bind_receives_future_updates(self, qapp):
        store = KeyStore()
        widget = TextFilter.create_widget()
        TextFilter.bind_key_store(widget, store)

        store.set_data([("path", 20), ("artist", 8)])
        assert "path" in widget.keys_combo.active_keys
        catalog_keys = [k for k, _ in widget.keys_combo._popup.catalog_data()]
        assert "artist" in catalog_keys


class TestBaseSortPlugin:
    def test_sort_rows_raises(self):
        with pytest.raises(NotImplementedError):
            BaseSortPlugin.sort_rows([], True)


class TestSortRegistryValidation:
    def test_register_valid_meta_key(self):
        class Good(BaseSortPlugin):
            NAME = "_test_good"
            PRIORITY = 0
            META_KEY = "valid_key"

        reg = SortRegistry()
        reg.register(Good)
        assert reg.get("_test_good") is Good

    def test_register_none_meta_key(self):
        class NoMeta(BaseSortPlugin):
            NAME = "_test_nometa"
            PRIORITY = 0

        reg = SortRegistry()
        reg.register(NoMeta)
        assert reg.get("_test_nometa") is NoMeta

    def test_register_invalid_meta_key_raises(self):
        class Bad(BaseSortPlugin):
            NAME = "_test_bad"
            PRIORITY = 0
            META_KEY = "DROP TABLE"

        reg = SortRegistry()
        with pytest.raises(ValueError, match="Invalid META_KEY"):
            reg.register(Bad)


class TestNormalizeTextInputs:
    def test_string_keys(self):
        keys, inc, exc = _normalize_text_inputs({"keys": "path"})
        assert keys == ["path"]

    def test_none_keys(self):
        keys, inc, exc = _normalize_text_inputs({})
        assert keys == []

    def test_empty_keywords(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "", "keyword_separator": ","})
        assert inc == []
        assert exc == []

    def test_dash_only_excluded(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "-", "keyword_separator": ","})
        assert inc == []
        assert exc == []

    def test_trim_keywords_false_keeps_spaces(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": " a , -c ", "keyword_separator": ",", "trim_keywords": False})
        assert inc == [" a ", " -c "]
        assert exc == []

import pytest

from PySide6 import QtWidgets

from wafer.plugin.query.base import BaseFilterPlugin, BaseSortPlugin, KeyStore
from wafer.plugin.query.handler import SortRegistry, filter_registry, sort_registry
from wafer.plugin.query.widgets import _KeySelectorPopup
from wafer.plugin.registry import PluginRegistry
from wafer.core.db.db_utils import build_like_condition, escape_like
from wafer.builtins.filters import (
    TextFilter,
    DirectoryFilter,
    _normalize_text_inputs,
)
from wafer.builtins.sorts import (
    NaturalPathSort,
    NaturalNameSort,
    ModifiedSort,
    CreatedSort,
    SizeSort,
    CollectedSort,
    RandomSort,
)
from wafer.utils.formatting import natural_key


class TestBaseFilterPlugin:
    def test_abstract_build_path_query(self):
        with pytest.raises(TypeError):
            BaseFilterPlugin()

    def test_default_post_filter(self):
        rows = [{"a": 1}, {"a": 2}]
        assert BaseFilterPlugin.post_filter({}, rows) is rows

    def test_default_required_columns(self):
        assert BaseFilterPlugin.required_columns() == ()

    def test_subclass_must_implement_build(self):
        class Incomplete(BaseFilterPlugin):
            NAME = "incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_concrete_subclass(self):
        class MyFilter(BaseFilterPlugin):
            NAME = "my"

            @classmethod
            def build_path_query(cls, params, normalize_path):
                return "SELECT path FROM files", []

        sql, bind = MyFilter.build_path_query({}, None)
        assert sql == "SELECT path FROM files"

    def test_default_create_widget(self):
        assert BaseFilterPlugin.create_widget() is None

    def test_default_read_params(self):
        assert BaseFilterPlugin.read_params(None) == {}

    def test_default_write_params(self):
        BaseFilterPlugin.write_params(None, {"a": 1})

    def test_default_bind_key_store(self):
        BaseFilterPlugin.bind_key_store(None, None)

    def test_default_inheritable_params(self):
        assert BaseFilterPlugin.inheritable_params({}) == {}
        assert BaseFilterPlugin.inheritable_params({"keys": ["a"]}) == {}

    def test_default_display_name(self):
        assert BaseFilterPlugin.DISPLAY_NAME == ""


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


class TestKeyStore:
    def test_initial_data_empty(self, qapp):
        store = KeyStore()
        assert store.data == []

    def test_set_data_updates_property(self, qapp):
        store = KeyStore()
        store.set_data([("prompt", 5), ("artist", 3)])
        assert store.data == [("prompt", 5), ("artist", 3)]

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
    def test_default_sql_column_none(self):
        assert BaseSortPlugin.META_KEY is None

    def test_sort_rows_raises(self):
        with pytest.raises(NotImplementedError):
            BaseSortPlugin.sort_rows([], True)

    def test_concrete_subclass_sql_column(self):
        class MySort(BaseSortPlugin):
            NAME = "my"
            META_KEY = "created"

        assert MySort.META_KEY == "created"


class TestFilterRegistry:
    def test_register_and_get(self):
        reg = PluginRegistry()
        reg.register(TextFilter)
        assert reg.get("text") is TextFilter

    def test_get_missing(self):
        reg = PluginRegistry()
        assert reg.get("nonexistent") is None

    def test_list_all_sorted_by_priority(self):
        reg = PluginRegistry()
        reg.register(DirectoryFilter)
        reg.register(TextFilter)
        items = reg.list_all()
        assert items[0] is TextFilter
        assert items[1] is DirectoryFilter

    def test_override(self):
        reg = PluginRegistry()
        reg.register(TextFilter)

        class TextFilterV2(BaseFilterPlugin):
            NAME = "text"
            PRIORITY = 200

            @classmethod
            def build_path_query(cls, params, normalize_path):
                return None, []

        reg.register(TextFilterV2)
        assert reg.get("text") is TextFilterV2
        assert len(reg.list_all()) == 1


class TestSortRegistry:
    def test_register_and_get(self):
        reg = SortRegistry()
        reg.register(NaturalNameSort)
        assert reg.get("name") is NaturalNameSort

    def test_get_missing(self):
        reg = SortRegistry()
        assert reg.get("missing") is None

    def test_list_all_sorted_by_priority(self):
        reg = SortRegistry()
        reg.register(RandomSort)
        reg.register(NaturalPathSort)
        items = reg.list_all()
        assert items[0] is NaturalPathSort
        assert items[1] is RandomSort


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


class TestGlobalRegistries:
    def test_builtins_registered_in_filter_registry(self):
        assert filter_registry.get("text") is TextFilter
        assert filter_registry.get("directory") is DirectoryFilter

    def test_builtins_registered_in_sort_registry(self):
        assert sort_registry.get("path") is NaturalPathSort
        assert sort_registry.get("name") is NaturalNameSort
        assert sort_registry.get("modified") is ModifiedSort
        assert sort_registry.get("created") is CreatedSort
        assert sort_registry.get("size") is SizeSort
        assert sort_registry.get("collected") is CollectedSort
        assert sort_registry.get("random") is RandomSort


class TestNormalizeTextInputs:
    def test_string_keys(self):
        keys, inc, exc = _normalize_text_inputs({"keys": "path"})
        assert keys == ["path"]

    def test_list_keys(self):
        keys, inc, exc = _normalize_text_inputs({"keys": ["dpi", "Comment"]})
        assert keys == ["dpi", "Comment"]

    def test_none_keys(self):
        keys, inc, exc = _normalize_text_inputs({})
        assert keys == []

    def test_split_keywords(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "cat,dog,-fish", "keyword_separator": ","})
        assert inc == ["cat", "dog"]
        assert exc == ["fish"]

    def test_no_separator(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "cat dog"})
        assert inc == ["cat dog"]

    def test_empty_keywords(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "", "keyword_separator": ","})
        assert inc == []
        assert exc == []

    def test_dash_only_excluded(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": "-", "keyword_separator": ","})
        assert inc == []
        assert exc == []

    def test_whitespace_strip(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": " a , b , -c ", "keyword_separator": ","})
        assert inc == ["a", "b"]
        assert exc == ["c"]

    def test_tuple_keywords(self):
        keys, inc, exc = _normalize_text_inputs({"keywords": ("a,b", "c"), "keyword_separator": ","})
        assert inc == ["a,b", "c"]


class TestMatchClause:
    def test_like_mode(self):
        clause, vals = build_like_condition("path", ["cat"], "AND", "LIKE")
        assert "LIKE" in clause
        assert vals == ["%cat%"]

    def test_glob_mode(self):
        clause, vals = build_like_condition("path", ["cat"], "AND", "GLOB")
        assert "GLOB" in clause
        assert vals == ["*cat*"]

    def test_multiple_keywords_and(self):
        clause, vals = build_like_condition("path", ["a", "b"], "AND", "LIKE")
        assert " AND " in clause
        assert len(vals) == 2

    def test_multiple_keywords_or(self):
        clause, vals = build_like_condition("path", ["a", "b"], "OR", "LIKE")
        assert " OR " in clause

    def test_empty(self):
        clause, vals = build_like_condition("path", [], "AND", "LIKE")
        assert clause == ""
        assert vals == []

    def test_like_escape_percent(self):
        clause, vals = build_like_condition("path", ["100%"], "AND", "LIKE")
        assert "\\%" in vals[0]

    def test_like_escape_underscore(self):
        clause, vals = build_like_condition("path", ["a_b"], "AND", "LIKE")
        assert "\\_" in vals[0]


class TestEscapeLike:
    def test_percent(self):
        assert escape_like("100%") == "100\\%"

    def test_underscore(self):
        assert escape_like("a_b") == "a\\_b"

    def test_backslash(self):
        assert escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert escape_like("100%_\\") == "100\\%\\_\\\\"


class TestNaturalKey:
    def test_pure_alpha(self):
        assert natural_key("abc") == ["abc"]

    def test_pure_digits(self):
        assert natural_key("123") == ["", 123, ""]

    def test_mixed(self):
        result = natural_key("img_10.jpg")
        assert any(isinstance(c, int) for c in result)
        assert 10 in result

    def test_ordering(self):
        names = ["img_2.jpg", "img_10.jpg", "img_1.jpg"]
        sorted_names = sorted(names, key=natural_key)
        assert sorted_names == ["img_1.jpg", "img_2.jpg", "img_10.jpg"]

    def test_case_insensitive(self):
        assert natural_key("ABC") == natural_key("abc")

    def test_leading_zeros(self):
        assert natural_key("file_001.jpg") == natural_key("file_1.jpg")


class TestSortPluginAttributes:
    def test_natural_path_sort(self):
        assert NaturalPathSort.NAME == "path"
        assert NaturalPathSort.META_KEY is None

    def test_natural_name_sort(self):
        assert NaturalNameSort.NAME == "name"
        assert NaturalNameSort.META_KEY == "name"

    def test_modified_sort(self):
        assert ModifiedSort.META_KEY == "modified"

    def test_created_sort(self):
        assert CreatedSort.META_KEY == "created"

    def test_size_sort(self):
        assert SizeSort.META_KEY == "size"

    def test_collected_sort(self):
        assert CollectedSort.META_KEY == "collected"

    def test_random_sort(self):
        assert RandomSort.META_KEY is None
        assert RandomSort.NAME == "random"

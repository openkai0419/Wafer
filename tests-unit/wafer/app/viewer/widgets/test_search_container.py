import pytest
from unittest.mock import patch, MagicMock

from PySide6 import QtWidgets

from wafer.builtins.filters import TextFilter, DirectoryFilter
from wafer.plugin.query.base import KeyStore
from wafer.plugin.query.widgets import _KeySelectorPopup
from wafer.app.viewer.widgets.search_container import SearchContainer, FilterRow


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


class TestFilterRow:
    def test_create_with_text_filter(self, qapp):
        row = FilterRow(TextFilter)
        assert row.filter_cls is TextFilter

    def test_op_combo_default_and(self, qapp):
        row = FilterRow(TextFilter)
        assert row.operator == "AND"

    def test_op_hidden_when_show_op_false(self, qapp):
        row = FilterRow(TextFilter, show_op=False)
        assert not row._has_op

    def test_read_entry_returns_tuple(self, qapp):
        row = FilterRow(TextFilter, show_op=False)
        entry = row.read_entry()
        assert entry is not None
        cls, params, op = entry
        assert cls is TextFilter
        assert isinstance(params, dict)
        assert op is None

    def test_read_entry_with_op(self, qapp):
        row = FilterRow(TextFilter, show_op=True)
        entry = row.read_entry()
        cls, params, op = entry
        assert op == "AND"

    def test_write_entry(self, qapp):
        row = FilterRow(TextFilter, show_op=True)
        row.write_entry("text", {"keywords": "hello", "query_mode": "LIKE"}, "OR")
        entry = row.read_entry()
        cls, params, op = entry
        assert params["keywords"] == "hello"
        assert params["query_mode"] == "LIKE"
        assert op == "OR"

    def test_write_entry_wrong_type_ignored(self, qapp):
        row = FilterRow(TextFilter, show_op=True)
        row.write_entry("directory", {"directories": ["/a"]}, "OR")
        assert row.filter_cls is TextFilter

    def test_param_widget_exists(self, qapp):
        row = FilterRow(TextFilter)
        w = row.get_param_widget()
        assert w is not None

    def test_set_removable(self, qapp):
        row = FilterRow(TextFilter)
        row.show()
        row.set_removable(False)
        assert not row.remove_button.isVisibleTo(row)
        row.set_removable(True)
        assert row.remove_button.isVisibleTo(row)


class TestSearchContainer:
    def test_default_has_one_row(self, qapp):
        container = SearchContainer()
        assert len(container._rows) == 1

    def test_default_row_is_text_filter(self, qapp):
        container = SearchContainer()
        assert container._rows[0].filter_cls is TextFilter

    def test_default_row_removable(self, qapp):
        container = SearchContainer()
        container.show()
        assert container._rows[0].remove_button.isVisibleTo(container)

    def test_add_row(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        assert len(container._rows) == 2
        assert container._rows[1]._has_op

    def test_remove_filter(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        second = container._rows[1]
        container._on_remove_row(second)
        assert len(container._rows) == 1

    def test_remove_all_rows(self, qapp):
        container = SearchContainer()
        first = container._rows[0]
        container._on_remove_row(first)
        assert len(container._rows) == 0
        assert not container._empty_row.isHidden()

    def test_remove_first_updates_op_visibility(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        assert container._rows[1]._has_op
        first = container._rows[0]
        container._on_remove_row(first)
        assert len(container._rows) == 1
        assert not container._rows[0]._has_op

    def test_tools_move_to_last_row(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        assert container._tools_host is container._rows[-1]

    def test_tools_in_empty_state(self, qapp):
        container = SearchContainer()
        container._on_remove_row(container._rows[0])
        assert container._tools_host is None
        assert not container._empty_row.isHidden()

    def test_build_filter_entries_no_directories(self, qapp):
        container = SearchContainer()
        entries = container.build_filter_entries()
        assert len(entries) == 1
        cls, params, op = entries[0]
        assert cls is TextFilter
        assert op is None

    def test_build_filter_entries_with_directories(self, qapp):
        container = SearchContainer()
        entries = container.build_filter_entries(directories=["/photos"])
        assert len(entries) == 2
        assert entries[0][0] is TextFilter
        assert entries[0][2] is None
        assert entries[1][0] is DirectoryFilter
        assert entries[1][1]["directories"] == ["/photos"]

    def test_build_entries_multiple_rows(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        entries = container.build_filter_entries()
        assert len(entries) == 2

    def test_build_entries_empty(self, qapp):
        container = SearchContainer()
        container._on_remove_row(container._rows[0])
        entries = container.build_filter_entries()
        assert len(entries) == 0

    def test_get_sort_defaults(self, qapp):
        container = SearchContainer()
        sort_name, ascending = container.get_sort()
        assert sort_name == "path"
        assert ascending is False

    def test_set_sort(self, qapp):
        container = SearchContainer()
        container.set_sort("modified", True)
        sort_name, ascending = container.get_sort()
        assert sort_name == "modified"
        assert ascending is True

    def test_set_ascending(self, qapp):
        container = SearchContainer()
        container.set_ascending(True)
        _, ascending = container.get_sort()
        assert ascending is True

    def test_set_sort_by(self, qapp):
        container = SearchContainer()
        container.set_sort_by("name")
        sort_name, _ = container.get_sort()
        assert sort_name == "name"

    def test_sort_menu_syncs(self, qapp):
        container = SearchContainer()
        container.set_sort("size", True)
        checked_sort = [a for a in container._sort_group.actions() if a.isChecked()]
        assert len(checked_sort) == 1
        assert checked_sort[0].data() == "size"
        checked_order = [a for a in container._order_group.actions() if a.isChecked()]
        assert len(checked_order) == 1
        assert checked_order[0].data() is True

    def test_get_values_returns_dict(self, qapp):
        container = SearchContainer()
        values = container.get_values()
        assert isinstance(values, dict)
        assert "sort_by" in values
        assert "ascending" in values

    def test_get_values_empty(self, qapp):
        container = SearchContainer()
        container._on_remove_row(container._rows[0])
        assert container.get_values() == {}

    def test_set_search_text(self, qapp):
        container = SearchContainer()
        container.set_search_text("hello world")
        values = container.get_values()
        assert values.get("keywords") == "hello world"

    def test_filter_changed_signal(self, qapp):
        container = SearchContainer()
        signals = []
        container.filter_changed.connect(lambda: signals.append(True))
        container._add_row(TextFilter)
        assert len(signals) >= 1


class TestSearchContainerState:
    def test_save_state(self, qapp):
        container = SearchContainer()
        container.set_search_text("test")
        state = container.save_state()
        assert "rows" in state
        assert "sort_by" in state
        assert "ascending" in state
        assert len(state["rows"]) == 1
        assert state["rows"][0]["filter"] == "text"

    def test_restore_state(self, qapp):
        container = SearchContainer()
        state = {
            "rows": [
                {"filter": "text", "params": {"keywords": "restored", "query_mode": "LIKE"}, "op": None},
            ],
            "sort_by": "modified",
            "ascending": True,
        }
        container.restore_state(state)
        assert len(container._rows) == 1
        sort_name, ascending = container.get_sort()
        assert sort_name == "modified"
        assert ascending is True

    def test_restore_multiple_rows(self, qapp):
        container = SearchContainer()
        state = {
            "rows": [
                {"filter": "text", "params": {"keywords": "first"}, "op": None},
                {"filter": "text", "params": {"keywords": "second"}, "op": "OR"},
            ],
            "sort_by": "path",
            "ascending": False,
        }
        container.restore_state(state)
        assert len(container._rows) == 2
        assert not container._rows[0]._has_op
        assert container._rows[1]._has_op

    def test_restore_empty_rows_keeps_existing(self, qapp):
        container = SearchContainer()
        container.set_search_text("keep")
        state = {"rows": [], "sort_by": "size", "ascending": True}
        container.restore_state(state)
        assert len(container._rows) == 1
        sort_name, ascending = container.get_sort()
        assert sort_name == "size"
        assert ascending is True

    def test_restore_updates_tool_placement(self, qapp):
        container = SearchContainer()
        state = {
            "rows": [
                {"filter": "text", "params": {"keywords": "a"}, "op": None},
                {"filter": "text", "params": {"keywords": "b"}, "op": "OR"},
            ],
            "sort_by": "path",
            "ascending": True,
        }
        container.restore_state(state)
        assert container._tools_host is container._rows[-1]

    def test_roundtrip_save_restore(self, qapp):
        container1 = SearchContainer()
        container1._add_row(TextFilter)
        state = container1.save_state()
        container2 = SearchContainer()
        container2.restore_state(state)
        assert len(container2._rows) == len(container1._rows)


class TestSearchContainerFolderWorker:
    def test_first_call_runs(self, qapp):
        container = SearchContainer()
        with patch.object(container, "_dispatcher") as mock_disp:
            container.run_folder_worker("dummy.db", [])
            assert mock_disp.post.call_count == 1

    def test_duplicate_call_skipped(self, qapp):
        container = SearchContainer()
        with patch.object(container, "_dispatcher") as mock_disp:
            container.run_folder_worker("dummy.db", ["/a"])
            container.run_folder_worker("dummy.db", ["/a"])
            assert mock_disp.post.call_count == 1

    def test_different_paths_not_skipped(self, qapp):
        container = SearchContainer()
        with patch.object(container, "_dispatcher") as mock_disp:
            container.run_folder_worker("dummy.db", ["/a"])
            container.run_folder_worker("dummy.db", ["/b"])
            assert mock_disp.post.call_count == 2


class TestUpdateKeyCombos:
    def test_filepath_present_when_in_results(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([("path", 10), ("prompt", 5), ("artist", 3)])
        w = container._rows[0].get_param_widget()
        assert "path" in w.keys_combo.active_keys

    def test_filepath_default_checked(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([("path", 10), ("prompt", 5)])
        w = container._rows[0].get_param_widget()
        assert "path" in w.keys_combo.checked_items()

    def test_counts_in_catalog(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([("path", 10), ("prompt", 5)])
        w = container._rows[0].get_param_widget()
        catalog = dict(w.keys_combo._popup.catalog_data())
        assert catalog["path"] == 10

    def test_empty_results_keeps_default_key(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([])
        w = container._rows[0].get_param_widget()
        assert w.keys_combo.active_keys == ["path"]

    def test_all_rows_receive_data(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        container._key_store.set_data([("path", 10), ("prompt", 5)])
        for row in container._rows:
            w = row.get_param_widget()
            assert "path" in w.keys_combo.active_keys
            catalog_keys = [k for k, _ in w.keys_combo._popup.catalog_data()]
            assert "prompt" in catalog_keys

    def test_new_row_receives_existing_data(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([("path", 20), ("artist", 8)])
        container._add_row(TextFilter)
        w = container._rows[1].get_param_widget()
        assert "path" in w.keys_combo.active_keys
        catalog_keys = [k for k, _ in w.keys_combo._popup.catalog_data()]
        assert "artist" in catalog_keys

    def test_restored_rows_receive_existing_data(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([("path", 15), ("prompt", 7)])
        state = {
            "rows": [
                {"filter": "text", "params": {"keywords": "a"}, "op": None},
                {"filter": "text", "params": {"keywords": "b"}, "op": "OR"},
            ],
            "sort_by": "path",
            "ascending": True,
        }
        container.restore_state(state)
        for row in container._rows:
            w = row.get_param_widget()
            assert "path" in w.keys_combo.active_keys


class TestInvalidateKeyCache:
    def test_invalidate_allows_same_paths(self, qapp):
        container = SearchContainer()
        with patch.object(container, "_dispatcher") as mock_disp:
            container.run_folder_worker("db1.db", ["/a"])
            assert mock_disp.post.call_count == 1
            container.invalidate_key_cache()
            container.run_folder_worker("db2.db", ["/a"])
            assert mock_disp.post.call_count == 2

    def test_invalidate_resets_last_paths(self, qapp):
        container = SearchContainer()
        container._last_paths = ("/some/path",)
        container.invalidate_key_cache()
        assert container._last_paths != ("/some/path",)


class TestFilterInheritance:
    def test_new_row_inherits_settings_from_existing(self, qapp):
        container = SearchContainer()
        primary = container._rows[0].get_param_widget()
        primary.write_params(
            {
                "query_mode": "LIKE",
                "keyword_mode": "OR",
                "keyword_separator": " ",
                "keys": ["prompt", "path"],
            }
        )
        container._add_row(TextFilter)
        second = container._rows[1].get_param_widget()
        params = second.read_params()
        assert params["query_mode"] == "LIKE"
        assert params["keyword_mode"] == "OR"
        assert params["keyword_separator"] == " "

    def test_new_row_does_not_inherit_keywords(self, qapp):
        container = SearchContainer()
        primary = container._rows[0].get_param_widget()
        primary.write_params({"keywords": "sunset"})
        container._add_row(TextFilter)
        second = container._rows[1].get_param_widget()
        params = second.read_params()
        assert params["keywords"] == ""

    def test_later_row_overwrites_earlier(self, qapp):
        container = SearchContainer()
        primary = container._rows[0].get_param_widget()
        primary.write_params({"query_mode": "LIKE"})
        container._add_row(TextFilter)
        second = container._rows[1].get_param_widget()
        second.write_params({"query_mode": "GLOB"})
        container._add_row(TextFilter)
        third = container._rows[2].get_param_widget()
        params = third.read_params()
        assert params["query_mode"] == "GLOB"

    def test_collect_inherited_params_empty_when_no_rows(self, qapp):
        container = SearchContainer()
        container._on_remove_row(container._rows[0])
        assert container._collect_inherited_params() == {}

    def test_cross_filter_inheritance_keys(self, qapp):
        from extensions.additional_filters.regex_filter import RegexFilter

        container = SearchContainer()
        container._key_store.set_data([("path", 10), ("prompt", 5)])
        primary = container._rows[0].get_param_widget()
        primary.keys_combo.set_checked(["prompt"])
        container._add_row(RegexFilter)
        second = container._rows[1].get_param_widget()
        params = second.read_params()
        assert "prompt" in (params.get("keys") or [])

    def test_first_row_no_inheritance(self, qapp):
        container = SearchContainer()
        container._on_remove_row(container._rows[0])
        container._add_row(TextFilter)
        params = container._rows[0].get_param_widget().read_params()
        assert params["query_mode"] == "GLOB"
        assert params["keyword_mode"] == "AND"

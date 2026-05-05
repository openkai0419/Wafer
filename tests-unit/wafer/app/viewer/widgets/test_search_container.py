import pytest
from unittest.mock import patch, MagicMock

from PySide6 import QtCore, QtWidgets

from wafer.builtins.filters import TextFilter, DirectoryFilter, ContainedFilesFilter
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
    yield
    _KeySelectorPopup._instance = None


def _menu_action_label(action):
    widget = action.defaultWidget() if isinstance(action, QtWidgets.QWidgetAction) else None
    if widget is not None:
        labels = [label.text() for label in widget.findChildren(QtWidgets.QLabel) if label.objectName() != "checkMark" and label.text()]
        if labels:
            return labels[0]
    return action.text()


def _menu_labels(menu):
    labels = []
    for action in menu.actions():
        if action.isSeparator():
            continue
        text = _menu_action_label(action)
        if text:
            labels.append(text)
        if action.menu():
            labels.extend(_menu_labels(action.menu()))
    return labels


def _find_menu_action(menu, text):
    for action in menu.actions():
        if _menu_action_label(action) == text:
            return action
        if action.menu():
            found = _find_menu_action(action.menu(), text)
            if found is not None:
                return found
    return None


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

    def test_default_enabled(self, qapp):
        row = FilterRow(TextFilter)
        assert row.is_enabled() is True

    def test_no_dedicated_toggle_button(self, qapp):
        row = FilterRow(TextFilter)
        assert not hasattr(row, "toggle_button")

    def test_set_enabled_false_skips_entry(self, qapp):
        row = FilterRow(TextFilter, show_op=False)
        row.set_enabled(False)
        assert row.is_enabled() is False
        assert row.read_entry() is None

    def test_set_enabled_true_restores_entry(self, qapp):
        row = FilterRow(TextFilter, show_op=False)
        row.set_enabled(False)
        row.set_enabled(True)
        assert row.read_entry() is not None

    def test_set_enabled_does_not_emit_changed(self, qapp):
        row = FilterRow(TextFilter)
        signals = []
        row.changed.connect(lambda: signals.append(True))
        row.set_enabled(False)
        assert signals == []

    def test_disabled_grays_out_param_widget(self, qapp):
        row = FilterRow(TextFilter)
        w = row.get_param_widget()
        assert w.isEnabled() is True
        row.set_enabled(False)
        assert w.isEnabled() is False
        row.set_enabled(True)
        assert w.isEnabled() is True

    def test_disabled_grays_out_op_combo(self, qapp):
        row = FilterRow(TextFilter, show_op=True)
        assert row.op_combo.isEnabled() is True
        row.set_enabled(False)
        assert row.op_combo.isEnabled() is False
        row.set_enabled(True)
        assert row.op_combo.isEnabled() is True

    def test_remove_button_context_request_uses_global_position(self, qapp):
        row = FilterRow(TextFilter)
        received = []
        row.context_requested.connect(lambda r, pos: received.append((r, pos)))
        row.remove_button.customContextMenuRequested.emit(QtCore.QPoint(1, 2))
        assert received[0][0] is row
        assert isinstance(received[0][1], QtCore.QPoint)


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

    def test_build_filter_entries_excludes_contained_files_when_disabled(self, qapp):
        container = SearchContainer()
        entries = container.build_filter_entries(include_contained_files=False)
        assert len(entries) == 2
        assert entries[0][0] is TextFilter
        assert entries[1][0] is ContainedFilesFilter
        assert entries[1][1] == {"include": False}

    def test_internal_filters_are_hidden_from_add_menu(self, qapp):
        container = SearchContainer()
        assert ContainedFilesFilter not in container._available_filter_classes()

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
        assert sort_name == "none"
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
        menu = container._build_sort_menu()
        size_action = _find_menu_action(menu, "Size")
        ascending_action = _find_menu_action(menu, "Ascending")
        descending_action = _find_menu_action(menu, "Descending")
        assert size_action is not None
        assert size_action.isChecked()
        assert ascending_action is not None
        assert ascending_action.isChecked()
        assert descending_action is not None
        assert not descending_action.isChecked()

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

    def test_filter_changed_signal(self, qapp):
        container = SearchContainer()
        signals = []
        container.filter_changed.connect(lambda: signals.append(True))
        container._add_row(TextFilter)
        assert len(signals) >= 1

    def test_row_menu_contains_row_actions(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        container._add_row(TextFilter)
        menu = container._build_row_menu(container._rows[1])
        labels = _menu_labels(menu)
        assert "Enabled" in labels
        assert "Move up" in labels
        assert "Move down" in labels
        assert "Move to top" in labels
        assert "Move to bottom" in labels
        assert "Delete filter" in labels
        assert any(a.menu() and a.text() == "Add filter after this" for a in menu.actions())

    def test_row_menu_has_header(self, qapp):
        container = SearchContainer()
        menu = container._build_row_menu(container._rows[0])
        header = menu.actions()[0]
        assert isinstance(header, QtWidgets.QWidgetAction)
        widget = header.defaultWidget()
        assert widget is not None
        assert widget.findChild(QtWidgets.QLabel).text() == "Filter Menu"

    def test_row_menu_enabled_action_is_checkable(self, qapp):
        container = SearchContainer()
        menu = container._build_row_menu(container._rows[0])
        enabled_action = _find_menu_action(menu, "Enabled")
        assert enabled_action is not None
        assert enabled_action.isCheckable()
        assert enabled_action.isChecked()

    def test_row_menu_enabled_action_sets_state(self, qapp):
        container = SearchContainer()
        menu = container._build_row_menu(container._rows[0])
        enabled_action = _find_menu_action(menu, "Enabled")
        assert enabled_action is not None
        enabled_action.trigger()
        assert container._rows[0].is_enabled() is False

    def test_toggle_row_enabled_from_menu_action(self, qapp):
        container = SearchContainer()
        signals = []
        container.filter_changed.connect(lambda: signals.append(True))
        container._toggle_row_enabled(container._rows[0])
        assert container._rows[0].is_enabled() is False
        assert len(signals) == 1

    def test_add_row_after_inserts_after_target(self, qapp):
        container = SearchContainer()
        first = container._rows[0]
        container._add_row(TextFilter)
        second = container._rows[1]
        container._add_row_after(first, TextFilter)
        assert len(container._rows) == 3
        assert container._rows[0] is first
        assert container._rows[2] is second
        assert container._rows[1].filter_cls is TextFilter

    def test_insert_row_updates_op_visibility(self, qapp):
        container = SearchContainer()
        container._insert_row(0, TextFilter)
        assert len(container._rows) == 2
        assert not container._rows[0]._has_op
        assert container._rows[1]._has_op

    def test_insert_row_updates_tool_placement(self, qapp):
        container = SearchContainer()
        container._insert_row(0, TextFilter)
        assert container._tools_host is container._rows[-1]

    def test_insert_row_inherits_from_previous_rows_only(self, qapp):
        container = SearchContainer()
        first = container._rows[0].get_param_widget()
        first.write_params({"query_mode": "LIKE"})
        container._add_row(TextFilter)
        second = container._rows[1].get_param_widget()
        second.write_params({"query_mode": "GLOB"})
        container._add_row_after(container._rows[0], TextFilter)
        inserted = container._rows[1].get_param_widget()
        assert inserted.read_params()["query_mode"] == "LIKE"

    def test_move_row_up(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        first, second = container._rows
        container._move_row(second, 0)
        assert container._rows == [second, first]

    def test_move_row_down(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        first, second = container._rows
        container._move_row(first, 1)
        assert container._rows == [second, first]

    def test_move_row_updates_layout_order(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        first, second = container._rows
        container._move_row(first, 1)
        assert container._filter_stack.itemAt(0).widget() is second
        assert container._filter_stack.itemAt(1).widget() is first

    def test_move_row_updates_op_visibility(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        container._move_row(container._rows[1], 0)
        assert not container._rows[0]._has_op
        assert container._rows[1]._has_op

    def test_move_row_preserves_enabled_state(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        first, second = container._rows
        second.set_enabled(False)
        container._move_row(second, 0)
        assert container._rows[0] is second
        assert container._rows[0].is_enabled() is False
        assert container._rows[1] is first
        assert container._rows[1].is_enabled() is True

    def test_move_row_updates_tool_placement(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        last = container._rows[-1]
        container._move_row(last, 0)
        assert container._tools_host is container._rows[-1]

    def test_move_row_emits_once(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        signals = []
        container.filter_changed.connect(lambda: signals.append(True))
        container._move_row(container._rows[1], 0)
        assert len(signals) == 1


class TestSearchContainerState:
    def test_save_state(self, qapp):
        container = SearchContainer()
        state = container.save_state()
        assert "bars" in state
        assert "sort_by" in state
        assert "ascending" in state
        assert len(state["bars"]) == 1
        assert state["bars"][0]["filter"] == "text"

    def test_restore_state(self, qapp):
        container = SearchContainer()
        state = {
            "bars": [
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
            "bars": [
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
        state = {"bars": [], "sort_by": "size", "ascending": True}
        container.restore_state(state)
        assert len(container._rows) == 1
        sort_name, ascending = container.get_sort()
        assert sort_name == "size"
        assert ascending is True

    def test_restore_updates_tool_placement(self, qapp):
        container = SearchContainer()
        state = {
            "bars": [
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

    def test_save_includes_enabled_field(self, qapp):
        container = SearchContainer()
        state = container.save_state()
        assert state["bars"][0]["enabled"] is True

    def test_save_preserves_disabled_rows(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        container._rows[1].set_enabled(False)
        state = container.save_state()
        assert len(state["bars"]) == 2
        assert state["bars"][0]["enabled"] is True
        assert state["bars"][1]["enabled"] is False

    def test_disabled_row_excluded_from_filter_entries(self, qapp):
        container = SearchContainer()
        container._add_row(TextFilter)
        container._rows[1].set_enabled(False)
        entries = container.build_filter_entries()
        assert len(entries) == 1

    def test_restore_enabled_state(self, qapp):
        container = SearchContainer()
        state = {
            "bars": [
                {"filter": "text", "params": {"keywords": "a"}, "op": None, "enabled": True},
                {"filter": "text", "params": {"keywords": "b"}, "op": "OR", "enabled": False},
            ],
            "sort_by": "path",
            "ascending": False,
        }
        container.restore_state(state)
        assert container._rows[0].is_enabled() is True
        assert container._rows[1].is_enabled() is False

    def test_restore_legacy_state_defaults_enabled(self, qapp):
        container = SearchContainer()
        state = {
            "bars": [
                {"filter": "text", "params": {"keywords": "legacy"}, "op": None},
            ],
            "sort_by": "path",
            "ascending": False,
        }
        container.restore_state(state)
        assert container._rows[0].is_enabled() is True

    def test_roundtrip_disabled_row(self, qapp):
        container1 = SearchContainer()
        container1._add_row(TextFilter)
        container1._rows[1].set_enabled(False)
        state = container1.save_state()
        container2 = SearchContainer()
        container2.restore_state(state)
        assert len(container2._rows) == 2
        assert container2._rows[1].is_enabled() is False


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
            "bars": [
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

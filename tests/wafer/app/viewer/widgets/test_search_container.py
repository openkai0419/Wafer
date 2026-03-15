import pytest
from unittest.mock import patch, MagicMock

from PySide6 import QtWidgets

from wafer.plugin.query.builtin import TextFilter, DirectoryFilter
from wafer.plugin.query.base import KeyStore
from wafer.app.viewer.widgets.search_container import SearchContainer, FilterRow


@pytest.fixture()
def qapp():
    app = QtWidgets.QApplication.instance()
    if app is None:
        app = QtWidgets.QApplication([])
    return app


class TestFilterRow:

    def test_create_with_text_filter(self, qapp):
        row = FilterRow(TextFilter)
        assert row.filter_cls is TextFilter

    def test_op_combo_default_and(self, qapp):
        row = FilterRow(TextFilter)
        assert row.operator == 'AND'

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
        assert op == 'AND'

    def test_write_entry(self, qapp):
        row = FilterRow(TextFilter, show_op=True)
        row.write_entry('text', {'keywords': 'hello', 'query_mode': 'LIKE'}, 'OR')
        entry = row.read_entry()
        cls, params, op = entry
        assert params['keywords'] == 'hello'
        assert params['query_mode'] == 'LIKE'
        assert op == 'OR'

    def test_type_combo_excludes_directory(self, qapp):
        row = FilterRow(TextFilter)
        items = [row.type_combo.itemData(i) for i in range(row.type_combo.count())]
        assert 'directory' not in items
        assert 'text' in items

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

    def test_default_row_not_removable(self, qapp):
        container = SearchContainer()
        container.show()
        assert not container._rows[0].remove_button.isVisibleTo(container)

    def test_add_filter(self, qapp):
        container = SearchContainer()
        container._on_add_filter()
        assert len(container._rows) == 2
        assert container._rows[1]._has_op
        container.show()
        assert container._rows[1].remove_button.isVisibleTo(container)

    def test_remove_filter(self, qapp):
        container = SearchContainer()
        container._on_add_filter()
        second = container._rows[1]
        container._on_remove_row(second)
        assert len(container._rows) == 1

    def test_cannot_remove_only_row(self, qapp):
        container = SearchContainer()
        assert not container._rows[0].remove_button.isVisible()

    def test_build_filter_entries_no_directories(self, qapp):
        container = SearchContainer()
        entries = container.build_filter_entries()
        assert len(entries) == 1
        cls, params, op = entries[0]
        assert cls is TextFilter
        assert op is None

    def test_build_filter_entries_with_directories(self, qapp):
        container = SearchContainer()
        entries = container.build_filter_entries(directories=['/photos'])
        assert len(entries) == 2
        assert entries[0][0] is TextFilter
        assert entries[0][2] is None
        assert entries[1][0] is DirectoryFilter
        assert entries[1][1]['directories'] == ['/photos']

    def test_build_entries_multiple_rows(self, qapp):
        container = SearchContainer()
        container._on_add_filter()
        entries = container.build_filter_entries()
        assert len(entries) == 2

    def test_get_sort_defaults(self, qapp):
        container = SearchContainer()
        sort_name, ascending = container.get_sort()
        assert isinstance(sort_name, str)
        assert isinstance(ascending, bool)

    def test_set_sort(self, qapp):
        container = SearchContainer()
        container.set_sort('modified', True)
        sort_name, ascending = container.get_sort()
        assert sort_name == 'modified'
        assert ascending is True

    def test_set_ascending(self, qapp):
        container = SearchContainer()
        container.set_ascending(True)
        _, ascending = container.get_sort()
        assert ascending is True

    def test_get_values_returns_dict(self, qapp):
        container = SearchContainer()
        values = container.get_values()
        assert isinstance(values, dict)
        assert 'sort_by' in values
        assert 'ascending' in values

    def test_set_search_text(self, qapp):
        container = SearchContainer()
        container.set_search_text('hello world')
        values = container.get_values()
        assert values.get('keywords') == 'hello world'

    def test_filter_changed_signal(self, qapp):
        container = SearchContainer()
        signals = []
        container.filter_changed.connect(lambda: signals.append(True))
        container._on_add_filter()
        assert len(signals) >= 1


class TestSearchContainerState:

    def test_save_state(self, qapp):
        container = SearchContainer()
        container.set_search_text('test')
        state = container.save_state()
        assert 'rows' in state
        assert 'sort_by' in state
        assert 'ascending' in state
        assert len(state['rows']) == 1
        assert state['rows'][0]['filter'] == 'text'

    def test_restore_state(self, qapp):
        container = SearchContainer()
        state = {
            'rows': [
                {'filter': 'text', 'params': {'keywords': 'restored', 'query_mode': 'LIKE'}, 'op': None},
            ],
            'sort_by': 'modified',
            'ascending': True,
        }
        container.restore_state(state)
        assert len(container._rows) == 1
        sort_name, ascending = container.get_sort()
        assert sort_name == 'modified'
        assert ascending is True

    def test_restore_multiple_rows(self, qapp):
        container = SearchContainer()
        state = {
            'rows': [
                {'filter': 'text', 'params': {'keywords': 'first'}, 'op': None},
                {'filter': 'text', 'params': {'keywords': 'second'}, 'op': 'OR'},
            ],
            'sort_by': 'path',
            'ascending': False,
        }
        container.restore_state(state)
        assert len(container._rows) == 2
        assert not container._rows[0]._has_op
        assert container._rows[1]._has_op

    def test_roundtrip_save_restore(self, qapp):
        container1 = SearchContainer()
        container1._on_add_filter()
        state = container1.save_state()
        container2 = SearchContainer()
        container2.restore_state(state)
        assert len(container2._rows) == len(container1._rows)


class TestSearchContainerFolderWorker:

    def test_first_call_runs(self, qapp):
        container = SearchContainer()
        with patch.object(container, '_dispatcher') as mock_disp:
            container.run_folder_worker('dummy.db', [])
            assert mock_disp.post.call_count == 1

    def test_duplicate_call_skipped(self, qapp):
        container = SearchContainer()
        with patch.object(container, '_dispatcher') as mock_disp:
            container.run_folder_worker('dummy.db', ['/a'])
            container.run_folder_worker('dummy.db', ['/a'])
            assert mock_disp.post.call_count == 1

    def test_different_paths_not_skipped(self, qapp):
        container = SearchContainer()
        with patch.object(container, '_dispatcher') as mock_disp:
            container.run_folder_worker('dummy.db', ['/a'])
            container.run_folder_worker('dummy.db', ['/b'])
            assert mock_disp.post.call_count == 2


class TestUpdateKeyCombos:

    def test_filepath_present_when_in_results(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([('__filepath__', 10), ('prompt', 5), ('artist', 3)])
        w = container._rows[0].get_param_widget()
        items = [a.data() for a in w.keys_combo.actions]
        assert '__filepath__' in items

    def test_filepath_default_checked(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([('__filepath__', 10), ('prompt', 5)])
        w = container._rows[0].get_param_widget()
        fp_action = next(a for a in w.keys_combo.actions if a.data() == '__filepath__')
        assert fp_action.isChecked()

    def test_counts_passed_through(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([('__filepath__', 10), ('prompt', 5)])
        w = container._rows[0].get_param_widget()
        fp_action = next(a for a in w.keys_combo.actions if a.data() == '__filepath__')
        assert '(10)' in fp_action.text()

    def test_empty_results_no_actions(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([])
        w = container._rows[0].get_param_widget()
        assert len(w.keys_combo.actions) == 0

    def test_all_rows_receive_data(self, qapp):
        container = SearchContainer()
        container._on_add_filter()
        container._key_store.set_data([('__filepath__', 10), ('prompt', 5)])
        for row in container._rows:
            w = row.get_param_widget()
            items = [a.data() for a in w.keys_combo.actions]
            assert '__filepath__' in items
            assert 'prompt' in items

    def test_new_row_receives_existing_data(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([('__filepath__', 20), ('artist', 8)])
        container._on_add_filter()
        w = container._rows[1].get_param_widget()
        items = [a.data() for a in w.keys_combo.actions]
        assert '__filepath__' in items
        assert 'artist' in items

    def test_restored_rows_receive_existing_data(self, qapp):
        container = SearchContainer()
        container._key_store.set_data([('__filepath__', 15), ('prompt', 7)])
        state = {
            'rows': [
                {'filter': 'text', 'params': {'keywords': 'a'}, 'op': None},
                {'filter': 'text', 'params': {'keywords': 'b'}, 'op': 'OR'},
            ],
            'sort_by': 'path',
            'ascending': True,
        }
        container.restore_state(state)
        for row in container._rows:
            w = row.get_param_widget()
            items = [a.data() for a in w.keys_combo.actions]
            assert '__filepath__' in items

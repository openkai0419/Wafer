import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.app.viewer.renamer.dialog import (
    BatchRenameDialog,
    _fetch_metadata_sync,
)
from wafer.app.viewer.renamer.engine import (
    PostProcess,
    RenameResult,
    RenameEngine,
    RenameColumn,
)
from wafer.builtins.rename_sources import (
    NameSource,
    ExtSource,
    FixedSource,
    SequentialSource,
)
from wafer.core.qt.dispatcher import CancelToken
from wafer.core.state import StateStore


@pytest.fixture(autouse=True)
def _reset_singleton():
    BatchRenameDialog._instance = None
    BatchRenameDialog._saved_state = {}
    BatchRenameDialog._registered = False
    yield
    BatchRenameDialog._instance = None
    BatchRenameDialog._saved_state = {}
    BatchRenameDialog._registered = False
    StateStore._instance = None


@pytest.fixture(autouse=True)
def _suppress_msgbox():
    with patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.information'), \
         patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.warning'):
        yield


@pytest.fixture
def tmp_files(tmp_path):
    files = []
    for name in ['a.jpg', 'b.jpg', 'c.jpg']:
        f = tmp_path / name
        f.write_bytes(b'\x00' * 16)
        files.append(f)
    return files


class TestRenameResultMissing:

    def test_missing_default_false(self):
        r = RenameResult(original='a.jpg', segments=['a', '.jpg'], new_name='a.jpg')
        assert r.missing is False

    def test_missing_flag(self):
        r = RenameResult(original='a.jpg', segments=[], new_name='a.jpg', missing=True)
        assert r.missing is True


class TestSingleton:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_open_creates_instance(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog.open(tmp_files)
        assert BatchRenameDialog._instance is dlg
        assert dlg.isVisible()
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_open_replaces_existing(self, mock_init, qtbot, tmp_files, tmp_path):
        dlg1 = BatchRenameDialog.open(tmp_files)
        dlg1.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg1)
        other = [tmp_path / 'x.jpg']
        other[0].write_bytes(b'\x00')
        dlg2 = BatchRenameDialog.open(other)
        dlg2.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg2)
        assert dlg2 is not dlg1
        assert BatchRenameDialog._instance is dlg2
        assert len(dlg2._paths) == 1
        dlg2.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_clears_singleton(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog.open(tmp_files)
        dlg.close()
        qtbot.waitUntil(lambda: BatchRenameDialog._instance is None, timeout=1000)

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_modeless_window_flags(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog.open(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert dlg.windowFlags() & Qt.Tool
        dlg.close()


class TestDialogInit:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_tables_visible_on_init(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert not dlg._preview_frame.isHidden()
        assert not dlg._seg_frame.isHidden()
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_data_ready_refreshes_preview(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._on_data_ready({})
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg.close()


class TestFileExistenceCheck:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_refresh_no_missing_without_os_check(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        tmp_files[1].unlink()
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) > 0, timeout=5000)
        assert all(not r.missing for r in dlg._results)
        dlg.close()


class TestExecuteChecksExistence:

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.warning')
    def test_execute_recheck_missing(self, mock_warn, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        results, _ = RenameEngine.preview(
            tmp_files,
            dlg._columns,
            dlg._ext_column,
            {},
        )
        dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (0, 0, 0))
        tmp_files[0].unlink()
        dlg._execute()
        mock_warn.assert_called_once()
        assert 'no longer exist' in mock_warn.call_args[0][2]
        dlg.close()


class TestFetchMetadataSync:

    def test_no_db(self):
        assert _fetch_metadata_sync(None, ['a.jpg']) == {}

    def test_missing_db(self):
        assert _fetch_metadata_sync('/nonexistent/db.sqlite', ['a.jpg']) == {}





class TestSerialiseColumns:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_serialise_has_source_defaults(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        state = dlg._serialise_columns()
        assert 'source_defaults' in state
        assert 'name' in state['source_defaults']
        assert 'ext' in state['source_defaults']
        assert 'columns' not in state
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_serialise_captures_source_settings(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._columns.append(RenameColumn(SequentialSource(start=5, padding=4)))
        state = dlg._serialise_columns()
        assert state['source_defaults']['seq']['start'] == 5
        assert state['source_defaults']['seq']['padding'] == 4
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_overrides_stripped_from_fixed(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        fixed = FixedSource(text='hello')
        fixed.overrides = {'a.jpg': 'custom'}
        dlg._columns = [RenameColumn(fixed)]
        state = dlg._serialise_columns()
        assert 'overrides' not in state['source_defaults']['fixed']
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_post_process_not_serialised(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._columns[0].post.prefix = 'X_'
        dlg._ext_column.post.case_mode = 'lower'
        state = dlg._serialise_columns()
        assert 'ext_post' not in state
        assert 'columns' not in state
        dlg.close()


class TestColumnRestore:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_always_starts_with_name_column(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'source_defaults': {
                'seq': {'type': 'seq', 'start': 10, 'step': 2, 'padding': 5},
            },
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_post_process_always_clean(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'source_defaults': {'name': {'type': 'name'}},
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert dlg._columns[0].post.prefix == ''
        assert dlg._columns[0].post.suffix == ''
        assert dlg._columns[0].post.case_mode == ''
        assert dlg._ext_column.post.prefix == ''
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_source_defaults_applied_on_add_column(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'source_defaults': {
                'seq': {'type': 'seq', 'start': 10, 'step': 2, 'padding': 5},
            },
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._add_column(SequentialSource)
        seq_col = dlg._columns[-1]
        assert isinstance(seq_col.source, SequentialSource)
        assert seq_col.source.start == 10
        assert seq_col.source.step == 2
        assert seq_col.source.padding == 5
        assert seq_col.post.prefix == ''
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_add_column_without_defaults_uses_source_default(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {}
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._add_column(SequentialSource)
        seq_col = dlg._columns[-1]
        assert seq_col.source.start == 1
        assert seq_col.source.padding == 3
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_empty_state_uses_defaults(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {}
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_saves_source_defaults(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._columns.append(RenameColumn(FixedSource(text='test')))
        dlg.close()
        state = BatchRenameDialog._saved_state
        assert 'source_defaults' in state
        assert state['source_defaults']['fixed']['text'] == 'test'

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_always_saves_state(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.close()
        assert 'source_defaults' in BatchRenameDialog._saved_state

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_ext_column_always_reset(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'source_defaults': {'ext': {'type': 'ext', 'mode': 'custom', 'custom': 'webp'}},
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert dlg._ext_column.source.mode == 'keep'
        assert dlg._ext_column.enabled is True
        dlg.close()


class TestStateStoreIntegration:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_registers_with_state_store(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        store = StateStore.instance()
        assert 'batch_rename' in store._entries
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_state_store_save_returns_saved_state(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._init_done = True
        dlg.close()
        store = StateStore.instance()
        all_states = store.save_all()
        assert 'batch_rename' in all_states
        assert 'source_defaults' in all_states['batch_rename']

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_state_store_deferred_restore(self, mock_init, qtbot, tmp_files):
        store = StateStore.instance()
        store.restore_all({
            'batch_rename': {
                'source_defaults': {
                    'seq': {'type': 'seq', 'start': 7, 'step': 1, 'padding': 4},
                },
            }
        })
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        dlg._add_column(SequentialSource)
        assert dlg._columns[-1].source.start == 7
        dlg.close()


from wafer.core.platform.file_operations import OperationResult


def _ok_result(src='', dst=''):
    return OperationResult(action="move", src=str(src), dst=str(dst), status="ok")


def _err_result(src='', error='error'):
    return OperationResult(action="move", src=str(src), dst="", status="error", error=error)


class TestRenameExecution:

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_rename_calls_execute_plans(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        mock_execute.assert_called_once()
        plans = mock_execute.call_args[1]['plans']
        assert len(plans) == 1
        assert plans[0].action == 'cut'
        assert not plans[0].conflict
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_rename_multiple_files(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        new_b = tmp_files[1].parent / 'y.jpg'
        new_c = tmp_files[2].parent / 'z.jpg'
        mock_execute.return_value = [
            _ok_result(tmp_files[0], new_a),
            _ok_result(tmp_files[1], new_b),
            _ok_result(tmp_files[2], new_c),
        ]

        rename_map = {
            str(tmp_files[0]): str(new_a),
            str(tmp_files[1]): str(new_b),
            str(tmp_files[2]): str(new_c),
        }
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        plans = mock_execute.call_args[1]['plans']
        assert len(plans) == 3
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.warning')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_failed_rename_shows_error_detail(self, mock_execute, mock_warn, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], 'permission denied')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        dlg._do_rename(rename_map)
        mock_warn.assert_called_once()
        msg = mock_warn.call_args[0][2]
        assert 'failed' in msg
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_overwrite_mode_is_overwrite(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert mock_execute.call_args[1]['overwrite_mode'] == 'overwrite'
        dlg.close()


class TestCloseProtection:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_always_allowed(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.close()
        assert not dlg.isVisible()


class TestRenameStaysOpen:

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_dialog_stays_open_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.show()

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg.isVisible()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_paths_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg._paths[0] == new_a
        assert dlg._paths[1] == tmp_files[1]
        assert dlg._paths[2] == tmp_files[2]
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_keys_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg._keys[0] == str(new_a).replace('\\', '/')
        assert dlg._initial_keys[0] == str(new_a).replace('\\', '/')
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_initial_paths_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg._initial_paths[0] == new_a
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_metadata_keys_remapped(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        old_key = str(tmp_files[0]).replace('\\', '/')
        dlg._metadata = {old_key: {'tag': 'val'}}

        new_a = tmp_files[0].parent / 'x.jpg'
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        new_key = str(new_a).replace('\\', '/')
        assert new_key in dlg._metadata
        assert old_key not in dlg._metadata
        assert dlg._metadata[new_key] == {'tag': 'val'}
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_thumb_cache_cleared(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        dlg._thumb_cache['fake'] = MagicMock()
        dlg._thumb_visible.add(0)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert len(dlg._thumb_cache) == 0
        assert len(dlg._thumb_visible) == 0
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_failed_files_keep_old_path(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / 'x.jpg'
        new_b = tmp_files[1].parent / 'y.jpg'
        mock_execute.return_value = [
            _ok_result(tmp_files[0], new_a),
            _err_result(tmp_files[1], 'fail'),
        ]

        rename_map = {
            str(tmp_files[0]): str(new_a),
            str(tmp_files[1]): str(new_b),
        }
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg._paths[0] == new_a
        assert dlg._paths[1] == tmp_files[1]
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_rebuild_called_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_rebuild') as mock_rebuild:
            dlg._do_rename(rename_map)
            mock_rebuild.assert_called_once()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_status_shows_result(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert 'Renamed 1 file(s)' in dlg._status.text()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_columns_reset_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        dlg._columns.append(RenameColumn(FixedSource()))
        dlg._sort_indicator = ('segment', 0, True)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_rebuild'):
            dlg._do_rename(rename_map)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        assert isinstance(dlg._ext_column.source, ExtSource)
        assert dlg._sort_indicator is None
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_reset_preserves_source_defaults(self, mock_execute, mock_init, qtbot, tmp_files):
        from wafer.builtins.rename_sources import RandomSource
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        rand_src = RandomSource(chars='hex', length=12)
        dlg._columns.append(RenameColumn(rand_src))
        ext_src = dlg._ext_column.source
        ext_src.mode = 'lower'
        dlg._update_source_defaults()

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_rebuild'):
            dlg._do_rename(rename_map)
        assert dlg._source_defaults.get('random', {}).get('chars') == 'hex'
        assert dlg._source_defaults.get('random', {}).get('length') == 12
        assert dlg._ext_column.source.mode == 'lower'
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.information')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_msgbox_shown_on_success(self, mock_execute, mock_msgbox, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_rebuild'):
            dlg._do_rename(rename_map)
        mock_msgbox.assert_called_once()
        assert '1 file(s) renamed' in mock_msgbox.call_args[0][2]
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.QtWidgets.QMessageBox.warning')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_msgbox_shown_on_all_failed(self, mock_execute, mock_msgbox, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], 'denied')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        dlg._do_rename(rename_map)
        mock_msgbox.assert_called_once()
        assert 'failed' in mock_msgbox.call_args[0][2]
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_all_failed_keeps_old_paths(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], 'denied')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        dlg._do_rename(rename_map)
        assert dlg._paths[0] == tmp_files[0]
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer.dialog.execute_paste_plans_with_ui')
    def test_rename_button_text_unchanged(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / 'x.jpg')]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        with patch.object(dlg, '_refresh'):
            dlg._do_rename(rename_map)
        assert dlg._rename_btn.text() == 'Rename'
        dlg.close()


class TestProgressiveThumbnailLoading:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_showEvent_triggers_thumb_update(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        with patch.object(dlg, '_update_visible_thumbnails') as mock_thumb:
            dlg._init_done = False
            dlg.showEvent(QtGui.QShowEvent())
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_thumbnail_loaded_updates_cache(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        key = str(tmp_files[0])
        img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
        dlg._on_thumbnail_loaded(key, img)
        assert key in dlg._thumb_cache
        assert not dlg._thumb_cache[key].isNull()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_thumbnail_null_image_stores_empty_pixmap(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        key = str(tmp_files[0])
        dlg._on_thumbnail_loaded(key, None)
        assert key in dlg._thumb_cache
        assert dlg._thumb_cache[key].isNull()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_thumbnail_loaded_after_row_excluded(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        excluded_key = str(tmp_files[1])
        dlg._exclude_row(1)
        img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
        dlg._on_thumbnail_loaded(excluded_key, img)
        assert excluded_key in dlg._thumb_cache
        assert len(dlg._paths) == 2
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_cancels_thumbnail_loading(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        token = CancelToken()
        dlg._thumb_tokens[0] = token
        assert not token.is_cancelled()
        dlg.close()
        assert token.is_cancelled()


class TestSegTableSelectionSync:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_seg_click_updates_selected_row(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._seg_table.selectRow(1)
        assert dlg._selected_row == 1
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_seg_selection_syncs_preview(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._seg_table.selectRow(2)
        preview_rows = dlg._preview.selectionModel().selectedRows()
        assert preview_rows and preview_rows[0].row() == 2
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_preview_selection_syncs_seg(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._preview.selectRow(0)
        seg_rows = dlg._seg_table.selectionModel().selectedRows()
        assert seg_rows and seg_rows[0].row() == 0
        dlg.close()


class TestStatusClickNavigation:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_scroll_to_next_issue_no_issues(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._scroll_to_next_issue()
        assert dlg._selected_row in (-1, 0, 1, 2)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_scroll_to_next_issue_finds_conflict(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        results = [
            RenameResult(original='a.jpg', segments=['a', '.jpg'], new_name='a.jpg'),
            RenameResult(original='b.jpg', segments=['b', '.jpg'], new_name='b.jpg', conflict=True),
            RenameResult(original='c.jpg', segments=['c', '.jpg'], new_name='c.jpg'),
        ]
        dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (1, 0, 0))
        dlg._selected_row = -1
        dlg._scroll_to_next_issue()
        assert dlg._selected_row == 1
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_scroll_wraps_around(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        results = [
            RenameResult(original='a.jpg', segments=['a', '.jpg'], new_name='a.jpg', conflict=True),
            RenameResult(original='b.jpg', segments=['b', '.jpg'], new_name='b.jpg'),
            RenameResult(original='c.jpg', segments=['c', '.jpg'], new_name='c.jpg'),
        ]
        dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (1, 0, 0))
        dlg._selected_row = 2
        dlg._scroll_to_next_issue()
        assert dlg._selected_row == 0
        dlg.close()


class TestOpacitySlider:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_slider_exists(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert hasattr(dlg, '_opacity_slider')
        assert dlg._opacity_slider.value() == 20
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_slider_changes_overlay_opacity(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._opacity_slider.setValue(50)
        assert abs(dlg._overlay._row_opacity - 0.5) < 0.01
        assert abs(dlg._overlay._sel_opacity - 0.5) < 0.01
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_slider_zero_opacity(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._opacity_slider.setValue(0)
        assert dlg._overlay._row_opacity == 0.0
        dlg.close()


class TestAllColumnsEditable:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_name_column_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        idx = dlg._seg_model.index(0, 0)
        flags = dlg._seg_model.flags(idx)
        assert flags & Qt.ItemIsEditable
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_ext_column_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        ext_sec = dlg._ext_section
        idx = dlg._seg_model.index(0, ext_sec)
        flags = dlg._seg_model.flags(idx)
        assert flags & Qt.ItemIsEditable
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_add_column_not_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        add_sec = dlg._add_section
        idx = dlg._seg_model.index(0, add_sec)
        flags = dlg._seg_model.flags(idx)
        assert not (flags & Qt.ItemIsEditable)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_edit_name_column_stores_override(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        with patch.object(dlg, '_refresh'):
            idx = dlg._seg_model.index(0, 0)
            dlg._seg_model.setData(idx, 'custom_name', Qt.EditRole)
            path_key = str(dlg._paths[0])
            assert path_key in dlg._columns[0].overrides
            assert dlg._columns[0].overrides[path_key] == 'custom_name'
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_edit_ext_column_stores_override(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        ext_sec = dlg._ext_section
        with patch.object(dlg, '_refresh'):
            idx = dlg._seg_model.index(0, ext_sec)
            dlg._seg_model.setData(idx, '.png', Qt.EditRole)
            path_key = str(dlg._paths[0])
            assert path_key in dlg._ext_column.overrides
            assert dlg._ext_column.overrides[path_key] == '.png'
        dlg.close()


class TestRenameColumnOverrides:

    def test_override_bypasses_source(self):
        col = RenameColumn(NameSource())
        segment = _make_segment(Path('test.jpg'))
        assert col.evaluate(segment) == 'test'
        col.overrides[str(segment.original_path)] = 'custom'
        assert col.evaluate(segment) == 'custom'

    def test_override_bypasses_post(self):
        col = RenameColumn(NameSource(), PostProcess(prefix='X_'))
        segment = _make_segment(Path('test.jpg'))
        assert col.evaluate(segment) == 'X_test'
        col.overrides[str(segment.original_path)] = 'raw'
        assert col.evaluate(segment) == 'raw'

    def test_no_override_uses_normal_path(self):
        col = RenameColumn(NameSource())
        segment = _make_segment(Path('hello.png'))
        assert col.evaluate(segment) == 'hello'


def _make_segment(path: Path):
    from wafer.plugin.rename.base import SegmentInfo
    return SegmentInfo(
        index=0, total=1, original_path=path,
        stem=path.stem, ext=path.suffix.lstrip('.'), metadata={},
    )


class TestSortIndicator:

    def test_preview_model_sort_indicator(self):
        from wafer.app.viewer.renamer.table import PreviewModel
        model = PreviewModel()
        assert model.headerData(0, Qt.Horizontal) == 'Original'
        assert model.headerData(1, Qt.Horizontal) == 'Result'
        model.set_sort_indicator(0)
        assert model.headerData(0, Qt.Horizontal) == 'Original \u25b2'
        assert model.headerData(1, Qt.Horizontal) == 'Result'
        model.set_sort_indicator(1)
        assert model.headerData(0, Qt.Horizontal) == 'Original'
        assert model.headerData(1, Qt.Horizontal) == 'Result \u25b2'
        model.set_sort_indicator(-1)
        assert model.headerData(0, Qt.Horizontal) == 'Original'
        assert model.headerData(1, Qt.Horizontal) == 'Result'

    def test_segment_model_sort_indicator(self):
        from wafer.app.viewer.renamer.table import SegmentModel
        model = SegmentModel()
        name_col = RenameColumn(NameSource())
        ext_col = RenameColumn(ExtSource())
        model.configure([name_col], ext_col, '+', '.ext')
        assert '\u25b2' not in model.headerData(0, Qt.Horizontal)
        assert '\u25bc' not in model.headerData(0, Qt.Horizontal)
        model.set_sort_indicator(0, True)
        assert '\u25b2' in model.headerData(0, Qt.Horizontal)
        model.set_sort_indicator(0, False)
        assert '\u25bc' in model.headerData(0, Qt.Horizontal)
        model.set_sort_indicator(-1)
        assert '\u25b2' not in model.headerData(0, Qt.Horizontal)
        assert '\u25bc' not in model.headerData(0, Qt.Horizontal)

    def test_segment_model_configure_clears_sort(self):
        from wafer.app.viewer.renamer.table import SegmentModel
        model = SegmentModel()
        name_col = RenameColumn(NameSource())
        ext_col = RenameColumn(ExtSource())
        model.configure([name_col], ext_col, '+', '.ext')
        model.set_sort_indicator(0, True)
        assert '\u25b2' in model.headerData(0, Qt.Horizontal)
        model.configure([name_col], ext_col, '+', '.ext')
        assert '\u25b2' not in model.headerData(0, Qt.Horizontal)

    def test_segment_ext_header_no_arrow(self):
        from wafer.app.viewer.renamer.table import SegmentModel
        model = SegmentModel()
        name_col = RenameColumn(NameSource())
        ext_col = RenameColumn(ExtSource())
        model.configure([name_col], ext_col, '+', '.ext')
        ext_header = model.headerData(2, Qt.Horizontal)
        assert '\u25bc' not in ext_header
        assert '\u25b2' not in ext_header

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_dialog_sort_indicator_on_preview_sort(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._results = [
            RenameResult(original=p.name, segments=[p.stem, p.suffix], new_name=p.name)
            for p in tmp_files
        ]
        dlg._on_preview_sort(0)
        assert dlg._sort_indicator == ('preview', 0, True)
        dlg._on_preview_sort(1)
        assert dlg._sort_indicator == ('preview', 1, True)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_dialog_sort_indicator_on_segment_sort(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._results = [
            RenameResult(original=p.name, segments=[p.stem, p.suffix], new_name=p.name)
            for p in tmp_files
        ]
        dlg._sort_by_segment(0, True)
        assert dlg._sort_indicator == ('segment', 0, True)
        dlg._sort_by_segment(0, False)
        assert dlg._sort_indicator == ('segment', 0, False)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_refresh_without_prepare_clears_sort(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._sort_indicator = ('preview', 0, True)
        dlg._refresh()
        assert dlg._sort_indicator is None
        dlg.close()


class TestThumbCacheLRU:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_cache_is_ordered_dict(self, mock_init, qtbot, tmp_files):
        import collections
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert isinstance(dlg._thumb_cache, collections.OrderedDict)
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_cache_evicts_beyond_limit(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.THUMB_CACHE_LIMIT = 5
        img = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
        for i in range(10):
            dlg._on_thumbnail_loaded(f'key_{i}', img)
        assert len(dlg._thumb_cache) == 5
        assert 'key_0' not in dlg._thumb_cache
        assert 'key_9' in dlg._thumb_cache
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_thumb_for_row_refreshes_lru(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.THUMB_CACHE_LIMIT = 3
        img = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
        for p in tmp_files:
            dlg._on_thumbnail_loaded(str(p), img)
        assert len(dlg._thumb_cache) == 3
        dlg.thumb_for_row(0)
        first_key = str(tmp_files[0])
        keys = list(dlg._thumb_cache.keys())
        assert keys[-1] == first_key
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_cache_limit_default(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert dlg.THUMB_CACHE_LIMIT == 200
        dlg.close()

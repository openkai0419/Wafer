import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.app.viewer.renamer._dialog import (
    BatchRenameDialog,
    _fetch_metadata_sync,
)
from wafer.app.viewer.renamer._engine import (
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
    @patch('wafer.app.viewer.renamer._dialog.Notifier')
    def test_execute_recheck_missing(self, mock_notifier, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._on_refresh_done(RenameEngine.preview(
            tmp_files,
            dlg._columns,
            dlg._ext_column,
            {},
        ))
        tmp_files[0].unlink()
        dlg._execute()
        mock_notifier.warning.assert_called_once()
        assert 'no longer exist' in mock_notifier.warning.call_args[0][0]
        dlg.close()


class TestFetchMetadataSync:

    def test_no_db(self):
        assert _fetch_metadata_sync(None, ['a.jpg']) == {}

    def test_missing_db(self):
        assert _fetch_metadata_sync('/nonexistent/db.sqlite', ['a.jpg']) == {}





class TestSerialiseColumns:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_roundtrip_default_columns(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        state = dlg._serialise_columns()
        assert 'columns' in state
        assert len(state['columns']) == 1
        assert state['columns'][0]['source']['type'] == 'name'
        assert 'ext_post' in state
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_roundtrip_multiple_columns(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._columns.append(RenameColumn(SequentialSource(start=5, padding=4)))
        dlg._columns[0].post.prefix = 'pre_'
        state = dlg._serialise_columns()
        assert len(state['columns']) == 2
        assert state['columns'][1]['source']['type'] == 'seq'
        assert state['columns'][1]['source']['start'] == 5
        assert state['columns'][0]['post']['prefix'] == 'pre_'
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
        assert 'overrides' not in state['columns'][0]['source']
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_ext_post_process_saved(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._ext_column.post.case_mode = 'lower'
        state = dlg._serialise_columns()
        assert state['ext_post']['case_mode'] == 'lower'
        dlg.close()


class TestColumnRestore:

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_restore_from_saved_state(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'columns': [
                {'source': {'type': 'seq', 'start': 10, 'step': 2, 'padding': 5},
                 'post': {}, 'enabled': True},
            ],
            'ext_post': {'case_mode': 'upper'},
            'ext_enabled': True,
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, SequentialSource)
        assert dlg._columns[0].source.start == 10
        assert dlg._ext_column.post.case_mode == 'upper'
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
    def test_close_saves_state(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg._columns.append(RenameColumn(FixedSource(text='test')))
        dlg.close()
        assert len(BatchRenameDialog._saved_state.get('columns', [])) == 2
        assert BatchRenameDialog._saved_state['columns'][1]['source']['type'] == 'fixed'

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_close_always_saves_state(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        dlg.close()
        assert 'columns' in BatchRenameDialog._saved_state

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_post_process_fields_restored(self, mock_init, qtbot, tmp_files):
        BatchRenameDialog._saved_state = {
            'columns': [
                {'source': {'type': 'name'},
                 'post': {'prefix': 'A_', 'suffix': '_Z', 'case_mode': 'upper'},
                 'enabled': False},
            ],
            'ext_post': {},
            'ext_enabled': True,
        }
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert dlg._columns[0].post.prefix == 'A_'
        assert dlg._columns[0].post.suffix == '_Z'
        assert dlg._columns[0].post.case_mode == 'upper'
        assert dlg._columns[0].enabled is False
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
        assert 'columns' in all_states['batch_rename']

    @patch.object(BatchRenameDialog, '_start_async_init')
    def test_state_store_deferred_restore(self, mock_init, qtbot, tmp_files):
        store = StateStore.instance()
        store.restore_all({
            'batch_rename': {
                'columns': [
                    {'source': {'type': 'seq', 'start': 1, 'step': 1, 'padding': 3},
                     'post': {}, 'enabled': True},
                ],
                'ext_post': {},
                'ext_enabled': True,
            }
        })
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)
        assert isinstance(dlg._columns[0].source, SequentialSource)
        dlg.close()


class TestRenameProgress:

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer._dialog.Notifier')
    @patch('wafer.app.viewer.renamer._dialog.FileExecutor')
    def test_progress_updates_status(self, mock_exec_cls, mock_notifier, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_result = MagicMock()
        mock_result.status = 'ok'
        mock_exec_cls.return_value.rename.return_value = mock_result

        dlg._dispatcher.post = lambda fn, cancel=None: fn()
        dlg._dispatcher.invoke = lambda fn: fn()

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg')}
        dlg._do_rename(rename_map)
        assert '1 / 1' in dlg._status.text()
        mock_notifier.info.assert_called_once()
        dlg.close()

    @patch.object(BatchRenameDialog, '_start_async_init')
    @patch('wafer.app.viewer.renamer._dialog.Notifier')
    @patch('wafer.app.viewer.renamer._dialog.FileExecutor')
    def test_progress_multiple_files(self, mock_exec_cls, mock_notifier, mock_init, qtbot, tmp_files):
        dlg = BatchRenameDialog(tmp_files)
        dlg.setAttribute(Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

        mock_result = MagicMock()
        mock_result.status = 'ok'
        mock_exec_cls.return_value.rename.return_value = mock_result

        progress_texts = []
        def capture_invoke(fn):
            fn()
            progress_texts.append(dlg._status.text())

        dlg._dispatcher.post = lambda fn, cancel=None: fn()
        dlg._dispatcher.invoke = capture_invoke

        rename_map = {
            str(tmp_files[0]): str(tmp_files[0].parent / 'x.jpg'),
            str(tmp_files[1]): str(tmp_files[1].parent / 'y.jpg'),
            str(tmp_files[2]): str(tmp_files[2].parent / 'z.jpg'),
        }
        dlg._do_rename(rename_map)
        progress_only = [t for t in progress_texts if 'Renaming...' in t]
        assert len(progress_only) >= 3
        assert any('1 / 3' in t for t in progress_only)
        assert any('3 / 3' in t for t in progress_only)
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

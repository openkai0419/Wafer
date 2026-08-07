import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from PySide6 import QtCore, QtGui, QtWidgets
from PySide6.QtCore import Qt

from wafer.builtins.batch_renamer.widget import (
    BatchRenameWidget,
    _fetch_metadata_sync,
    _fill_fs_timestamps,
)
from wafer.builtins.batch_renamer.engine import (
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
from wafer.builtins.batch_renamer.widget import BatchRenamerPlugin
from wafer.core.qt.dispatcher import CancelToken
from wafer.core.db.file_db import FileDB
from wafer.utils.formatting import dpix


@pytest.fixture(autouse=True)
def _reset_state():
    BatchRenameWidget._saved_state = {}
    BatchRenameWidget._instance_ref = None
    yield
    BatchRenameWidget._saved_state = {}
    BatchRenameWidget._instance_ref = None


@pytest.fixture(autouse=True)
def _suppress_msgbox():
    with patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.information"), patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.warning"):
        yield


@pytest.fixture
def tmp_files(tmp_path):
    files = []
    for name in ["a.jpg", "b.jpg", "c.jpg"]:
        f = tmp_path / name
        f.write_bytes(b"\x00" * 16)
        files.append(f)
    return files


class TestRenameResultMissing:
    def test_missing_default_false(self):
        r = RenameResult(original="a.jpg", segments=["a", ".jpg"], new_name="a.jpg")
        assert r.missing is False

    def test_missing_flag(self):
        r = RenameResult(original="a.jpg", segments=[], new_name="a.jpg", missing=True)
        assert r.missing is True


class TestWidgetInit:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_tables_visible_on_init(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert not dlg._preview_frame.isHidden()
        assert not dlg._seg_frame.isHidden()
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_data_ready_refreshes_preview(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._on_data_ready({})
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg.close()


class TestFileExistenceCheck:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_refresh_no_missing_without_os_check(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        tmp_files[1].unlink()
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) > 0, timeout=5000)
        assert all(not r.missing for r in dlg._results)
        dlg.close()


class TestExecuteChecksExistence:
    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.warning")
    def test_execute_recheck_missing(self, mock_warn, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
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
        assert "no longer exist" in mock_warn.call_args[0][2]
        dlg.close()


class TestFetchMetadataSync:
    def test_no_db(self):
        assert _fetch_metadata_sync(None, ["a.jpg"]) == {}

    def test_missing_db(self):
        assert _fetch_metadata_sync("/nonexistent/db.sqlite", ["a.jpg"]) == {}

    def test_fetches_standard_and_custom_metadata(self, tmp_path):
        db_path = tmp_path / "rename.db"
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        db.upsert_batches(
            [("c:/a.jpg", "hash-a", 2048, 1700000000.0, 1600000000.0, 1800000000.0)],
            [("c:/a.jpg", "c:/a.jpg", "actual.jpg", 1.0, None)],
            [("c:/a.jpg", "name", "stale-meta-name", None), ("c:/a.jpg", "exif.width", "100", 100.0)],
            [("hash-a", "rating", "5", 5.0)],
        )
        db.close()

        meta = _fetch_metadata_sync(db_path, ["c:/a.jpg"])["c:/a.jpg"]

        assert meta["path"] == "c:/a.jpg"
        assert meta["name"] == "actual.jpg"
        assert meta["size"] == "2048"
        assert meta["modified"] == "1700000000.0"
        assert meta["created"] == "1600000000.0"
        assert meta["collected"] == "1800000000.0"
        assert meta["exif.width"] == "100"
        assert meta["rating"] == "5"

    def test_fetch_skips_null_standard_source_values(self, tmp_path):
        db_path = tmp_path / "rename.db"
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        db.upsert_batches(
            [("c:/b.jpg", "hash-b", None, None, None, None)],
            [("c:/b.jpg", "c:/b.jpg", "b.jpg", 1.0, None)],
            [],
            [],
        )
        db.close()

        meta = _fetch_metadata_sync(db_path, ["c:/b.jpg"])["c:/b.jpg"]

        assert meta["path"] == "c:/b.jpg"
        assert meta["name"] == "b.jpg"
        assert "size" not in meta
        assert "modified" not in meta
        assert "created" not in meta
        assert "collected" not in meta


class TestFillFsTimestamps:
    def test_fills_missing_timestamps(self, tmp_path):
        f = tmp_path / "a.txt"
        f.write_text("hello")
        st = os.stat(f)
        metadata: dict[str, dict[str, str]] = {}
        key = str(f).replace("\\", "/")
        _fill_fs_timestamps([f], [key], metadata)
        assert key in metadata
        assert float(metadata[key]["modified"]) == pytest.approx(st.st_mtime, abs=1)
        assert float(metadata[key]["created"]) == pytest.approx(st.st_ctime, abs=1)

    def test_skips_when_both_present(self, tmp_path):
        f = tmp_path / "b.txt"
        f.write_text("hello")
        key = str(f).replace("\\", "/")
        metadata = {key: {"modified": "1000", "created": "2000"}}
        _fill_fs_timestamps([f], [key], metadata)
        assert metadata[key]["modified"] == "1000"
        assert metadata[key]["created"] == "2000"

    def test_fills_only_missing_keys(self, tmp_path):
        f = tmp_path / "c.txt"
        f.write_text("hello")
        st = os.stat(f)
        key = str(f).replace("\\", "/")
        metadata = {key: {"modified": "1000"}}
        _fill_fs_timestamps([f], [key], metadata)
        assert metadata[key]["modified"] == "1000"
        assert float(metadata[key]["created"]) == pytest.approx(st.st_ctime, abs=1)

    def test_skips_nonexistent_file(self):
        key = "Z:/no/such/file.txt"
        metadata: dict[str, dict[str, str]] = {}
        _fill_fs_timestamps([Path(key)], [key], metadata)
        assert metadata == {}


class TestSerialiseColumns:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_serialise_has_source_defaults(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        state = dlg._serialise_columns()
        assert "source_defaults" in state
        assert "name" in state["source_defaults"]
        assert "ext" in state["source_defaults"]
        assert "columns" not in state
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_serialise_captures_source_settings(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._columns.append(RenameColumn(SequentialSource(start=5, padding=4)))
        state = dlg._serialise_columns()
        assert state["source_defaults"]["seq"]["start"] == 5
        assert state["source_defaults"]["seq"]["padding"] == 4
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_overrides_stripped_from_fixed(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        fixed = FixedSource(text="hello")
        fixed.overrides = {"a.jpg": "custom"}
        dlg._columns = [RenameColumn(fixed)]
        state = dlg._serialise_columns()
        assert "overrides" not in state["source_defaults"]["fixed"]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_post_process_not_serialised(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._columns[0].post.prefix = "X_"
        dlg._ext_column.post.case_mode = "lower"
        state = dlg._serialise_columns()
        assert "ext_post" not in state
        assert "columns" not in state
        dlg.close()


class TestColumnRestore:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_always_starts_with_name_column(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {
            "source_defaults": {
                "seq": {"type": "seq", "start": 10, "step": 2, "padding": 5},
            },
        }
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_post_process_always_clean(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {
            "source_defaults": {"name": {"type": "name"}},
        }
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._columns[0].post.prefix == ""
        assert dlg._columns[0].post.suffix == ""
        assert dlg._columns[0].post.case_mode == ""
        assert dlg._ext_column.post.prefix == ""
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_source_defaults_applied_on_add_column(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {
            "source_defaults": {
                "seq": {"type": "seq", "start": 10, "step": 2, "padding": 5},
            },
        }
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._add_column(SequentialSource)
        seq_col = dlg._columns[-1]
        assert isinstance(seq_col.source, SequentialSource)
        assert seq_col.source.start == 10
        assert seq_col.source.step == 2
        assert seq_col.source.padding == 5
        assert seq_col.post.prefix == ""
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_add_column_without_defaults_uses_source_default(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {}
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._add_column(SequentialSource)
        seq_col = dlg._columns[-1]
        assert seq_col.source.start == 1
        assert seq_col.source.padding == 3
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_empty_state_uses_defaults(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {}
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_hide_saves_source_defaults(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.show()
        dlg.set_files(tmp_files)
        dlg._columns.append(RenameColumn(FixedSource(text="test")))
        dlg.hide()
        state = BatchRenameWidget._saved_state
        assert "source_defaults" in state
        assert state["source_defaults"]["fixed"]["text"] == "test"

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_hide_always_saves_state(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.show()
        dlg.set_files(tmp_files)
        dlg.hide()
        assert "source_defaults" in BatchRenameWidget._saved_state

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_ext_column_always_reset(self, mock_init, qtbot, tmp_files):
        BatchRenameWidget._saved_state = {
            "source_defaults": {"ext": {"type": "ext", "mode": "custom", "custom": "webp"}},
        }
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._ext_column.source.mode == "keep"
        assert dlg._ext_column.enabled is True
        dlg.close()


class TestPluginStateIntegration:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_plugin_save_state_delegates_to_widget(self, mock_init, qtbot, tmp_files):
        plugin = BatchRenamerPlugin()
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        widget.set_files(tmp_files)
        widget.show()
        widget.hide()
        state = plugin.save_ui_state()
        assert "source_defaults" in state
        widget.close()

    def test_plugin_restore_state_sets_widget_saved_state(self):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"source_defaults": {"seq": {"type": "seq", "start": 7}}})
        assert BatchRenameWidget._saved_state == {"source_defaults": {"seq": {"type": "seq", "start": 7}}}

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_plugin_restore_then_create_widget(self, mock_init, qtbot, tmp_files):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state(
            {
                "source_defaults": {
                    "seq": {"type": "seq", "start": 7, "step": 1, "padding": 4},
                },
            }
        )
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        widget.set_files(tmp_files)
        assert len(widget._columns) == 1
        assert isinstance(widget._columns[0].source, NameSource)
        widget._add_column(SequentialSource)
        assert widget._columns[-1].source.start == 7
        widget.close()

    def test_plugin_save_state_returns_cached_when_no_widget(self):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"row_opacity": 50})
        assert plugin.save_ui_state() == {"row_opacity": 50}

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_plugin_restore_reapplies_to_live_widget(self, mock_init, qtbot):
        plugin = BatchRenamerPlugin()
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._thumb_resolution == 512
        plugin.restore_ui_state({"thumb_resolution": 256, "row_opacity": 40, "outer_dir": "TB"})
        assert widget._thumb_resolution == 256
        assert widget._row_opacity_slider.value() == 40
        assert widget._split.direction == "TB"
        widget.close()

    def test_plugin_restore_legacy_thumb_fit_mode(self, qtbot):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"thumb_fit_mode": "contain"})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._row_thumb_fit_mode == "contain"
        assert widget._sel_thumb_fit_mode == "contain"
        assert widget._overlay.row_fit_mode == "contain"
        assert widget._overlay.sel_fit_mode == "contain"
        widget.close()

    def test_plugin_restore_separate_thumb_fit_modes(self, qtbot):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"row_thumb_fit_mode": "contain", "sel_thumb_fit_mode": "cover"})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._row_thumb_fit_mode == "contain"
        assert widget._sel_thumb_fit_mode == "cover"
        assert widget._overlay.row_fit_mode == "contain"
        assert widget._overlay.sel_fit_mode == "cover"
        widget.close()


from wafer.core.platform.file_operations import OperationResult


def _ok_result(src="", dst=""):
    return OperationResult(action="move", src=str(src), dst=str(dst), status="ok")


def _err_result(src="", error="error"):
    return OperationResult(action="move", src=str(src), dst="", status="error", error=error)


class TestRenameExecution:
    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_rename_calls_execute_plans(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        mock_execute.assert_called_once()
        plans = mock_execute.call_args[1]["plans"]
        assert len(plans) == 1
        assert plans[0].action == "cut"
        assert not plans[0].conflict
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_rename_multiple_files(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        new_b = tmp_files[1].parent / "y.jpg"
        new_c = tmp_files[2].parent / "z.jpg"
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
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        plans = mock_execute.call_args[1]["plans"]
        assert len(plans) == 3
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.warning")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_failed_rename_shows_error_detail(self, mock_execute, mock_warn, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], "permission denied")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        dlg._do_rename(rename_map)
        mock_warn.assert_called_once()
        msg = mock_warn.call_args[0][2]
        assert "failed" in msg
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_overwrite_mode_is_overwrite(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert mock_execute.call_args[1]["overwrite_mode"] == "overwrite"
        dlg.close()


class TestRenameStaysOpen:
    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_dialog_stays_open_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.show()

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg.isVisible()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_paths_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg._paths[0] == new_a
        assert dlg._paths[1] == tmp_files[1]
        assert dlg._paths[2] == tmp_files[2]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_keys_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg._keys[0] == str(new_a).replace("\\", "/")
        assert dlg._initial_keys[0] == str(new_a).replace("\\", "/")
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_initial_paths_updated_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg._initial_paths[0] == new_a
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_metadata_keys_remapped(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        old_key = str(tmp_files[0]).replace("\\", "/")
        dlg._metadata = {old_key: {"tag": "val"}}

        new_a = tmp_files[0].parent / "x.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        new_key = str(new_a).replace("\\", "/")
        assert new_key in dlg._metadata
        assert old_key not in dlg._metadata
        assert dlg._metadata[new_key] == {"tag": "val"}
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_thumb_cache_cleared(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        dlg._thumb_cache["fake"] = MagicMock()
        dlg._thumb_visible.add(0)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert len(dlg._thumb_cache) == 0
        assert len(dlg._thumb_visible) == 0
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_failed_files_keep_old_path(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        new_a = tmp_files[0].parent / "x.jpg"
        new_b = tmp_files[1].parent / "y.jpg"
        mock_execute.return_value = [
            _ok_result(tmp_files[0], new_a),
            _err_result(tmp_files[1], "fail"),
        ]

        rename_map = {
            str(tmp_files[0]): str(new_a),
            str(tmp_files[1]): str(new_b),
        }
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg._paths[0] == new_a
        assert dlg._paths[1] == tmp_files[1]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_rebuild_called_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_rebuild") as mock_rebuild:
            dlg._do_rename(rename_map)
            mock_rebuild.assert_called_once()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_status_shows_result(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert "Renamed 1 file(s)" in dlg._status.text()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_columns_reset_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        dlg._columns.append(RenameColumn(FixedSource()))

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_rebuild"):
            dlg._do_rename(rename_map)
        assert len(dlg._columns) == 1
        assert isinstance(dlg._columns[0].source, NameSource)
        assert isinstance(dlg._ext_column.source, ExtSource)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_order_preserved_after_rename(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)

        new_a = tmp_files[0].parent / "z.jpg"
        mock_execute.return_value = [_ok_result(tmp_files[0], new_a)]

        rename_map = {str(tmp_files[0]): str(new_a)}
        dlg._do_rename(rename_map)

        qtbot.waitUntil(lambda: [r.segments[0] for r in dlg._results] == ["z", "b", "c"], timeout=5000)
        assert [p.name for p in dlg._paths] == ["z.jpg", "b.jpg", "c.jpg"]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_reset_preserves_source_defaults(self, mock_execute, mock_init, qtbot, tmp_files):
        from wafer.builtins.rename_sources import RandomSource

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        rand_src = RandomSource(chars="hex", length=12)
        dlg._columns.append(RenameColumn(rand_src))
        ext_src = dlg._ext_column.source
        ext_src.mode = "lower"
        dlg._update_source_defaults()

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_rebuild"):
            dlg._do_rename(rename_map)
        assert dlg._source_defaults.get("random", {}).get("chars") == "hex"
        assert dlg._source_defaults.get("random", {}).get("length") == 12
        assert dlg._ext_column.source.mode == "lower"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.information")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_msgbox_shown_on_success(self, mock_execute, mock_msgbox, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_rebuild"):
            dlg._do_rename(rename_map)
        mock_msgbox.assert_called_once()
        assert "1 file(s) renamed" in mock_msgbox.call_args[0][2]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.QtWidgets.QMessageBox.warning")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_msgbox_shown_on_all_failed(self, mock_execute, mock_msgbox, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], "denied")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        dlg._do_rename(rename_map)
        mock_msgbox.assert_called_once()
        assert "failed" in mock_msgbox.call_args[0][2]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_all_failed_keeps_old_paths(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_err_result(tmp_files[0], "denied")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        dlg._do_rename(rename_map)
        assert dlg._paths[0] == tmp_files[0]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    @patch("wafer.builtins.batch_renamer.widget.execute_paste_plans_with_ui")
    def test_rename_button_text_unchanged(self, mock_execute, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)

        mock_execute.return_value = [_ok_result(tmp_files[0], tmp_files[0].parent / "x.jpg")]

        rename_map = {str(tmp_files[0]): str(tmp_files[0].parent / "x.jpg")}
        with patch.object(dlg, "_refresh"):
            dlg._do_rename(rename_map)
        assert dlg._rename_btn.text() == "Rename"
        dlg.close()


class TestProgressiveThumbnailLoading:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_set_files_triggers_thumb_update(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        with patch.object(dlg, "_update_visible_thumbnails") as mock_thumb:
            dlg.set_files(tmp_files)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumbnail_loaded_updates_cache(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        key = str(tmp_files[0])
        img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
        dlg._on_thumbnail_loaded(0, key, img)
        assert key in dlg._thumb_cache
        assert not dlg._thumb_cache[key].isNull()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumbnail_null_image_stores_empty_pixmap(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        key = str(tmp_files[0])
        dlg._on_thumbnail_loaded(0, key, None)
        assert key in dlg._thumb_cache
        assert dlg._thumb_cache[key].isNull()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumbnail_loaded_after_row_excluded(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        excluded_key = str(tmp_files[1])
        dlg._exclude_rows([1])
        img = QtGui.QImage(10, 10, QtGui.QImage.Format_RGB32)
        dlg._on_thumbnail_loaded(-1, excluded_key, img)
        assert excluded_key in dlg._thumb_cache
        assert len(dlg._paths) == 2
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_close_cancels_thumbnail_loading(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.show()
        dlg.set_files(tmp_files)
        token = CancelToken()
        dlg._thumb_tokens[0] = token
        assert not token.is_cancelled()
        dlg.close()
        assert token.is_cancelled()


class TestSegTableSelectionSync:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_seg_click_updates_selected_row(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        index = dlg._seg_model.index(1, 0)
        dlg._seg_table.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
        assert dlg._selected_row == 1
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_seg_selection_syncs_preview(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        index = dlg._seg_model.index(2, 0)
        dlg._seg_table.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
        preview_rows = {item.row() for item in dlg._orig_view.selectionModel().selectedIndexes()}
        assert preview_rows == {2}
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_preview_selection_syncs_seg(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        index = dlg._preview_model.index(0, 1)
        dlg._result_view.selectionModel().select(index, QtCore.QItemSelectionModel.ClearAndSelect)
        seg_rows = {item.row() for item in dlg._seg_table.selectionModel().selectedIndexes()}
        assert seg_rows == {0}
        dlg.close()


class TestStatusClickNavigation:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_scroll_to_next_issue_no_issues(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._scroll_to_next_issue()
        assert dlg._selected_row in (-1, 0, 1, 2)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_scroll_to_next_issue_finds_conflict(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        results = [
            RenameResult(original="a.jpg", segments=["a", ".jpg"], new_name="a.jpg"),
            RenameResult(original="b.jpg", segments=["b", ".jpg"], new_name="b.jpg", conflict=True),
            RenameResult(original="c.jpg", segments=["c", ".jpg"], new_name="c.jpg"),
        ]
        dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (1, 0, 0))
        dlg._selected_row = -1
        dlg._scroll_to_next_issue()
        assert dlg._selected_row == 1
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_scroll_wraps_around(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        results = [
            RenameResult(original="a.jpg", segments=["a", ".jpg"], new_name="a.jpg", conflict=True),
            RenameResult(original="b.jpg", segments=["b", ".jpg"], new_name="b.jpg"),
            RenameResult(original="c.jpg", segments=["c", ".jpg"], new_name="c.jpg"),
        ]
        dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (1, 0, 0))
        dlg._selected_row = 2
        dlg._scroll_to_next_issue()
        assert dlg._selected_row == 0
        dlg.close()


class TestOpacitySlider:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_row_slider_exists(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert hasattr(dlg, "_row_opacity_slider")
        assert hasattr(dlg, "_sel_opacity_slider")
        assert hasattr(dlg, "_row_thumb_fit_btn")
        assert hasattr(dlg, "_sel_thumb_fit_btn")
        assert dlg._row_opacity_slider.value() == 20
        assert dlg._sel_opacity_slider.value() == 20
        assert dlg._row_thumb_fit_btn.text() == ""
        assert dlg._sel_thumb_fit_btn.text() == ""
        assert dlg._row_thumb_fit_btn.iconSize() == QtCore.QSize(dpix(14), dpix(14))
        assert dlg._sel_thumb_fit_btn.iconSize() == QtCore.QSize(dpix(14), dpix(14))
        assert not dlg._row_thumb_fit_btn.icon().isNull()
        assert not dlg._sel_thumb_fit_btn.icon().isNull()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumb_fit_buttons_precede_opacity_sliders(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        grid = dlg._thumb_settings_content.layout()
        widgets = [grid.itemAt(i).widget() for i in range(grid.count()) if grid.itemAt(i).widget() is not None]
        assert widgets.index(dlg._row_thumb_fit_btn) < widgets.index(dlg._row_opacity_slider)
        assert widgets.index(dlg._sel_thumb_fit_btn) < widgets.index(dlg._sel_opacity_slider)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_controls_moved_out_of_bottom_bar(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        bar_widgets = [dlg._bottom_bar.itemAt(i).widget() for i in range(dlg._bottom_bar.count()) if dlg._bottom_bar.itemAt(i).widget() is not None]
        assert dlg._thumb_settings_btn in bar_widgets
        assert dlg._row_opacity_slider not in bar_widgets
        assert dlg._sel_opacity_slider not in bar_widgets
        assert dlg._row_thumb_fit_btn not in bar_widgets
        assert dlg._sel_thumb_fit_btn not in bar_widgets
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_gear_button_opens_and_closes_popup(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.show()
        assert dlg._thumb_settings_popup is None
        dlg._toggle_thumb_settings_popup()
        assert dlg._thumb_settings_popup is not None
        assert dlg._thumb_settings_popup.isVisible()
        assert dlg._thumb_settings_popup.content_widget() is dlg._thumb_settings_content
        dlg._toggle_thumb_settings_popup()
        assert not dlg._thumb_settings_popup.isVisible()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_row_slider_changes_row_opacity(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._row_opacity_slider.setValue(50)
        assert abs(dlg._overlay._row_opacity - 0.5) < 0.01
        assert abs(dlg._overlay._sel_opacity - 0.2) < 0.01
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sel_slider_changes_sel_opacity(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._sel_opacity_slider.setValue(70)
        assert abs(dlg._overlay._sel_opacity - 0.7) < 0.01
        assert abs(dlg._overlay._row_opacity - 0.2) < 0.01
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_slider_zero_opacity(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._row_opacity_slider.setValue(0)
        assert dlg._overlay._row_opacity == 0.0
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_row_thumb_fit_button_toggles_left_overlay_mode(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._overlay.row_fit_mode == "cover"
        assert dlg._overlay.sel_fit_mode == "cover"
        dlg._row_thumb_fit_btn.setChecked(True)
        assert dlg._row_thumb_fit_mode == "contain"
        assert dlg._sel_thumb_fit_mode == "cover"
        assert dlg._overlay.row_fit_mode == "contain"
        assert dlg._overlay.sel_fit_mode == "cover"
        dlg._row_thumb_fit_btn.setChecked(False)
        assert dlg._row_thumb_fit_mode == "cover"
        assert dlg._overlay.row_fit_mode == "cover"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sel_thumb_fit_button_toggles_right_overlay_mode(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._sel_thumb_fit_btn.setChecked(True)
        assert dlg._row_thumb_fit_mode == "cover"
        assert dlg._sel_thumb_fit_mode == "contain"
        assert dlg._overlay.row_fit_mode == "cover"
        assert dlg._overlay.sel_fit_mode == "contain"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumb_fit_mode_serialised(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._set_thumb_fit_mode("row", "contain")
        dlg._set_thumb_fit_mode("sel", "cover")
        state = dlg._serialise_columns()
        assert state["row_thumb_fit_mode"] == "contain"
        assert state["sel_thumb_fit_mode"] == "cover"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_preview_row_height_slider_defaults(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._preview_row_height_slider.value() == 0
        assert dlg._preview_row_height_slider.minimum() == 0
        assert dlg._preview_row_height_slider.maximum() == 200
        dlg.close()

    def test_preview_row_height_ratio_square_and_scaled(self, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg.resize(dpix(600), dpix(500))
        dlg.show()
        qtbot.waitExposed(dlg)
        w = dlg._orig_view.viewport().width()
        seg_h = dlg._seg_table.verticalHeader().defaultSectionSize()
        dlg._preview_row_height_slider.setValue(100)
        assert dlg._orig_view.verticalHeader().defaultSectionSize() == max(dpix(20), w)
        dlg._preview_row_height_slider.setValue(50)
        assert dlg._orig_view.verticalHeader().defaultSectionSize() == max(dpix(20), round(w * 0.5))
        dlg._preview_row_height_slider.setValue(200)
        assert dlg._orig_view.verticalHeader().defaultSectionSize() == max(dpix(20), round(w * 2.0))
        assert dlg._seg_table.verticalHeader().defaultSectionSize() == seg_h
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_preview_row_ratio_serialised(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._preview_row_height_slider.setValue(60)
        state = dlg._serialise_columns()
        assert state["preview_row_ratio"] == 60
        dlg.close()

    def test_preview_row_ratio_restored(self, qtbot):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"preview_row_ratio": 70})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._preview_row_height_slider.value() == 70
        widget.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_preview_views_stretch_single_column(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._orig_view.isColumnHidden(1)
        assert dlg._result_view.isColumnHidden(0)
        for view in (dlg._orig_view, dlg._result_view):
            assert view.horizontalHeader().sectionResizeMode(0) == QtWidgets.QHeaderView.Stretch
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_split_is_vertical_and_contains_frames(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._split.orientation() == Qt.Vertical
        assert dlg._split.indexOf(dlg._preview_frame) == 0
        assert dlg._split.indexOf(dlg._seg_frame) == 1
        assert dlg._bottom_bar.indexOf(dlg._rename_btn) >= 0
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_split_directions_serialised(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._set_split_direction("outer", "RL")
        dlg._set_split_direction("inner", "BT")
        state = dlg._serialise_columns()
        assert state["outer_dir"] == "RL"
        assert state["inner_dir"] == "BT"
        assert isinstance(state["outer_sizes"], list)
        assert isinstance(state["inner_sizes"], list)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_set_split_direction_changes_orientation(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._set_split_direction("outer", "LR")
        assert dlg._split.orientation() == Qt.Horizontal
        dlg._set_split_direction("inner", "TB")
        assert dlg._inner_split.orientation() == Qt.Vertical
        dlg.close()

    def test_scroll_anchor_skips_when_visible(self, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg.resize(dpix(600), dpix(500))
        dlg.show()
        qtbot.waitExposed(dlg)
        before = dlg._orig_view.verticalScrollBar().value()
        dlg._scroll_anchor_into_view(0)
        assert dlg._orig_view.verticalScrollBar().value() == before
        dlg.close()

    def test_split_sizes_restored(self, qtbot):
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"outer_dir": "TB", "outer_sizes": [dpix(300), dpix(100)]})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        widget._stack.setCurrentWidget(widget._rename_page)
        widget.resize(dpix(600), dpix(500))
        widget.show()
        qtbot.waitExposed(widget)
        assert widget._split.sizes()[0] > widget._split.sizes()[1]
        widget.close()

    def test_selection_anchor_prefers_current_index(self, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg._select_preview_rows([0, 1, 2], anchor=1)
        assert dlg._selection_anchor_row(dlg._orig_view) == 1
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_scroll_mode_per_item(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg._orig_view.verticalScrollMode() == QtWidgets.QAbstractItemView.ScrollPerPixel
        assert dlg._seg_table.verticalScrollMode() == QtWidgets.QAbstractItemView.ScrollPerItem
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_exclude_rows_batch(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._exclude_rows([0, 2])
        assert len(dlg._paths) == 1
        assert dlg._paths[0] == tmp_files[1]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_remove_files(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.remove_files([tmp_files[0], tmp_files[2]])
        assert len(dlg._paths) == 1
        assert dlg._paths[0] == tmp_files[1]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_remove_files_all_resets(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.remove_files(tmp_files)
        assert len(dlg._paths) == 0
        dlg.close()


class TestThumbnailFitMode:
    def test_cover_scales_outside_rect(self):
        from wafer.builtins.batch_renamer.overlay import ThumbnailOverlay

        pix = QtGui.QPixmap(100, 50)
        rect = QtCore.QRect(0, 0, 100, 100)
        target = ThumbnailOverlay._scaled_rect(pix, rect, "cover")
        assert target == QtCore.QRect(-50, 0, 200, 100)

    def test_contain_scales_inside_rect(self):
        from wafer.builtins.batch_renamer.overlay import ThumbnailOverlay

        pix = QtGui.QPixmap(100, 50)
        rect = QtCore.QRect(0, 0, 100, 100)
        target = ThumbnailOverlay._scaled_rect(pix, rect, "contain")
        assert target == QtCore.QRect(0, 25, 100, 50)


class TestAllColumnsEditable:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_name_column_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        idx = dlg._seg_model.index(0, 0)
        flags = dlg._seg_model.flags(idx)
        assert flags & Qt.ItemIsEditable
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_ext_column_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        ext_sec = dlg._ext_section
        idx = dlg._seg_model.index(0, ext_sec)
        flags = dlg._seg_model.flags(idx)
        assert flags & Qt.ItemIsEditable
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_add_column_not_editable(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        add_sec = dlg._add_section
        idx = dlg._seg_model.index(0, add_sec)
        flags = dlg._seg_model.flags(idx)
        assert not (flags & Qt.ItemIsEditable)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_edit_name_column_stores_override(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        with patch.object(dlg, "_refresh"):
            idx = dlg._seg_model.index(0, 0)
            dlg._seg_model.setData(idx, "custom_name", Qt.EditRole)
            path_key = str(dlg._paths[0])
            assert path_key in dlg._columns[0].overrides
            assert dlg._columns[0].overrides[path_key] == "custom_name"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_edit_ext_column_stores_override(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        ext_sec = dlg._ext_section
        with patch.object(dlg, "_refresh"):
            idx = dlg._seg_model.index(0, ext_sec)
            dlg._seg_model.setData(idx, ".png", Qt.EditRole)
            path_key = str(dlg._paths[0])
            assert path_key in dlg._ext_column.overrides
            assert dlg._ext_column.overrides[path_key] == ".png"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_restore_name_column_clears_override_and_recomputes_result(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)

        idx = dlg._seg_model.index(0, 0)
        path_key = str(dlg._paths[0])
        original = dlg._results[0].segments[0]

        dlg._seg_model.setData(idx, "custom_name", Qt.EditRole)
        qtbot.waitUntil(
            lambda: dlg._results[0].segments[0] == "custom_name" and dlg._columns[0].overrides.get(path_key) == "custom_name",
            timeout=5000,
        )

        dlg._restore_cell_override(path_key, 0)

        qtbot.waitUntil(
            lambda: path_key not in dlg._columns[0].overrides and dlg._results[0].segments[0] == original,
            timeout=5000,
        )
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_restore_ext_column_clears_override_and_refreshes(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)

        ext_sec = dlg._ext_section
        idx = dlg._seg_model.index(0, ext_sec)
        path_key = str(dlg._paths[0])

        with patch.object(dlg, "_refresh") as refresh:
            dlg._seg_model.setData(idx, ".png", Qt.EditRole)
            assert dlg._ext_column.overrides[path_key] == ".png"
            refresh.reset_mock()

            dlg._restore_cell_override(path_key, ext_sec)

            assert path_key not in dlg._ext_column.overrides
            refresh.assert_called_once_with(auto_size=False)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_restore_selected_overrides_clears_only_selected_cells(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)

        ext_sec = dlg._ext_section
        name_idx_0 = dlg._seg_model.index(0, 0)
        ext_idx_0 = dlg._seg_model.index(0, ext_sec)
        name_idx_1 = dlg._seg_model.index(1, 0)
        path_key_0 = str(dlg._paths[0])
        path_key_1 = str(dlg._paths[1])

        with patch.object(dlg, "_refresh") as refresh:
            dlg._seg_model.setData(name_idx_0, "custom_name", Qt.EditRole)
            dlg._seg_model.setData(ext_idx_0, ".png", Qt.EditRole)
            dlg._seg_model.setData(name_idx_1, "other_name", Qt.EditRole)
            refresh.reset_mock()

            sel = dlg._seg_table.selectionModel()
            sel.select(name_idx_0, QtCore.QItemSelectionModel.ClearAndSelect)
            sel.select(name_idx_1, QtCore.QItemSelectionModel.Select)

            dlg._restore_cell_overrides(dlg._selected_override_cells())

            assert path_key_0 not in dlg._columns[0].overrides
            assert path_key_1 not in dlg._columns[0].overrides
            assert dlg._ext_column.overrides[path_key_0] == ".png"
            refresh.assert_called_once_with(auto_size=False)
        dlg.close()


class TestSegmentEditingNavigation:
    def _prepare_dialog(self, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.resize(640, 480)
        dlg.set_files(tmp_files)
        dlg._columns.append(RenameColumn(FixedSource("fixed")))
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg.show()
        qtbot.waitExposed(dlg)
        return dlg

    def _open_editor(self, dlg, qtbot, row, column):
        index = dlg._seg_model.index(row, column)
        dlg._seg_table.setCurrentIndex(index)
        dlg._seg_table.setFocus()
        dlg._seg_table.edit(index)
        qtbot.waitUntil(dlg._seg_table.is_editing, timeout=3000)
        editor = dlg._seg_table.findChild(QtWidgets.QLineEdit)
        assert editor is not None
        return editor

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_enter_opens_current_editor(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            index = dlg._seg_model.index(0, 0)
            dlg._seg_table.setCurrentIndex(index)
            dlg._seg_table.setFocus()
            qtbot.keyClick(dlg._seg_table, Qt.Key_Return)
            qtbot.waitUntil(dlg._seg_table.is_editing, timeout=3000)
        finally:
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_f2_opens_current_editor(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            index = dlg._seg_model.index(0, 0)
            dlg._seg_table.setCurrentIndex(index)
            dlg._seg_table.setFocus()
            qtbot.keyClick(dlg._seg_table, Qt.Key_F2)
            qtbot.waitUntil(dlg._seg_table.is_editing, timeout=3000)
        finally:
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_enter_ignores_add_column(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            index = dlg._seg_model.index(0, dlg._add_section)
            dlg._seg_table.setCurrentIndex(index)
            dlg._seg_table.setFocus()
            qtbot.keyClick(dlg._seg_table, Qt.Key_Return)
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents)
            assert not dlg._seg_table.is_editing()
        finally:
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_tab_moves_to_next_row_same_column(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            fixed_col = 1
            editor = self._open_editor(dlg, qtbot, 0, fixed_col)
            editor.setFocus()
            qtbot.keyClick(editor, Qt.Key_Tab)

            qtbot.waitUntil(
                lambda: dlg._seg_table.currentIndex().row() == 1
                and dlg._seg_table.currentIndex().column() == fixed_col
                and dlg._seg_table.is_editing(),
                timeout=3000,
            )
        finally:
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_shift_tab_moves_to_previous_row_same_column(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            fixed_col = 1
            editor = self._open_editor(dlg, qtbot, 1, fixed_col)
            dlg._seg_table.closeEditor(editor, QtWidgets.QAbstractItemDelegate.EditPreviousItem)

            qtbot.waitUntil(
                lambda: dlg._seg_table.currentIndex().row() == 0
                and dlg._seg_table.currentIndex().column() == fixed_col
                and dlg._seg_table.is_editing(),
                timeout=3000,
            )
        finally:
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_tab_at_last_row_does_not_wrap(self, mock_init, qtbot, tmp_files):
        dlg = self._prepare_dialog(qtbot, tmp_files)
        try:
            fixed_col = 1
            editor = self._open_editor(dlg, qtbot, 2, fixed_col)
            dlg._seg_table.closeEditor(editor, QtWidgets.QAbstractItemDelegate.EditNextItem)

            qtbot.waitUntil(lambda: not dlg._seg_table.is_editing(), timeout=3000)
            assert dlg._seg_table.currentIndex().row() == 2
            assert dlg._seg_table.currentIndex().column() == fixed_col
        finally:
            dlg.close()


class TestScrollSync:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_preview_wheel_offsets_without_moving_seg(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        row_h = dlg._orig_view.verticalHeader().defaultSectionSize() or 1
        for view in (dlg._orig_view, dlg._result_view):
            view.verticalScrollBar().setRange(0, 1000)
        seg_before = dlg._seg_table.verticalScrollBar().value()
        dlg._orig_view.verticalScrollBar().setValue(row_h * 2)
        assert dlg._seg_table.verticalScrollBar().value() == seg_before
        assert dlg._result_view.verticalScrollBar().value() == row_h * 2
        assert dlg._display_offset == row_h * 2 - seg_before * row_h
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_seg_scroll_applies_offset_when_enabled(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        row_h = dlg._orig_view.verticalHeader().defaultSectionSize() or 1
        for view in (dlg._orig_view, dlg._result_view):
            view.verticalScrollBar().setRange(0, 1000)
        dlg._display_offset = 5
        dlg._sync_from_seg(1)
        expected = min(1 * row_h + 5, dlg._orig_view.verticalScrollBar().maximum())
        assert dlg._orig_view.verticalScrollBar().value() == expected
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sync_disabled_keeps_preview_independent(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._scroll_sync_check.setChecked(False)
        before = dlg._orig_view.verticalScrollBar().value()
        dlg._sync_from_seg(2)
        assert dlg._orig_view.verticalScrollBar().value() == before
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sync_disabled_selection_does_not_scroll(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._orig_view.verticalScrollBar().setRange(0, 1000)
        dlg._scroll_sync_check.setChecked(False)
        before = dlg._orig_view.verticalScrollBar().value()
        dlg._scroll_anchor_into_view(2)
        assert dlg._orig_view.verticalScrollBar().value() == before
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_scroll_sync_serialised_and_restored(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._scroll_sync_check.setChecked(False)
        assert dlg._serialise_columns()["scroll_sync_enabled"] is False
        dlg.close()
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"scroll_sync_enabled": False})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._scroll_sync_enabled is False
        widget.close()


class TestThumbnailResolution:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_resolution_change_clears_cache(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._thumb_cache[str(tmp_files[0])] = QtGui.QPixmap()
        dlg._thumb_res_slider.setValue(BatchRenameWidget.THUMB_RESOLUTIONS.index(1024))
        assert dlg._thumb_resolution == 1024
        assert len(dlg._thumb_cache) == 0
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_resolution_serialised_and_restored(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._thumb_res_slider.setValue(BatchRenameWidget.THUMB_RESOLUTIONS.index(2048))
        assert dlg._serialise_columns()["thumb_resolution"] == 2048
        dlg.close()
        plugin = BatchRenamerPlugin()
        plugin.restore_ui_state({"thumb_resolution": 256})
        widget = plugin.create_widget()
        qtbot.addWidget(widget)
        assert widget._thumb_resolution == 256
        widget.close()


class TestSegmentEditingDeferredUpdate:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_cancel_all_pending_clears_deferred_updates(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: True)

        assert dlg._defer_update_if_editing(lambda: None, kind="rebuild") is True
        assert dlg._defer_update_if_editing(lambda: None, kind="refresh") is True
        assert dlg._defer_update_if_editing(lambda: None, kind="apply") is True
        dlg._schedule_pending_update()

        dlg._cancel_all_pending()

        assert dlg._pending_rebuild_callback is None
        assert dlg._pending_refresh_callback is None
        assert dlg._pending_apply_callback is None
        assert dlg._pending_update_scheduled is False
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_refresh_defers_while_segment_editor_is_active(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        editing = {"value": True}
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])

        with patch.object(dlg._dispatcher, "post") as post:
            dlg._refresh(auto_size=False)
            post.assert_not_called()

            editing["value"] = False
            dlg._schedule_pending_update()
            qtbot.waitUntil(lambda: post.called, timeout=3000)

        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_deferred_refresh_disables_rename_and_blocks_execute(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3 and dlg._rename_btn.isEnabled(), timeout=5000)
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: True)

        dlg._seg_model.setData(dlg._seg_model.index(0, 0), "custom_name", Qt.EditRole)

        assert not dlg._rename_btn.isEnabled()
        assert dlg._pending_refresh_callback is not None
        with (
            patch.object(dlg, "_confirm_rename", return_value=True) as confirm,
            patch.object(dlg, "_do_rename") as do_rename,
        ):
            dlg._execute()
        confirm.assert_not_called()
        do_rename.assert_not_called()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_execute_while_editing_without_pending_queues_refresh(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3 and dlg._rename_btn.isEnabled(), timeout=5000)
        editing = {"value": True}
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])

        with patch.object(dlg._dispatcher, "post") as post:
            dlg._execute()
            assert not dlg._rename_btn.isEnabled()
            assert dlg._pending_refresh_callback is not None
            post.assert_not_called()

            editing["value"] = False
            dlg._schedule_pending_update()
            qtbot.waitUntil(lambda: post.called, timeout=3000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_pending_update_waits_for_editing_finished_without_reschedule_loop(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        editing = {"value": True}
        calls = []
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])

        assert dlg._defer_update_if_editing(lambda: calls.append("refresh"), kind="refresh") is True
        dlg._schedule_pending_update()
        qtbot.waitUntil(lambda: not dlg._pending_update_scheduled, timeout=3000)

        assert calls == []
        assert dlg._pending_refresh_callback is not None

        editing["value"] = False
        dlg._schedule_pending_update()
        qtbot.waitUntil(lambda: calls == ["refresh"], timeout=3000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_refresh_done_defers_model_reset_while_segment_editor_is_active(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        results = [RenameResult(original=p.name, segments=[p.stem, p.suffix], new_name=p.name) for p in tmp_files]
        editing = {"value": True}
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])

        with patch.object(dlg._seg_model, "refresh", wraps=dlg._seg_model.refresh) as refresh:
            dlg._on_refresh_done(results, list(tmp_files), list(dlg._keys), (0, 0, 0), auto_size=False)
            refresh.assert_not_called()

            editing["value"] = False
            dlg._schedule_pending_update()
            qtbot.waitUntil(lambda: refresh.called, timeout=3000)

        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_deferred_refresh_takes_priority_over_stale_apply(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        editing = {"value": True}
        calls = []
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])

        assert dlg._defer_update_if_editing(lambda: calls.append("apply"), kind="apply") is True
        assert dlg._defer_update_if_editing(lambda: calls.append("refresh"), kind="refresh") is True

        editing["value"] = False
        dlg._schedule_pending_update()
        qtbot.waitUntil(lambda: calls == ["refresh"], timeout=3000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_reset_discards_queued_deferred_apply(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files([tmp_files[0]])
        editing = {"value": True}
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])
        results = [RenameResult(original=tmp_files[0].name, segments=[tmp_files[0].stem, tmp_files[0].suffix], new_name=tmp_files[0].name)]

        dlg._on_refresh_done(
            results,
            [tmp_files[0]],
            [str(tmp_files[0]).replace("\\", "/")],
            (0, 0, 0, []),
            auto_size=False,
        )
        dlg._schedule_pending_update()

        calls = []
        with patch.object(dlg, "_apply_refresh_done", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))):
            dlg.reset()
            editing["value"] = False
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents)

        assert calls == []
        assert dlg._paths == []
        assert dlg._results == []
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_set_files_discards_queued_deferred_apply(self, mock_init, qtbot, tmp_files, monkeypatch):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files([tmp_files[0]])
        editing = {"value": True}
        monkeypatch.setattr(dlg._seg_table, "is_editing", lambda: editing["value"])
        results = [RenameResult(original=tmp_files[0].name, segments=[tmp_files[0].stem, tmp_files[0].suffix], new_name=tmp_files[0].name)]

        dlg._on_refresh_done(
            results,
            [tmp_files[0]],
            [str(tmp_files[0]).replace("\\", "/")],
            (0, 0, 0, []),
            auto_size=False,
        )
        dlg._schedule_pending_update()

        calls = []
        with (
            patch.object(dlg, "_apply_refresh_done", side_effect=lambda *args, **kwargs: calls.append((args, kwargs))),
            patch.object(dlg, "_refresh") as refresh,
        ):
            dlg.set_files([tmp_files[1]])
            editing["value"] = False
            QtWidgets.QApplication.processEvents(QtCore.QEventLoop.AllEvents)

        refresh.assert_called_once_with()
        assert calls == []
        assert dlg._paths == [tmp_files[1]]
        dlg.close()


class TestRenameColumnOverrides:
    def test_override_bypasses_source(self):
        col = RenameColumn(NameSource())
        segment = _make_segment(Path("test.jpg"))
        assert col.evaluate(segment) == "test"
        col.overrides[str(segment.original_path)] = "custom"
        assert col.evaluate(segment) == "custom"

    def test_override_bypasses_post(self):
        col = RenameColumn(NameSource(), PostProcess(prefix="X_"))
        segment = _make_segment(Path("test.jpg"))
        assert col.evaluate(segment) == "X_test"
        col.overrides[str(segment.original_path)] = "raw"
        assert col.evaluate(segment) == "raw"

    def test_no_override_uses_normal_path(self):
        col = RenameColumn(NameSource())
        segment = _make_segment(Path("hello.png"))
        assert col.evaluate(segment) == "hello"


def _make_segment(path: Path):
    from wafer.plugin.rename.base import SegmentInfo

    return SegmentInfo(
        index=0,
        total=1,
        original_path=path,
        stem=path.stem,
        ext=path.suffix.lstrip("."),
        metadata={},
    )


class TestSort:
    def test_preview_header_has_no_indicator(self):
        from wafer.builtins.batch_renamer.table import PreviewModel

        model = PreviewModel()
        assert model.headerData(0, Qt.Horizontal) == "Original"
        assert model.headerData(1, Qt.Horizontal) == "Result"
        assert "\u25b2" not in model.headerData(0, Qt.Horizontal)

    def test_segment_header_has_no_indicator(self):
        from wafer.builtins.batch_renamer.table import SegmentModel

        model = SegmentModel()
        name_col = RenameColumn(NameSource())
        ext_col = RenameColumn(ExtSource())
        model.configure([name_col], ext_col, "+", ".ext")
        header = model.headerData(0, Qt.Horizontal)
        assert "\u25b2" not in header
        assert "\u25bc" not in header

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_set_files_preserves_input_order(self, mock_init, qtbot, tmp_path):
        files = []
        for name in ["b2.jpg", "a10.jpg", "a2.jpg"]:
            path = tmp_path / name
            path.write_bytes(b"x")
            files.append(path)
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(files)
        assert [p.name for p in dlg._paths] == ["b2.jpg", "a10.jpg", "a2.jpg"]
        assert dlg._initial_paths == dlg._paths
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_add_files_appends_at_end(self, mock_init, qtbot, tmp_path):
        initial = []
        for name in ["c.jpg", "a.jpg"]:
            path = tmp_path / name
            path.write_bytes(b"x")
            initial.append(path)
        added = tmp_path / "b.jpg"
        added.write_bytes(b"x")
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(initial)
        dlg.add_files([added])
        assert [p.name for p in dlg._paths] == ["c.jpg", "a.jpg", "b.jpg"]
        assert dlg._initial_paths == dlg._paths
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_apply_sort_preview_ascending(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._paths = list(reversed(dlg._paths))
        dlg._keys = list(reversed(dlg._keys))
        dlg._results = list(reversed(dlg._results))
        dlg._apply_sort("preview", 0, True)
        qtbot.waitUntil(lambda: [p.name for p in dlg._paths] == ["a.jpg", "b.jpg", "c.jpg"], timeout=5000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_apply_sort_segment_descending(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._apply_sort("segment", 0, False)
        qtbot.waitUntil(lambda: [r.segments[0] for r in dlg._results] == ["c", "b", "a"], timeout=5000)
        assert [p.name for p in dlg._paths] == ["c.jpg", "b.jpg", "a.jpg"]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_refresh_preserves_manual_order(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._paths = list(reversed(dlg._paths))
        dlg._keys = list(reversed(dlg._keys))
        dlg._results = list(reversed(dlg._results))
        dlg._refresh(auto_size=False)
        qtbot.waitUntil(lambda: [p.name for p in dlg._paths] == ["c.jpg", "b.jpg", "a.jpg"], timeout=5000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_reorder_rows_moves_selection(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._reorder_rows([0], 3)
        qtbot.waitUntil(lambda: [p.name for p in dlg._paths] == ["b.jpg", "c.jpg", "a.jpg"], timeout=5000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_reorder_rows_multi_selection(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg._reorder_rows([0, 1], 3)
        qtbot.waitUntil(lambda: [p.name for p in dlg._paths] == ["c.jpg", "a.jpg", "b.jpg"], timeout=5000)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_reorder_rows_clears_thumb_requests(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        token = MagicMock()
        dlg._thumb_tokens[0] = token
        dlg._thumb_visible.add(0)
        dlg._reorder_rows([0], 3)
        qtbot.waitUntil(lambda: [p.name for p in dlg._paths] == ["b.jpg", "c.jpg", "a.jpg"], timeout=5000)
        token.cancel.assert_called_once()
        assert dlg._thumb_tokens == {}
        assert dlg._thumb_visible == set()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_apply_sort_clears_thumb_requests(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        token = MagicMock()
        dlg._thumb_tokens[0] = token
        dlg._thumb_visible.add(0)
        dlg._apply_sort("segment", 0, False)
        qtbot.waitUntil(lambda: [r.segments[0] for r in dlg._results] == ["c", "b", "a"], timeout=5000)
        token.cancel.assert_called_once()
        assert dlg._thumb_tokens == {}
        assert dlg._thumb_visible == set()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sort_menu_items_for_preview(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        idx = dlg._preview_model.index(0, 1)
        items = dlg._sort_menu_items(dlg._result_view, idx)
        assert len(items) == 3
        assert items[0] == "-"

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_sort_menu_items_skip_add_column(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        idx = dlg._seg_model.index(0, dlg._add_section)
        assert dlg._sort_menu_items(dlg._seg_table, idx) == []
        dlg.close()


class TestThumbCacheLRU:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_cache_is_ordered_dict(self, mock_init, qtbot, tmp_files):
        import collections

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert isinstance(dlg._thumb_cache, collections.OrderedDict)
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_cache_evicts_beyond_limit(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.THUMB_CACHE_LIMIT = 5
        img = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
        for i in range(10):
            dlg._on_thumbnail_loaded(-1, f"key_{i}", img)
        assert len(dlg._thumb_cache) == 5
        assert "key_0" not in dlg._thumb_cache
        assert "key_9" in dlg._thumb_cache
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_thumb_for_row_refreshes_lru(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg.THUMB_CACHE_LIMIT = 3
        img = QtGui.QImage(4, 4, QtGui.QImage.Format_RGB32)
        for p in tmp_files:
            dlg._on_thumbnail_loaded(-1, str(p), img)
        assert len(dlg._thumb_cache) == 3
        dlg.thumb_for_row(0)
        first_key = str(tmp_files[0])
        keys = list(dlg._thumb_cache.keys())
        assert keys[-1] == first_key
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_cache_limit_default(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        assert dlg.THUMB_CACHE_LIMIT == 200
        dlg.close()


class TestContextMenu:
    class _TopLevelShowTrace(QtCore.QObject):
        def __init__(self):
            super().__init__()
            self.shows = []

        def eventFilter(self, obj, event):
            if event.type() == QtCore.QEvent.Show and isinstance(obj, QtWidgets.QWidget) and obj.isWindow():
                self.shows.append((type(obj).__name__, obj.size()))
            return False

    def _assert_popup_anchored_to_header(self, popup, header, section):
        section_x = header.sectionPosition(section) - header.offset()
        header_top = header.mapToGlobal(QtCore.QPoint(section_x, 0))
        header_bottom = header.mapToGlobal(QtCore.QPoint(section_x, header.height()))
        popup_rect = QtCore.QRect(popup.pos(), popup.size())
        vertical_gap = min(
            abs(popup_rect.top() - header_bottom.y()),
            abs(popup_rect.bottom() - header_top.y()),
        )
        assert vertical_gap <= 4
        assert abs(popup_rect.left() - header_top.x()) <= max(header.sectionSize(section), popup_rect.width())

    @pytest.mark.parametrize("insert_attr", ["prefix", "suffix"])
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_segment_header_popup_stays_open_when_insert_is_enabled(self, mock_init, qtbot, tmp_files, insert_attr):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        setattr(dlg._columns[0].post, insert_attr, "insert_")
        dlg._rebuild()
        qtbot.waitUntil(lambda: len(dlg._results) == 3, timeout=5000)
        dlg.resize(640, 480)
        dlg.show()
        qtbot.waitExposed(dlg)
        qtbot.waitUntil(dlg.isVisible, timeout=5000)

        header = dlg._seg_table.horizontalHeader()
        qtbot.waitUntil(lambda: header.viewport().isVisible() and header.sectionSize(0) > 0, timeout=5000)
        pos = header.sectionViewportPosition(0) + header.sectionSize(0) // 2
        click_pos = QtCore.QPoint(pos, header.height() // 2)
        trace = self._TopLevelShowTrace()
        QtWidgets.QApplication.instance().installEventFilter(trace)

        try:
            qtbot.mouseClick(header.viewport(), Qt.LeftButton, pos=click_pos)
            qtbot.waitUntil(lambda: dlg._popup is not None and dlg._popup.isVisible(), timeout=5000)
            first_popup = dlg._popup
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
            assert dlg._popup is not None
            assert dlg._popup.isVisible()
            self._assert_popup_anchored_to_header(dlg._popup, header, 0)

            qtbot.mouseClick(header.viewport(), Qt.LeftButton, pos=click_pos)
            qtbot.waitUntil(lambda: dlg._popup is not None and dlg._popup.isVisible(), timeout=5000)
            for _ in range(10):
                QtWidgets.QApplication.processEvents()

            assert dlg._popup is not None
            assert dlg._popup.isVisible()
            assert dlg._popup is not first_popup
            self._assert_popup_anchored_to_header(dlg._popup, header, 0)

            insert_btn = next(btn for btn in dlg._popup.findChildren(QtWidgets.QPushButton) if "Insert" in btn.text())
            qtbot.mouseClick(insert_btn, Qt.LeftButton)
            qtbot.waitUntil(lambda: dlg._popup is not None and dlg._popup.isVisible(), timeout=5000)
            for _ in range(10):
                QtWidgets.QApplication.processEvents()
            assert dlg._popup is not None
            assert dlg._popup.isVisible()
            assert [name for name, _size in trace.shows] == ["ColumnSettingsPopup", "ColumnSettingsPopup"]
        finally:
            QtWidgets.QApplication.instance().removeEventFilter(trace)
            dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_show_row_menu_builds_command_menu(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg._seg_table.selectionModel().select(
            dlg._seg_model.index(0, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )

        built_menu = None

        class FakeSpec:
            def __init__(self, items):
                self._items = items

            def exec(self, *a, **kw):
                nonlocal built_menu
                built_menu = self._items

        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            def menu(self, items):
                return FakeSpec(items)

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        assert built_menu is not None
        str_items = [i for i in built_menu if isinstance(i, str)]
        assert "file.open" in str_items
        assert "file.show_explorer" in str_items
        assert "file.show_file" in str_items
        assert "file.select_path" in str_items
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_passes_selected_paths(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg._seg_table.selectionModel().select(
            dlg._seg_model.index(1, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )

        captured_seed = None

        class FakeSpec:
            def exec(self, *a, **kw):
                pass

        class FakeSession:
            def __init__(self, *a, **kw):
                nonlocal captured_seed
                captured_seed = kw.get("seed_ctx")

            def menu(self, items):
                return FakeSpec()

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        logical_path = str(tmp_files[1]).replace("\\", "/")
        assert captured_seed is not None
        assert captured_seed.extras["path"] == logical_path
        assert captured_seed.extras["paths"] == [logical_path]
        assert captured_seed.extras["source"] == str(tmp_files[1])
        assert captured_seed.extras["sources"] == [str(tmp_files[1])]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_splits_logical_paths_and_sources(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        logical_paths = [f"virtual://item/{i}" for i in range(len(tmp_files))]
        dlg.set_files(tmp_files, keys=logical_paths)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg._seg_table.selectionModel().select(
            dlg._seg_model.index(2, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )

        captured_seed = None

        class FakeSpec:
            def exec(self, *a, **kw):
                pass

        class FakeSession:
            def __init__(self, *a, **kw):
                nonlocal captured_seed
                captured_seed = kw.get("seed_ctx")

            def menu(self, items):
                return FakeSpec()

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        assert captured_seed is not None
        assert captured_seed.extras["path"] == logical_paths[2]
        assert captured_seed.extras["paths"] == [logical_paths[2]]
        assert captured_seed.extras["source"] == str(tmp_files[2])
        assert captured_seed.extras["sources"] == [str(tmp_files[2])]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_multiple_selection(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        ext_sec = dlg._ext_section
        sel = dlg._seg_table.selectionModel()
        sel.select(
            dlg._seg_model.index(0, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )
        sel.select(
            dlg._seg_model.index(0, ext_sec),
            QtCore.QItemSelectionModel.Select,
        )
        sel.select(
            dlg._seg_model.index(2, 0),
            QtCore.QItemSelectionModel.Select,
        )

        captured_seed = None

        class FakeSpec:
            def exec(self, *a, **kw):
                pass

        class FakeSession:
            def __init__(self, *a, **kw):
                nonlocal captured_seed
                captured_seed = kw.get("seed_ctx")

            def menu(self, items):
                return FakeSpec()

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        logical_0 = str(tmp_files[0]).replace("\\", "/")
        logical_2 = str(tmp_files[2]).replace("\\", "/")
        assert captured_seed is not None
        assert len(captured_seed.extras["paths"]) == 2
        assert logical_0 in captured_seed.extras["paths"]
        assert logical_2 in captured_seed.extras["paths"]
        assert len(captured_seed.extras["sources"]) == 2
        assert str(tmp_files[0]) in captured_seed.extras["sources"]
        assert str(tmp_files[2]) in captured_seed.extras["sources"]
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_has_remove_action(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu, ActionKit

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        dlg._seg_table.selectionModel().select(
            dlg._seg_model.index(0, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )

        built_menu = None

        class FakeSpec:
            def __init__(self, items):
                self._items = items

            def exec(self, *a, **kw):
                nonlocal built_menu
                built_menu = self._items

        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            def menu(self, items):
                return FakeSpec(items)

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        assert built_menu is not None
        inline_cmds = [i for i in built_menu if hasattr(i, "path") and "remove" in i.path]
        assert len(inline_cmds) == 1
        assert "Remove" in inline_cmds[0].display
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_has_restore_action_for_edited_cell(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)

        idx = dlg._seg_model.index(0, 0)
        with patch.object(dlg, "_refresh"):
            dlg._seg_model.setData(idx, "custom_name", Qt.EditRole)
        dlg._seg_table.selectionModel().select(idx, QtCore.QItemSelectionModel.ClearAndSelect)

        built_menu = None

        class FakeSpec:
            def __init__(self, items):
                self._items = items

            def exec(self, *a, **kw):
                nonlocal built_menu
                built_menu = self._items

        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            def menu(self, items):
                return FakeSpec(items)

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos, clicked_index=idx)

        assert built_menu is not None
        restore_cmds = [i for i in built_menu if hasattr(i, "path") and i.path == "inline.renamer.restore_cell"]
        assert len(restore_cmds) == 1
        assert restore_cmds[0].display == "Restore selected override(s)"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_has_restore_selected_action_for_multiple_edited_cells(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)

        idx_0 = dlg._seg_model.index(0, 0)
        idx_1 = dlg._seg_model.index(1, 0)
        with patch.object(dlg, "_refresh"):
            dlg._seg_model.setData(idx_0, "custom_name", Qt.EditRole)
            dlg._seg_model.setData(idx_1, "other_name", Qt.EditRole)

        sel = dlg._seg_table.selectionModel()
        sel.select(idx_0, QtCore.QItemSelectionModel.ClearAndSelect)
        sel.select(idx_1, QtCore.QItemSelectionModel.Select)

        built_menu = None

        class FakeSpec:
            def __init__(self, items):
                self._items = items

            def exec(self, *a, **kw):
                nonlocal built_menu
                built_menu = self._items

        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            def menu(self, items):
                return FakeSpec(items)

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos, clicked_index=idx_1)

        assert built_menu is not None
        restore_cmds = [i for i in built_menu if hasattr(i, "path") and i.path == "inline.renamer.restore_cell"]
        assert len(restore_cmds) == 1
        assert restore_cmds[0].display == "Restore selected override(s)"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_context_menu_has_restore_action_for_unedited_cell(self, mock_init, qtbot, tmp_files):
        from wafer.core.commands.bridge import Menu

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        qtbot.addWidget(dlg)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        idx = dlg._seg_model.index(0, 0)
        dlg._seg_table.selectionModel().select(idx, QtCore.QItemSelectionModel.ClearAndSelect)

        built_menu = None

        class FakeSpec:
            def __init__(self, items):
                self._items = items

            def exec(self, *a, **kw):
                nonlocal built_menu
                built_menu = self._items

        class FakeSession:
            def __init__(self, *a, **kw):
                pass

            def menu(self, items):
                return FakeSpec(items)

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos, clicked_index=idx)

        assert built_menu is not None
        restore_cmds = [i for i in built_menu if hasattr(i, "path") and i.path == "inline.renamer.restore_cell"]
        assert len(restore_cmds) == 1
        assert restore_cmds[0].display == "Restore selected override(s)"
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_right_click_preserves_multi_selection(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._preview_model.rowCount() == 3, timeout=5000)
        sel = dlg._seg_table.selectionModel()
        for r in range(3):
            sel.select(
                dlg._seg_model.index(r, 0),
                QtCore.QItemSelectionModel.Select,
            )
        assert len(sel.selectedIndexes()) == 3

        pos = dlg._seg_table.visualRect(dlg._seg_model.index(1, 0)).center()
        event = QtGui.QMouseEvent(
            QtCore.QEvent.Type.MouseButtonPress,
            QtCore.QPointF(pos),
            QtCore.QPointF(pos),
            Qt.RightButton,
            Qt.RightButton,
            Qt.NoModifier,
        )
        dlg._seg_table.mousePressEvent(event)

        assert len(sel.selectedIndexes()) == 3

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_set_files_resets_selection_count_in_menu(self, mock_init, qtbot, tmp_path):
        from wafer.core.commands.bridge import Menu

        files_4 = []
        for name in ["a.jpg", "b.jpg", "c.jpg", "d.jpg"]:
            f = tmp_path / name
            f.write_bytes(b"\x00" * 16)
            files_4.append(f)

        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(files_4)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._seg_model.rowCount() == 4, timeout=5000)

        sel = dlg._seg_table.selectionModel()
        for r in range(4):
            sel.select(
                dlg._seg_model.index(r, 0),
                QtCore.QItemSelectionModel.Select,
            )
        assert len(sel.selectedIndexes()) == 4

        files_1 = [tmp_path / "only.jpg"]
        files_1[0].write_bytes(b"\x00" * 16)
        dlg.set_files(files_1)
        dlg._rebuild()
        qtbot.waitUntil(lambda: dlg._seg_model.rowCount() == 1, timeout=5000)

        dlg._seg_table.selectionModel().select(
            dlg._seg_model.index(0, 0),
            QtCore.QItemSelectionModel.ClearAndSelect,
        )

        captured_seed = None

        class FakeSpec:
            def exec(self, *a, **kw):
                pass

        class FakeSession:
            def __init__(self, *a, **kw):
                nonlocal captured_seed
                captured_seed = kw.get("seed_ctx")

            def menu(self, items):
                return FakeSpec()

        with patch.object(Menu, "session", staticmethod(lambda *a, **kw: FakeSession(*a, **kw))):
            gpos = dlg._seg_table.viewport().mapToGlobal(QtCore.QPoint(10, 10))
            dlg._show_row_menu(dlg._seg_table, gpos)

        assert captured_seed is not None
        assert len(captured_seed.extras["paths"]) == 1
        assert captured_seed.extras["path"] == str(files_1[0]).replace("\\", "/")


def _make_mime(urls):
    mime = QtCore.QMimeData()
    mime.setUrls([QtCore.QUrl.fromLocalFile(str(u)) for u in urls])
    return mime


def _make_drop_event(mime, pos=None):
    if pos is None:
        pos = QtCore.QPointF(10, 10)
    ev = QtGui.QDropEvent(
        pos,
        Qt.CopyAction | Qt.MoveAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )
    return ev


def _make_drag_enter_event(mime, pos=None):
    if pos is None:
        pos = QtCore.QPoint(10, 10)
    return QtGui.QDragEnterEvent(
        pos,
        Qt.CopyAction | Qt.MoveAction,
        mime,
        Qt.LeftButton,
        Qt.NoModifier,
    )


class TestDropFiles:
    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drag_enter_accepts_local_files(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        mime = _make_mime(tmp_files)
        event = _make_drag_enter_event(mime)
        dlg.dragEnterEvent(event)
        assert event.isAccepted()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drag_enter_rejects_no_urls(self, mock_init, qtbot):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        mime = QtCore.QMimeData()
        mime.setText("hello")
        event = _make_drag_enter_event(mime)
        dlg.dragEnterEvent(event)
        assert not event.isAccepted()
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drop_sets_files_when_empty(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        assert dlg._paths == []
        mime = _make_mime(tmp_files)
        event = _make_drop_event(mime)
        dlg.dropEvent(event)
        assert len(dlg._paths) == 3
        assert dlg._stack.currentWidget() == dlg._rename_page
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drop_adds_files_to_existing(self, mock_init, qtbot, tmp_path):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        first = [tmp_path / "a.jpg"]
        first[0].write_bytes(b"\x00")
        dlg.set_files(first)
        assert len(dlg._paths) == 1

        extra = [tmp_path / "b.jpg", tmp_path / "c.jpg"]
        for f in extra:
            f.write_bytes(b"\x00")
        mime = _make_mime(extra)
        event = _make_drop_event(mime)
        dlg.dropEvent(event)
        assert len(dlg._paths) == 3
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drop_deduplicates(self, mock_init, qtbot, tmp_files):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        dlg.set_files(tmp_files[:2])
        assert len(dlg._paths) == 2
        mime = _make_mime(tmp_files)
        event = _make_drop_event(mime)
        dlg.dropEvent(event)
        assert len(dlg._paths) == 3
        dlg.close()

    @patch.object(BatchRenameWidget, "_start_async_init")
    def test_drop_ignores_directories(self, mock_init, qtbot, tmp_path):
        dlg = BatchRenameWidget()
        qtbot.addWidget(dlg)
        sub = tmp_path / "subdir"
        sub.mkdir()
        mime = _make_mime([sub])
        event = _make_drop_event(mime)
        dlg.dropEvent(event)
        assert dlg._paths == []
        dlg.close()


class TestStandaloneLaunch:
    def test_open_batch_renamer_toggles_panel_with_mainwindow(self):
        from wafer.builtins.commands.tools import open_batch_renamer

        mock_ctx = MagicMock()
        mock_w = MagicMock()
        mock_ctx.get_instance = lambda name: mock_w if name == "MainWindow" else None
        open_batch_renamer(mock_ctx)
        mock_w._layout_manager.toggle_panel.assert_called_once_with("Batch Renamer")

    def test_open_batch_renamer_standalone_without_mainwindow(self, qtbot, monkeypatch):
        from wafer.builtins.commands.tools import open_batch_renamer, _standalone_dialogs

        class _FakeStore:
            def __init__(self, *a, **kw):
                pass

            def save(self, *a, **kw):
                pass

            def restore(self, *a, **kw):
                pass

        monkeypatch.setattr(
            "wafer.builtins.commands.tools.DialogLayoutStore",
            _FakeStore,
        )
        _standalone_dialogs.pop("batch_renamer", None)
        mock_ctx = MagicMock()
        mock_ctx.get_instance = lambda name: None
        with patch.object(BatchRenameWidget, "_start_async_init"):
            open_batch_renamer(mock_ctx)
        assert "batch_renamer" in _standalone_dialogs
        dlg = _standalone_dialogs["batch_renamer"]
        dlg.setAttribute(QtCore.Qt.WA_DeleteOnClose, False)
        qtbot.addWidget(dlg)

    def test_command_registered_with_star_scope(self):
        from wafer.builtins.commands.tools import ToolCommands

        assert ToolCommands.SCOPE == "*"

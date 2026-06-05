import py_compile
import os
import tempfile
from unittest.mock import MagicMock

from wafer.app.indexer.watch.setting_watcher import SettingWatcher


def test_compile():
    py_compile.compile("wafer/app/indexer/watch/setting_watcher.py")


def test_no_delete_requested_signal():
    mock_db = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        mock_db.db_name = f.name
        mock_db.get_all_parent_folders.return_value = []
        mock_db.get_all_ignore_folders.return_value = []
    try:
        watcher = SettingWatcher(mock_db)
        assert not hasattr(watcher, "delete_requested")
    finally:
        os.unlink(f.name)


def test_stop_handles_observer_error():
    mock_db = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        mock_db.db_name = f.name
        mock_db.get_all_parent_folders.return_value = []
        mock_db.get_all_ignore_folders.return_value = []
    try:
        watcher = SettingWatcher(mock_db)
        watcher._observer.stop = MagicMock(side_effect=RuntimeError("observer broken"))
        watcher.stop()
    finally:
        os.unlink(f.name)

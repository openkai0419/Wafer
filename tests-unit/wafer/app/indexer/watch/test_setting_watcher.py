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
        mock_db.get_all_folder_settings.return_value = ([], [], [])
    try:
        watcher = SettingWatcher(mock_db)
        assert not hasattr(watcher, "delete_requested")
    finally:
        os.unlink(f.name)


def test_stop_handles_observer_error():
    mock_db = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        mock_db.db_name = f.name
        mock_db.get_all_folder_settings.return_value = ([], [], [])
    try:
        watcher = SettingWatcher(mock_db)
        watcher._observer.stop = MagicMock(side_effect=RuntimeError("observer broken"))
        watcher.stop()
    finally:
        os.unlink(f.name)


def test_check_changes_coalesces_ignore_folders_and_patterns():
    mock_db = MagicMock()
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        mock_db.db_name = f.name
        mock_db.get_all_folder_settings.return_value = ([], [], [])
    try:
        watcher = SettingWatcher(mock_db)
        emitted = []
        watcher.ignore_changed.connect(lambda folders, patterns: emitted.append((folders, patterns)))

        mock_db.get_all_folder_settings.return_value = ([], ["C:/ignored"], ["*cache*"])
        watcher._check_changes()

        assert len(emitted) == 1
        assert set(emitted[0][0]) == {"C:/ignored"}
        assert set(emitted[0][1]) == {"*cache*"}
    finally:
        os.unlink(f.name)

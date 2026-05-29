from unittest.mock import patch, MagicMock

import pytest


class TestDirectLaunchSlotRestore:
    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main._wait_install_then_load_plugins")
    @patch("main._create_app")
    def test_no_restore_ids_passes_none(self, mock_create, mock_wait, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_slot_ids.return_value = []

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, parser=None, dev=False, slot=None)
            with patch("wafer.core.workspace.WorkspaceStore.instance", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, slot_id=None)
        mock_wait.assert_called_once()

    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main._wait_install_then_load_plugins")
    @patch("main._create_app")
    def test_single_restore_id(self, mock_create, mock_wait, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_slot_ids.return_value = ["s1"]

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, parser=None, dev=False, slot=None)
            with patch("wafer.core.workspace.WorkspaceStore.instance", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, slot_id="s1")
        viewer_spawn_calls = [c for c in mock_proc.new_main.call_args_list if "--viewer" in c.args]
        assert viewer_spawn_calls == []

    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main._wait_install_then_load_plugins")
    @patch("main._create_app")
    def test_multiple_restore_ids(self, mock_create, mock_wait, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_slot_ids.return_value = ["s1", "s2", "Work"]

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, parser=None, dev=False, slot=None)
            with patch("wafer.core.workspace.WorkspaceStore.instance", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, slot_id="s1")
        mock_proc.new_main.assert_any_call("--viewer", "--slot", "s2")
        mock_proc.new_main.assert_any_call("--viewer", "--slot", "Work")


class TestTrayStartup:
    @patch("main._entry_tray")
    @patch("main._bootstrap_plugins_for_tray")
    def test_tray_mode_delegates_only_to_entry_tray(self, mock_bootstrap, mock_entry_tray):
        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(
                tray=True,
                viewer=False,
                indexer=None,
                collector=None,
                parser=None,
                plugin="image",
                parent_pid=None,
                slot=None,
            )
            from main import main

            main()

        mock_entry_tray.assert_called_once_with()
        mock_bootstrap.assert_not_called()

    @patch("main._bootstrap_plugins_for_tray")
    def test_entry_tray_skips_bootstrap_when_lock_exists(self, mock_bootstrap):
        class BusyLock:
            def __enter__(self):
                raise FileExistsError()

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        with patch("main.SafeProcessLock", return_value=BusyLock()):
            from main import _entry_tray

            _entry_tray()

        mock_bootstrap.assert_not_called()

    @patch("main.sys.exit", side_effect=SystemExit)
    @patch("wafer.app.tray.main_tray.TrayApp")
    @patch("wafer.core.qt.tooltip.install_instant_tooltips")
    @patch("PySide6.QtWidgets.QApplication")
    @patch("main.get_icon")
    @patch("main.list_setting_db_names", return_value=[])
    @patch("main.AppProcess.terminate_and_wait")
    @patch("main.AppProcess.get_by_args_subset", return_value=[])
    @patch("main._bootstrap_plugins_for_tray")
    def test_entry_tray_bootstraps_after_lock(
        self,
        mock_bootstrap,
        mock_get_by_args,
        mock_terminate,
        mock_list_names,
        mock_get_icon,
        mock_qapp,
        mock_tooltips,
        mock_tray_app,
        mock_exit,
    ):
        order = []

        class HeldLock:
            def __enter__(self):
                order.append("lock")
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                order.append("unlock")
                return False

        mock_bootstrap.side_effect = lambda: order.append("bootstrap")
        mock_get_by_args.side_effect = lambda *_args, **_kwargs: order.append("get_indexers") or []
        mock_get_icon.return_value = object()
        mock_tooltips.side_effect = lambda _app: order.append("tooltips")
        mock_app = MagicMock()
        mock_app.exec.return_value = 0
        mock_qapp.side_effect = lambda *_args, **_kwargs: order.append("qapp") or mock_app
        mock_tray = MagicMock()
        mock_tray.show.side_effect = lambda: order.append("tray_show")
        mock_tray_app.return_value = mock_tray

        with patch("main.SafeProcessLock", return_value=HeldLock()):
            from main import _entry_tray

            with pytest.raises(SystemExit):
                _entry_tray()

        assert order[:4] == ["lock", "bootstrap", "get_indexers", "qapp"]
        mock_bootstrap.assert_called_once_with()
        mock_terminate.assert_called_once_with([])
        mock_list_names.assert_called_once_with()

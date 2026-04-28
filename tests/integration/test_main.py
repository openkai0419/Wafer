from unittest.mock import patch, MagicMock


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

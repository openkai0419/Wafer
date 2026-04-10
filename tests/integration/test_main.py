from unittest.mock import patch, MagicMock, call


class TestDirectLaunchProfileRestore:
    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main.load_plugins")
    @patch("main._create_app")
    def test_no_restore_ids_passes_none(self, mock_create, mock_load, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_profile_ids.return_value = []

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, detacher=None, dev=False, profile=None)
            with patch("wafer.core.profile.ProfileStore", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, profile_id=None)
        tray_call = call.new_main("--tray")
        assert tray_call in mock_proc.mock_calls

    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main.load_plugins")
    @patch("main._create_app")
    def test_single_restore_id(self, mock_create, mock_load, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_profile_ids.return_value = ["s1"]

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, detacher=None, dev=False, profile=None)
            with patch("wafer.core.profile.ProfileStore", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, profile_id="s1")
        viewer_spawn_calls = [c for c in mock_proc.new_main.call_args_list if "--viewer" in c.args]
        assert viewer_spawn_calls == []

    @patch("main._entry_viewer")
    @patch("main.AppProcess")
    @patch("main.load_plugins")
    @patch("main._create_app")
    def test_multiple_restore_ids(self, mock_create, mock_load, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_profile_ids.return_value = ["s1", "s2", "Work"]

        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(tray=False, viewer=False, indexer=None, collector=None, detacher=None, dev=False, profile=None)
            with patch("wafer.core.profile.ProfileStore", return_value=store):
                from main import main

                main()

        mock_viewer.assert_called_once_with(mock_app, profile_id="s1")
        mock_proc.new_main.assert_any_call("--viewer", "--profile", "s2")
        mock_proc.new_main.assert_any_call("--viewer", "--profile", "Work")

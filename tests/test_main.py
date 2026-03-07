from unittest.mock import patch, MagicMock, call


class TestDirectLaunchSessionRestore:

    @patch('main._entry_viewer')
    @patch('main.AppProcess')
    @patch('main._load_plugins_with_splash')
    @patch('main._create_app')
    def test_no_restore_ids_passes_none(self, mock_create, mock_splash, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_session_ids.return_value = []

        with patch('main.argparse.ArgumentParser.parse_args') as mock_args:
            mock_args.return_value = MagicMock(
                tray=False, viewer=False, indexer=None, collector=None,
                dev=False, session=None)
            with patch('wayfer.app.viewer.session.SessionStore', return_value=store):
                from main import main
                main()

        mock_viewer.assert_called_once_with(mock_app, session_id=None)
        tray_call = call.new_main('--tray')
        assert tray_call in mock_proc.mock_calls

    @patch('main._entry_viewer')
    @patch('main.AppProcess')
    @patch('main._load_plugins_with_splash')
    @patch('main._create_app')
    def test_single_restore_id(self, mock_create, mock_splash, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_session_ids.return_value = ['anon-1']

        with patch('main.argparse.ArgumentParser.parse_args') as mock_args:
            mock_args.return_value = MagicMock(
                tray=False, viewer=False, indexer=None, collector=None,
                dev=False, session=None)
            with patch('wayfer.app.viewer.session.SessionStore', return_value=store):
                from main import main
                main()

        mock_viewer.assert_called_once_with(mock_app, session_id='anon-1')
        viewer_spawn_calls = [
            c for c in mock_proc.new_main.call_args_list
            if '--viewer' in c.args
        ]
        assert viewer_spawn_calls == []

    @patch('main._entry_viewer')
    @patch('main.AppProcess')
    @patch('main._load_plugins_with_splash')
    @patch('main._create_app')
    def test_multiple_restore_ids(self, mock_create, mock_splash, mock_proc, mock_viewer):
        mock_app = MagicMock()
        mock_create.return_value = mock_app
        store = MagicMock()
        store.get_restore_session_ids.return_value = ['anon-1', 'anon-2', 'Work']

        with patch('main.argparse.ArgumentParser.parse_args') as mock_args:
            mock_args.return_value = MagicMock(
                tray=False, viewer=False, indexer=None, collector=None,
                dev=False, session=None)
            with patch('wayfer.app.viewer.session.SessionStore', return_value=store):
                from main import main
                main()

        mock_viewer.assert_called_once_with(mock_app, session_id='anon-1')
        mock_proc.new_main.assert_any_call('--viewer', '--session', 'anon-2')
        mock_proc.new_main.assert_any_call('--viewer', '--session', 'Work')

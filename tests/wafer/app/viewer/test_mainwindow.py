import py_compile
from unittest.mock import MagicMock, patch


def test_compile():
    py_compile.compile('wafer/app/viewer/mainwindow.py')


class TestUpdateTitle:

    def _make_win(self, session_entry=None, db_name='default', selected_paths=None):
        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win._session_entry = session_entry
            win.database_name = db_name
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = selected_paths or []
            win.setWindowTitle = MagicMock()
            return win

    def _named_entry(self, name='Work'):
        from wafer.app.viewer.session import SessionEntry
        return SessionEntry(session_id='abc123', name=name)

    def _unnamed_entry(self):
        from wafer.app.viewer.session import SessionEntry
        return SessionEntry(session_id='s1', name='')

    def test_named_session_shows_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_entry=self._named_entry('Work'), db_name='mydb', selected_paths=['/a/photos'])
        win._update_title()
        win.setWindowTitle.assert_called_once_with('Work')

    def test_unnamed_with_folders_shows_folder_names(self):
        from wafer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_entry=self._unnamed_entry(), selected_paths=['/home/user/photos', '/mnt/data/images'])
        win._update_title()
        win.setWindowTitle.assert_called_once_with('photos, images')

    def test_unnamed_no_folders_shows_db_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_entry=self._unnamed_entry(), db_name='mydb', selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with('mydb')

    def test_unnamed_no_folders_no_db_shows_app_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_entry=self._unnamed_entry(), db_name='', selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(APP_NAME)

    def test_no_session_entry_shows_folder_names(self):
        from wafer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_entry=None, selected_paths=['/data/pics'])
        win._update_title()
        win.setWindowTitle.assert_called_once_with('pics')


class TestSearchResultDiffCheck:

    def test_skip_when_paths_unchanged(self):
        from unittest.mock import MagicMock, patch
        paths = ['a.png', 'b.png']
        sources = ['a.png', 'b.png']
        aspects = [1.0, 1.5]

        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win._last_paths = paths
            win._folder_changed = False
            win.grid_view = MagicMock()
            win.file_model = MagicMock()
            win.overlay_stack = MagicMock()
            win.run_folder = False

            win._on_search_finished(paths, sources, aspects)
            win.grid_view.set_paths.assert_not_called()
            win.file_model.set_items.assert_not_called()
            win.overlay_stack.hide_persistent.assert_called_once_with("loading")

    def test_update_when_paths_changed(self):
        from unittest.mock import MagicMock, patch
        old_paths = ['a.png']
        new_paths = ['a.png', 'b.png']
        sources = ['a.png', 'b.png']
        aspects = [1.0, 1.5]

        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win._last_paths = old_paths
            win._folder_changed = False
            win.grid_view = MagicMock()
            win.file_model = MagicMock()
            win.overlay_stack = MagicMock()
            win.run_folder = False
            win.search_row_widget = MagicMock()

            win._on_search_finished(new_paths, sources, aspects)
            win.grid_view.set_paths.assert_called_once()
            win.file_model.set_items.assert_called_once()
            assert win._last_paths is new_paths

    def test_first_search_always_updates(self):
        from unittest.mock import MagicMock, patch
        paths = ['a.png']
        sources = ['a.png']
        aspects = [1.0]

        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win._last_paths = None
            win._folder_changed = False
            win.grid_view = MagicMock()
            win.file_model = MagicMock()
            win.overlay_stack = MagicMock()
            win.run_folder = False
            win.search_row_widget = MagicMock()

            win._on_search_finished(paths, sources, aspects)
            win.grid_view.set_paths.assert_called_once()
            assert win._last_paths is paths


class TestSyncSessionButton:

    def _make_win(self, session_entry=None):
        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win._session_entry = session_entry
            win.database_name = 'default'
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.setWindowTitle = MagicMock()
            win._session_button = MagicMock()
            return win

    def test_named_session_shows_name_on_button(self):
        from wafer.app.viewer.session import SessionEntry
        entry = SessionEntry(session_id='s1', name='Work')
        win = self._make_win(session_entry=entry)
        win._sync_session_button()
        win._session_button.setText.assert_called_with('\u25BC Work')

    def test_unnamed_session_shows_window(self):
        from wafer.app.viewer.session import SessionEntry
        entry = SessionEntry(session_id='s1', name='')
        win = self._make_win(session_entry=entry)
        win._sync_session_button()
        win._session_button.setText.assert_called_with('\u25BC Window')

    def test_colored_session_sets_stylesheet(self):
        from wafer.app.viewer.session import SessionEntry
        entry = SessionEntry(session_id='s1', name='Work', color='#4A90D9')
        win = self._make_win(session_entry=entry)
        win._sync_session_button()
        call_args = win._session_button.setStyleSheet.call_args[0][0]
        assert '#4A90D9' in call_args

    def test_no_color_default_stylesheet(self):
        from wafer.app.viewer.session import SessionEntry
        entry = SessionEntry(session_id='s1', name='Work')
        win = self._make_win(session_entry=entry)
        win._sync_session_button()
        call_args = win._session_button.setStyleSheet.call_args[0][0]
        assert '#4A90D9' not in call_args

    def test_update_title_calls_sync(self):
        from wafer.app.viewer.session import SessionEntry
        entry = SessionEntry(session_id='s1', name='Test')
        win = self._make_win(session_entry=entry)
        win._update_title()
        win._session_button.setText.assert_called()


class TestToggleShow:

    def _make_win(self):
        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win.isMinimized = MagicMock(return_value=False)
            win.isVisible = MagicMock(return_value=True)
            win.window_state = MagicMock()
            return win

    def test_visible_window_gets_minimized(self):
        win = self._make_win()
        win.toggle_show(True)
        win.window_state.minimize.assert_called_once()
        win.window_state.restore_or_activate.assert_not_called()

    def test_minimized_window_gets_restored(self):
        win = self._make_win()
        win.isMinimized.return_value = True
        win.toggle_show(False)
        win.window_state.restore_or_activate.assert_called_once()
        win.window_state.minimize.assert_not_called()

    def test_hidden_window_gets_shown(self):
        win = self._make_win()
        win.isVisible.return_value = False
        win.toggle_show(True)
        win.window_state.restore_or_activate.assert_called_once()
        win.window_state.minimize.assert_not_called()

    def test_ignores_state_arg(self):
        win = self._make_win()
        win.toggle_show(True)
        win.window_state.minimize.assert_called_once()
        win.window_state.minimize.reset_mock()
        win.toggle_show(False)
        win.window_state.minimize.assert_called_once()


class TestRaiseWindow:

    def _make_win(self):
        with patch('wafer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win.window_state = MagicMock()
            return win

    def test_always_calls_restore_or_activate(self):
        win = self._make_win()
        win.raise_window()
        win.window_state.restore_or_activate.assert_called_once()

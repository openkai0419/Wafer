import py_compile
from unittest.mock import MagicMock, patch


def test_compile():
    py_compile.compile('wayfer/app/viewer/mainwindow.py')


class TestUpdateTitle:

    def _make_win(self, session_id='anon-1', db_name='default', selected_paths=None):
        with patch('wayfer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wayfer.app.viewer.mainwindow import MainWindow
            win = MainWindow.__new__(MainWindow)
            win.session_id = session_id
            win.database_name = db_name
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = selected_paths or []
            win.setWindowTitle = MagicMock()
            return win

    def test_named_session_shows_session_id(self):
        from wayfer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_id='Work', db_name='mydb', selected_paths=['/a/photos'])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(f'Work - {APP_NAME}')

    def test_anon_with_folders_shows_folder_names(self):
        from wayfer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_id='anon-1', selected_paths=['/home/user/photos', '/mnt/data/images'])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(f'photos, images - {APP_NAME}')

    def test_anon_no_folders_shows_db_name(self):
        from wayfer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_id='anon-1', db_name='mydb', selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(f'mydb - {APP_NAME}')

    def test_anon_no_folders_no_db_shows_app_name(self):
        from wayfer.app.viewer.mainwindow import APP_NAME
        win = self._make_win(session_id='anon-1', db_name='', selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(APP_NAME)


class TestSearchResultDiffCheck:

    def test_skip_when_paths_unchanged(self):
        from unittest.mock import MagicMock, patch
        paths = ['a.png', 'b.png']
        sources = ['a.png', 'b.png']
        aspects = [1.0, 1.5]

        with patch('wayfer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wayfer.app.viewer.mainwindow import MainWindow
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

        with patch('wayfer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wayfer.app.viewer.mainwindow import MainWindow
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

        with patch('wayfer.app.viewer.mainwindow.MainWindow.__init__', lambda self, *a, **kw: None):
            from wayfer.app.viewer.mainwindow import MainWindow
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

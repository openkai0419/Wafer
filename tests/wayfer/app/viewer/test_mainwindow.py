import py_compile


def test_compile():
    py_compile.compile('wayfer/app/viewer/mainwindow.py')


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

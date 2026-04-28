import py_compile
from unittest.mock import MagicMock, patch


def test_compile():
    py_compile.compile("wafer/app/viewer/mainwindow.py")


class TestUpdateTitle:
    def _make_win(self, db_name="default", selected_paths=None):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.database_name = db_name
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = selected_paths or []
            win.setWindowTitle = MagicMock()
            return win

    def test_folders_show_folder_names(self):
        win = self._make_win(selected_paths=["/home/user/photos", "/mnt/data/images"])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("photos, images")

    def test_no_folders_shows_db_name(self):
        win = self._make_win(db_name="mydb", selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("mydb")

    def test_no_folders_no_db_shows_app_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(db_name="", selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(APP_NAME)


class TestSearchResultDiffCheck:
    def _make_win(self, last_paths=None):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._last_paths = last_paths
            win._folder_changed = False
            win.grid_view = MagicMock()
            win.file_model = MagicMock()
            win.overlay_stack = MagicMock()
            win.loading_indicator = MagicMock()
            win.search_row_widget = MagicMock()
            win.database_path = "test.db"
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.file_list_provider = MagicMock()
            win._mark_overlay_service = MagicMock()
            return win

    def test_skip_when_paths_unchanged(self):
        paths = ["a.png", "b.png"]
        win = self._make_win(last_paths=paths)
        win._on_search_finished(paths, ["a.png", "b.png"], [1.0, 1.5])
        win.grid_view.set_paths.assert_not_called()
        win.search_row_widget.run_folder_worker.assert_called_once()

    def test_update_when_paths_changed(self):
        win = self._make_win(last_paths=["a.png"])
        new_paths = ["a.png", "b.png"]
        win._on_search_finished(new_paths, new_paths, [1.0, 1.5])
        win.grid_view.set_paths.assert_called_once()
        assert win._last_paths is new_paths

    def test_first_search_always_updates(self):
        win = self._make_win(last_paths=None)
        paths = ["a.png"]
        win._on_search_finished(paths, paths, [1.0])
        win.grid_view.set_paths.assert_called_once()
        assert win._last_paths is paths


class TestOnDbContentUpdated:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.search_row_widget = MagicMock()
            win.search_row_widget.get_sort.return_value = ("path", False)
            win.search_row_widget.get_values.return_value = {}
            win.search_row_widget.build_filter_entries.return_value = []
            win.search_service = MagicMock()
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.database_path = "test.db"
            win.database_name = "testdb"
            return win

    def test_invalidates_key_cache(self):
        win = self._make_win()
        win._on_db_content_updated("testdb")
        win.search_row_widget.invalidate_key_cache.assert_called_once()

    def test_ignores_other_db(self):
        win = self._make_win()
        win._on_db_content_updated("other_db")
        win.search_row_widget.invalidate_key_cache.assert_not_called()


class TestToolbarPanel:
    def test_toolbar_panel_contains_workspace_progress_iconbar(self, qtbot):
        from PySide6 import QtCore, QtWidgets

        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.workspace_toolbar_widget = QtWidgets.QWidget()
            win.progress_bar = QtWidgets.QProgressBar()
            win.iconbar = QtWidgets.QWidget()
            panel = win._create_toolbar_panel()
        qtbot.addWidget(panel)
        assert panel.layout().count() == 3
        assert panel.layout().itemAt(0).widget() is win.workspace_toolbar_widget
        assert not (panel.layout().itemAt(0).alignment() & QtCore.Qt.AlignLeft)
        assert panel.layout().itemAt(1).widget() is win.progress_bar
        assert panel.layout().itemAt(2).widget() is win.iconbar


class TestToggleShow:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.isMinimized = MagicMock(return_value=False)
            win.isVisible = MagicMock(return_value=True)
            win.window_state = MagicMock()
            win.database_name = "testdb"
            return win

    def test_show_true_restores_window(self):
        win = self._make_win()
        win.toggle_show("testdb", True)
        win.window_state.restore_or_activate.assert_called_once()

    def test_show_false_minimizes_window(self):
        win = self._make_win()
        win.toggle_show("testdb", False)
        win.window_state.minimize.assert_called_once()

    def test_ignores_other_db(self):
        win = self._make_win()
        win.toggle_show("other_db", True)
        win.window_state.restore_or_activate.assert_not_called()


class TestRaiseWindow:
    def test_always_calls_restore_or_activate(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.window_state = MagicMock()
            win.raise_window()
            win.window_state.restore_or_activate.assert_called_once()

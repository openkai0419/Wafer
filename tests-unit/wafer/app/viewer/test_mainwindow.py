import py_compile
from unittest.mock import ANY, MagicMock, call, patch


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
            win.search_service = MagicMock()
            win.search_service.get.side_effect = lambda key, default=None: default
            win.file_list_provider = MagicMock()
            win.grid_overlay_host = MagicMock()
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
    def _make_win(self, auto_execute_on_update=True):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.search_row_widget = MagicMock()
            win.search_row_widget.get_sort.return_value = ("path", False)
            win.search_row_widget.get_values.return_value = {}
            win.search_row_widget.build_filter_entries.return_value = []
            win.search_service = MagicMock()
            win.search_service.get.side_effect = lambda key, default=None: auto_execute_on_update if key == "auto_execute_on_update" else default
            win.search = MagicMock()
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.database_path = "test.db"
            win.database_name = "testdb"
            return win

    def test_invalidates_key_cache(self):
        win = self._make_win()
        win._on_db_content_updated("testdb")
        win.search_row_widget.invalidate_key_cache.assert_called_once()
        win.search.assert_called_once_with(force=True)

    def test_auto_execute_on_update_disabled_skips_search(self):
        win = self._make_win(auto_execute_on_update=False)
        win._on_db_content_updated("testdb")
        win.search_row_widget.invalidate_key_cache.assert_not_called()
        win.search.assert_not_called()

    def test_ignores_other_db(self):
        win = self._make_win()
        win._on_db_content_updated("other_db")
        win.search_row_widget.invalidate_key_cache.assert_not_called()
        win.search.assert_not_called()

    def test_tags_updated_no_longer_has_grid_search_handler(self):
        from wafer.app.viewer.mainwindow import MainWindow

        assert not hasattr(MainWindow, "_on_tags_updated_research")


class TestReloadFolderList:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.setting_db = MagicMock()
            win.setting_db.get_all_parent_folders.return_value = ["/root"]
            win.setting_db.get_all_ignore_folders.return_value = ["/ignored"]
            win.folder_view = MagicMock()
            win.folder_view.is_structure_current.return_value = False
            win.folder_view.defer_reload_if_editing.return_value = False
            win.folder_view.capture_scroll_state.return_value = {"value": 37, "maximum": 120}
            win.folder_view.get_state.return_value = (["/root"], ["/root/A"])
            win._dismiss_folder_callout = MagicMock()
            return win, MainWindow

    def test_restore_scroll_after_rebuild_without_selection_scroll(self):
        win, MainWindow = self._make_win()

        MainWindow._reload_folderlist_now(win)

        assert win.folder_view.method_calls == [
            call.is_structure_current(["/root"], ["/ignored"]),
            call.defer_reload_if_editing(ANY, strong=True),
            call.capture_scroll_state(),
            call.get_state(),
            call.set_folders(["/root"], ["/ignored"]),
            call.set_state((["/root"], ["/root/A"]), scroll_to_selection=False),
            call.restore_scroll_state({"value": 37, "maximum": 120}),
        ]
        win._dismiss_folder_callout.assert_called_once()

    def test_skip_rebuild_when_structure_is_current(self):
        win, MainWindow = self._make_win()
        win.folder_view.is_structure_current.return_value = True

        MainWindow._reload_folderlist_now(win)

        win.folder_view.is_structure_current.assert_called_once_with(["/root"], ["/ignored"])
        win.folder_view.capture_scroll_state.assert_not_called()
        win.folder_view.set_folders.assert_not_called()
        win._dismiss_folder_callout.assert_called_once()

    def test_defer_rebuild_while_editing(self):
        win, MainWindow = self._make_win()
        win.folder_view.defer_reload_if_editing.return_value = True

        MainWindow._reload_folderlist_now(win)

        win.folder_view.is_structure_current.assert_called_once_with(["/root"], ["/ignored"])
        win.folder_view.defer_reload_if_editing.assert_called_once_with(ANY, strong=True)
        win.folder_view.capture_scroll_state.assert_not_called()
        win.folder_view.set_folders.assert_not_called()
        win._dismiss_folder_callout.assert_not_called()


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


class TestPanelLayoutReset:
    def test_restores_default_layout_and_saves_slot(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            default_layout = {"mode": "locked", "tree": {"root": None, "floating": {}}}
            win._load_default_layout = MagicMock(return_value=default_layout)
            win._layout_manager = MagicMock()
            win._save_slot = MagicMock()

            win.reset_panel_layout_to_default()

        win._load_default_layout.assert_called_once_with()
        win._layout_manager.reset_to_default.assert_called_once_with(default_layout)
        win._save_slot.assert_called_once_with()

    def test_reset_floating_positions_saves_slot_when_repositioned(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._layout_manager = MagicMock()
            win._layout_manager.reset_floating_positions.return_value = 2
            win._save_slot = MagicMock()

            result = win.reset_floating_positions()

        assert result == 2
        win._layout_manager.reset_floating_positions.assert_called_once_with()
        win._save_slot.assert_called_once_with()

    def test_reset_floating_positions_skips_save_when_none(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._layout_manager = MagicMock()
            win._layout_manager.reset_floating_positions.return_value = 0
            win._save_slot = MagicMock()

            result = win.reset_floating_positions()

        assert result == 0
        win._layout_manager.reset_floating_positions.assert_called_once_with()
        win._save_slot.assert_not_called()


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


class TestQueryMenu:
    def test_show_query_menu_opens_query_folder(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            menu_spec = MagicMock()
            session = MagicMock()
            session.from_folder.return_value = menu_spec

            with patch("wafer.app.viewer.mainwindow.Menu.session", return_value=session):
                win._show_query_menu()

            session.from_folder.assert_called_once_with("Query")
            menu_spec.exec.assert_called_once_with()


class TestFolderCallout:
    def test_check_folder_callout_uses_add_folder_button_attr(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            add_btn = MagicMock()
            add_btn.pressed = MagicMock()
            win._add_folder_btn = add_btn
            win._folder_callout = None
            win._on_folder_callout_dismissed = MagicMock()
            win._show_folder_callout = MagicMock()
            win._dismiss_folder_callout = MagicMock()

            callout = MagicMock()
            callout.dismissed = MagicMock()
            callout.dismissed.connect = MagicMock()

            with patch("wafer.app.viewer.mainwindow.CalloutOverlay", return_value=callout), patch("wafer.app.viewer.mainwindow.QtCore.QTimer.singleShot") as single_shot:
                win._check_folder_callout([])

            add_btn.pressed.connect.assert_called_once_with(win._dismiss_folder_callout)
            single_shot.assert_called_once()


class TestPanelPluginStartup:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            return MainWindow.__new__(MainWindow), MainWindow

    def test_runs_all_panel_plugin_startups(self):
        win, MainWindow = self._make_win()
        from wafer.plugin.panel.base import BasePanelPlugin

        class ViewerPlugin(BasePanelPlugin):
            NAME = "viewer_panel"
            SCOPE = "viewer"

            def __init__(self):
                self.calls = 0

            def startup(self):
                self.calls += 1

            def create_widget(self):
                return MagicMock()

        class GlobalPlugin(BasePanelPlugin):
            NAME = "global_panel"
            SCOPE = "*"

            def __init__(self):
                self.calls = 0

            def startup(self):
                self.calls += 1

            def create_widget(self):
                return MagicMock()

        class TrayPlugin(BasePanelPlugin):
            NAME = "tray_panel"
            SCOPE = "tray"

            def __init__(self):
                self.calls = 0

            def startup(self):
                self.calls += 1

            def create_widget(self):
                return MagicMock()

        viewer_plugin = ViewerPlugin()
        global_plugin = GlobalPlugin()
        tray_plugin = TrayPlugin()

        registry = MagicMock()
        registry.list_all.return_value = [
            ViewerPlugin,
            GlobalPlugin,
            TrayPlugin,
        ]
        registry.instance.side_effect = lambda name: {
            "viewer_panel": viewer_plugin,
            "global_panel": global_plugin,
            "tray_panel": tray_plugin,
        }[name]

        with patch("wafer.plugin.panel.handler.panel_registry", registry):
            MainWindow._run_panel_plugin_startups(win)

        assert viewer_plugin.calls == 1
        assert global_plugin.calls == 1
        assert tray_plugin.calls == 1

    def test_logs_and_continues_when_panel_plugin_startup_fails(self):
        win, MainWindow = self._make_win()
        from wafer.plugin.panel.base import BasePanelPlugin

        class FailingPlugin(BasePanelPlugin):
            NAME = "broken_panel"
            SCOPE = "viewer"

            def startup(self):
                raise RuntimeError("boom")

            def create_widget(self):
                return MagicMock()

        class HealthyPlugin(BasePanelPlugin):
            NAME = "healthy_panel"
            SCOPE = "viewer"

            def __init__(self):
                self.calls = 0

            def startup(self):
                self.calls += 1

            def create_widget(self):
                return MagicMock()

        failing_plugin = FailingPlugin()
        healthy_plugin = HealthyPlugin()

        registry = MagicMock()
        registry.list_all.return_value = [
            FailingPlugin,
            HealthyPlugin,
        ]
        registry.instance.side_effect = lambda name: {
            "broken_panel": failing_plugin,
            "healthy_panel": healthy_plugin,
        }[name]

        with patch("wafer.plugin.panel.handler.panel_registry", registry), patch(
            "wafer.app.viewer.mainwindow.AppLogger.warning"
        ) as warning:
            MainWindow._run_panel_plugin_startups(win)

        assert healthy_plugin.calls == 1
        warning.assert_called_once()

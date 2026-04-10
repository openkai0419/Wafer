import py_compile
from unittest.mock import MagicMock, patch


def test_compile():
    py_compile.compile("wafer/app/viewer/mainwindow.py")


class TestUpdateTitle:
    def _make_win(self, profile_entry=None, db_name="default", selected_paths=None):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._profile_entry = profile_entry
            win.database_name = db_name
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = selected_paths or []
            win.setWindowTitle = MagicMock()
            return win

    def _named_entry(self, name="Work"):
        from wafer.core.profile import ProfileEntry

        return ProfileEntry(profile_id="abc123", name=name)

    def _unnamed_entry(self):
        from wafer.core.profile import ProfileEntry

        return ProfileEntry(profile_id="s1", name="")

    def test_named_profile_shows_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(profile_entry=self._named_entry("Work"), db_name="mydb", selected_paths=["/a/photos"])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("Work")

    def test_unnamed_with_folders_shows_folder_names(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(profile_entry=self._unnamed_entry(), selected_paths=["/home/user/photos", "/mnt/data/images"])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("photos, images")

    def test_unnamed_no_folders_shows_db_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(profile_entry=self._unnamed_entry(), db_name="mydb", selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("mydb")

    def test_unnamed_no_folders_no_db_shows_app_name(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(profile_entry=self._unnamed_entry(), db_name="", selected_paths=[])
        win._update_title()
        win.setWindowTitle.assert_called_once_with(APP_NAME)

    def test_no_profile_entry_shows_folder_names(self):
        from wafer.app.viewer.mainwindow import APP_NAME

        win = self._make_win(profile_entry=None, selected_paths=["/data/pics"])
        win._update_title()
        win.setWindowTitle.assert_called_once_with("pics")


class TestSearchResultDiffCheck:
    def test_skip_when_paths_unchanged(self):
        from unittest.mock import MagicMock, patch

        paths = ["a.png", "b.png"]
        sources = ["a.png", "b.png"]
        aspects = [1.0, 1.5]

        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._last_paths = paths
            win._folder_changed = False
            win.grid_view = MagicMock()
            win.file_model = MagicMock()
            win.overlay_stack = MagicMock()
            win.loading_indicator = MagicMock()
            win.search_row_widget = MagicMock()
            win.database_path = "test.db"
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []

            win._on_search_finished(paths, sources, aspects)
            win.grid_view.set_paths.assert_not_called()
            win.file_model.set_items.assert_not_called()
            win.loading_indicator.stop.assert_called_once()
            win.overlay_stack.hide_persistent.assert_called_once_with("loading")
            win.search_row_widget.run_folder_worker.assert_called_once()

    def test_update_when_paths_changed(self):
        from unittest.mock import MagicMock, patch

        old_paths = ["a.png"]
        new_paths = ["a.png", "b.png"]
        sources = ["a.png", "b.png"]
        aspects = [1.0, 1.5]

        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._last_paths = old_paths
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

            win._on_search_finished(new_paths, sources, aspects)
            win.grid_view.set_paths.assert_called_once()
            assert win._last_paths is new_paths
            win.search_row_widget.run_folder_worker.assert_called_once()

    def test_first_search_always_updates(self):
        from unittest.mock import MagicMock, patch

        paths = ["a.png"]
        sources = ["a.png"]
        aspects = [1.0]

        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._last_paths = None
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

            win._on_search_finished(paths, sources, aspects)
            win.grid_view.set_paths.assert_called_once()
            assert win._last_paths is paths
            win.search_row_widget.run_folder_worker.assert_called_once()


class TestOnDbContentUpdated:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.search_row_widget = MagicMock()
            win.search_row_widget.get_sort.return_value = ("path", True)
            win.search_row_widget.get_values.return_value = {}
            win.search_service = MagicMock()
            win.search_service.get.return_value = True
            win.search_service.params = {}
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.database_path = "test.db"
            win.database_name = "testdb"
            return win

    def test_invalidates_key_cache(self):
        win = self._make_win()
        win._on_db_content_updated("testdb")
        win.search_row_widget.invalidate_key_cache.assert_called_once()

    def test_triggers_force_search(self):
        win = self._make_win()
        win._on_db_content_updated("testdb")
        win.search_service.execute.assert_called_once_with(force=True)

    def test_ignores_other_db(self):
        win = self._make_win()
        win._on_db_content_updated("other_db")
        win.search_row_widget.invalidate_key_cache.assert_not_called()

    def test_empty_db_passes_through(self):
        win = self._make_win()
        win._on_db_content_updated("")
        win.search_row_widget.invalidate_key_cache.assert_called_once()


class TestSyncProfileButton:
    def _make_win(self, profile_entry=None):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win._profile_entry = profile_entry
            win.database_name = "default"
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.setWindowTitle = MagicMock()
            win._profile_button = MagicMock()
            return win

    def test_named_profile_shows_name_on_button(self):
        from wafer.core.profile import ProfileEntry

        entry = ProfileEntry(profile_id="s1", name="Work")
        win = self._make_win(profile_entry=entry)
        win._sync_profile_button()
        win._profile_button.setText.assert_called_with("\u25bc Work")

    def test_unnamed_session_shows_window(self):
        from wafer.core.profile import ProfileEntry

        entry = ProfileEntry(profile_id="s1", name="")
        win = self._make_win(profile_entry=entry)
        win._sync_profile_button()
        win._profile_button.setText.assert_called_with("\u25bc Window")

    def test_colored_profile_sets_stylesheet(self):
        from wafer.core.profile import ProfileEntry

        entry = ProfileEntry(profile_id="s1", name="Work", color="#4A90D9")
        win = self._make_win(profile_entry=entry)
        win._sync_profile_button()
        call_args = win._profile_button.setStyleSheet.call_args[0][0]
        assert "#4A90D9" in call_args

    def test_no_color_default_stylesheet(self):
        from wafer.core.profile import ProfileEntry

        entry = ProfileEntry(profile_id="s1", name="Work")
        win = self._make_win(profile_entry=entry)
        win._sync_profile_button()
        call_args = win._profile_button.setStyleSheet.call_args[0][0]
        assert "#4A90D9" not in call_args

    def test_update_title_calls_sync(self):
        from wafer.core.profile import ProfileEntry

        entry = ProfileEntry(profile_id="s1", name="Test")
        win = self._make_win(profile_entry=entry)
        win._update_title()
        win._profile_button.setText.assert_called()


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
        win.window_state.minimize.assert_not_called()

    def test_show_false_minimizes_window(self):
        win = self._make_win()
        win.toggle_show("testdb", False)
        win.window_state.minimize.assert_called_once()
        win.window_state.restore_or_activate.assert_not_called()

    def test_hidden_window_gets_shown(self):
        win = self._make_win()
        win.isVisible.return_value = False
        win.toggle_show("testdb", True)
        win.window_state.restore_or_activate.assert_called_once()
        win.window_state.minimize.assert_not_called()

    def test_respects_show_arg(self):
        win = self._make_win()
        win.toggle_show("testdb", True)
        win.window_state.restore_or_activate.assert_called_once()
        win.window_state.restore_or_activate.reset_mock()
        win.toggle_show("testdb", False)
        win.window_state.minimize.assert_called_once()

    def test_ignores_other_db(self):
        win = self._make_win()
        win.toggle_show("other_db", True)
        win.window_state.restore_or_activate.assert_not_called()
        win.window_state.minimize.assert_not_called()


class TestRaiseWindow:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.window_state = MagicMock()
            return win

    def test_always_calls_restore_or_activate(self):
        win = self._make_win()
        win.raise_window()
        win.window_state.restore_or_activate.assert_called_once()


class TestSwitchProfile:
    def _make_win(self, profile_id="p1", profile_name="Old"):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow
            from wafer.core.profile import ProfileEntry, ProfileStore

            win = MainWindow.__new__(MainWindow)
            win.profile_id = profile_id
            win._profile_entry = ProfileEntry(profile_id=profile_id, name=profile_name)
            win._profile_ready = True
            win._profile_deleted = False
            win._profile_store = MagicMock(spec=ProfileStore)
            win._node = MagicMock()
            win.setWindowTitle = MagicMock()
            win._profile_button = MagicMock()
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.database_name = "default"
            win.database_path = "test.db"
            win.search_service = MagicMock()
            win.search_service.params = {}
            win.search_service.get.return_value = True
            win.search_row_widget = MagicMock()
            win.search_row_widget.get_sort.return_value = ("path", True)
            win.search_row_widget.get_values.return_value = {}
            win._last_paths = None
            win._folder_changed = False
            win._db_reload_cancel = None
            win.progress_bar = MagicMock()
            win.loading_indicator = MagicMock()
            win.overlay_stack = MagicMock()
            win.grid_view = MagicMock()
            win._dispatcher = MagicMock()
            win.window_state = MagicMock()
            return win

    def test_noop_when_same_profile(self):
        win = self._make_win(profile_id="p1")
        win._profile_store.get_profile = MagicMock()
        win.switch_profile("p1")
        win._profile_store.get_profile.assert_not_called()

    def test_saves_old_and_restores_new(self):
        from wafer.core.profile import ProfileEntry

        new_entry = ProfileEntry(profile_id="p2", name="New")
        win = self._make_win(profile_id="p1")
        win._profile_store.get_profile.return_value = new_entry
        win._profile_store.save_profile = MagicMock()
        win.switch_profile("p2")
        win._profile_store.save_profile.assert_called_once()
        assert win.profile_id == "p2"
        assert win._profile_entry is new_entry
        win.setWindowTitle.assert_called()

    def test_re_registers_node(self):
        from wafer.core.profile import ProfileEntry

        new_entry = ProfileEntry(profile_id="p2", name="New")
        win = self._make_win(profile_id="p1")
        win._profile_store.get_profile.return_value = new_entry
        win.switch_profile("p2")
        win._node.re_register.assert_called_once_with("p2")

    def test_noop_when_profile_not_found(self):
        win = self._make_win(profile_id="p1")
        win._profile_store.get_profile.return_value = None
        win.switch_profile("p_missing")
        assert win.profile_id == "p1"


class TestRestoreFromProfileSkipWindow:
    def _make_win(self):
        with patch("wafer.app.viewer.mainwindow.MainWindow.__init__", lambda self, *a, **kw: None):
            from wafer.app.viewer.mainwindow import MainWindow

            win = MainWindow.__new__(MainWindow)
            win.database_name = "default"
            win.database_path = "test.db"
            win.search_service = MagicMock()
            win.search_service.params = {}
            win.search_service.get.return_value = True
            win.search_row_widget = MagicMock()
            win.search_row_widget.get_sort.return_value = ("path", True)
            win.search_row_widget.get_values.return_value = {}
            win._last_paths = None
            win._folder_changed = False
            win._db_reload_cancel = None
            win.progress_bar = MagicMock()
            win.loading_indicator = MagicMock()
            win.overlay_stack = MagicMock()
            win.grid_view = MagicMock()
            win.folder_view = MagicMock()
            win.folder_view.get_selected_paths.return_value = []
            win.window_state = MagicMock()
            win.restore_ui_state = MagicMock()
            win.restore_query_state = MagicMock()
            win.reload_database = MagicMock(side_effect=lambda name, on_complete=None: on_complete() if on_complete else None)
            return win

    def test_skip_window_state_true(self):
        from wafer.core.profile import ProfileEntry, UIState

        entry = ProfileEntry(
            profile_id="p1",
            name="Test",
            ui=UIState(window_state={"geometry": "abc"}, component_states={"grid": {"zoom": 100}}),
        )
        win = self._make_win()
        win._restore_from_profile(entry, skip_window_state=True)
        call_args = win.restore_ui_state.call_args[0][0]
        assert call_args.window_state is None or call_args.window_state == {}
        assert call_args.component_states == {"grid": {"zoom": 100}}

    def test_skip_window_state_false(self):
        from wafer.core.profile import ProfileEntry, UIState

        ui = UIState(window_state={"geometry": "abc"}, component_states={"grid": {"zoom": 100}})
        entry = ProfileEntry(profile_id="p1", name="Test", ui=ui)
        win = self._make_win()
        win._restore_from_profile(entry, skip_window_state=False)
        call_args = win.restore_ui_state.call_args[0][0]
        assert call_args.window_state == {"geometry": "abc"}

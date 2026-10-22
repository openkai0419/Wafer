from unittest.mock import MagicMock, call, patch

import pytest


class TestDirectLaunch:
    def launch(self, restore_ids, *argv):
        store = MagicMock()
        store.get_restore_slot_ids.return_value = restore_ids
        store.get_restore_webui.return_value = False
        order = MagicMock()
        order.claim.return_value = "lock"
        with (
            patch("main._create_app") as create,
            patch("main._wait_install_then_load_plugins", order.wait),
            patch("main._sync_explorer_menu"),
            patch("main.AppProcess"),
            patch("main._entry_viewer") as viewer,
            patch("main._entry_launcher", order.launcher),
            patch("wafer.app.viewer.workspace_launch.claim_workspace", order.claim),
            patch("wafer.app.viewer.workspace_launch.AppProcess") as spawner,
            patch("wafer.core.store.workspace.WorkspaceStore.instance", return_value=store),
            patch("sys.argv", ["main.py", *argv]),
        ):
            from main import main

            main()
        order.create = create
        return create.return_value, viewer, spawner, order

    def test_no_restore_ids_claims_a_new_workspace(self):
        app, viewer, spawner, order = self.launch([])
        order.claim.assert_called_once_with(None)
        viewer.assert_called_once_with(app, lock="lock")
        spawner.new_main.assert_not_called()

    def test_single_restore_id(self):
        app, viewer, spawner, order = self.launch(["s1"])
        order.claim.assert_called_once_with("s1")
        viewer.assert_called_once_with(app, lock="lock")
        spawner.new_main.assert_not_called()

    def test_multiple_restore_ids(self):
        app, viewer, spawner, order = self.launch(["s1", "s2", "Work"])
        viewer.assert_called_once_with(app, lock="lock")
        assert spawner.new_main.call_args_list == [call("--viewer", "--slot", "s2"), call("--viewer", "--slot", "Work")]

    def test_the_first_workspace_is_claimed_before_plugins_load(self):
        _, _, _, order = self.launch(["s1"])
        assert [name for name, _, _ in order.mock_calls if name in ("claim", "wait")] == ["claim", "wait"]

    def test_an_open_first_workspace_exits_before_plugins_load_and_brings_the_others_forward(self):
        store = MagicMock()
        store.get_restore_slot_ids.return_value = ["s1", "s2"]
        store.get_restore_webui.return_value = False
        with (
            patch("main._create_app"),
            patch("main._wait_install_then_load_plugins") as wait,
            patch("main._sync_explorer_menu"),
            patch("main.AppProcess"),
            patch("main._entry_viewer") as viewer,
            patch("wafer.app.viewer.workspace_launch.claim_workspace", return_value=None),
            patch("wafer.app.viewer.workspace_launch.AppProcess") as spawner,
            patch("wafer.core.store.workspace.WorkspaceStore.instance", return_value=store),
            patch("sys.argv", ["main.py"]),
        ):
            from main import main

            with pytest.raises(SystemExit) as exited:
                main()
        assert exited.value.code == 0
        wait.assert_not_called()
        viewer.assert_not_called()
        assert spawner.new_main.call_args_list == [call("--viewer", "--slot", "s2")]

    def test_file_path_hands_over_to_the_launcher_without_becoming_a_viewer(self, tmp_path):
        file_path = tmp_path / "a.png"
        file_path.write_bytes(b"x")
        _, viewer, spawner, order = self.launch(["s1", "s2"], str(file_path))
        order.launcher.assert_called_once_with(str(file_path))
        order.create.assert_not_called()
        viewer.assert_not_called()
        order.claim.assert_not_called()
        order.wait.assert_not_called()
        spawner.new_main.assert_not_called()

    def test_folder_path_falls_back_to_a_normal_launch(self, tmp_path):
        app, viewer, spawner, order = self.launch(["s1", "s2"], str(tmp_path))
        order.launcher.assert_not_called()
        order.claim.assert_called_once_with("s1")
        viewer.assert_called_once_with(app, lock="lock")
        assert spawner.new_main.call_args_list == [call("--viewer", "--slot", "s2")]


class TestLauncher:
    def test_shows_the_picker_without_shared_opengl_or_plugins(self):
        order = MagicMock()
        with (
            patch("main._create_app", order.create),
            patch("main._ensure_tray_unless_pending", order.ensure_tray),
            patch("main._sync_explorer_menu", order.sync_menu),
            patch("main._load_plugins", order.load_plugins),
            patch("main.setproctitle"),
            patch("wafer.app.viewer.workspace_launch.run_open_path", order.open_path),
        ):
            from main import _entry_launcher

            _entry_launcher("C:/a.png")
        assert order.mock_calls == [
            call.create(shared_opengl=False),
            call.ensure_tray(),
            call.sync_menu(),
            call.open_path(order.create.return_value, "C:/a.png"),
        ]


class TestCreateApp:
    @pytest.mark.parametrize("shared_opengl", [True, False])
    def test_shared_opengl_contexts_only_when_asked(self, shared_opengl):
        with (
            patch("main._enable_shared_opengl_contexts") as enable,
            patch("PySide6.QtWidgets.QApplication"),
            patch("wafer.qt.common.app_icon.get_icon"),
            patch("wafer.qt.common.tooltip.install_instant_tooltips"),
        ):
            from main import _create_app

            _create_app(shared_opengl=shared_opengl)
        assert enable.called is shared_opengl


class TestTrayStartup:
    @patch("main._entry_tray")
    @patch("main._bootstrap_plugins_for_tray")
    def test_tray_mode_delegates_only_to_entry_tray(self, mock_bootstrap, mock_entry_tray):
        with patch("main.argparse.ArgumentParser.parse_args") as mock_args:
            mock_args.return_value = MagicMock(
                tray=True,
                viewer=False,
                webui=False,
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
    @patch("wafer.qt.common.tooltip.install_instant_tooltips")
    @patch("PySide6.QtWidgets.QApplication")
    @patch("wafer.qt.common.app_icon.get_icon")
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


@patch("main.constants.MEMWATCH", False)
@patch("wafer.core.profiling.profiler")
@patch("main.setproctitle")
class TestEntryViewer:
    def test_runs_the_viewer_with_the_claimed_lock(self, _title, _profiler):
        app, lock = MagicMock(), MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_viewer") as run:
            from main import _entry_viewer

            _entry_viewer(app, lock=lock)

        run.assert_called_once_with(app, lock, open_request=None)

    def test_passes_the_open_request_to_the_viewer(self, _title, _profiler):
        app, lock, request = MagicMock(), MagicMock(), MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_viewer") as run:
            from main import _entry_viewer

            _entry_viewer(app, lock=lock, open_request=request)

        run.assert_called_once_with(app, lock, open_request=request)

    def test_pick_hands_over_to_the_picker(self, _title, _profiler):
        app = MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_pick", side_effect=SystemExit) as pick:
            from main import _entry_viewer

            with pytest.raises(SystemExit):
                _entry_viewer(app, pick=True, seed_slot="s1")

        pick.assert_called_once_with(app, "s1")


class TestViewerArguments:
    def run_viewer_args(self, *argv, lock="lock", order=None):
        order = order or MagicMock()
        order.claim.return_value = lock
        with (
            patch("main._create_app") as create,
            patch("main._wait_install_then_load_plugins", order.wait),
            patch("main._entry_viewer", order.viewer),
            patch("wafer.app.viewer.workspace_launch.claim_workspace", order.claim),
            patch("wafer.app.viewer.workspace_launch.send_open_request", order.send),
            patch("sys.argv", ["main.py", "--viewer", *argv]),
        ):
            from main import main

            main()
        return create.return_value, order

    def test_pick_flags_reach_the_viewer_entry_without_claiming(self):
        app, order = self.run_viewer_args("--pick", "--seed-slot", "s1")
        order.claim.assert_not_called()
        order.viewer.assert_called_once_with(app, lock=None, pick=True, seed_slot="s1", open_request=None)

    def test_slot_is_claimed_before_plugins_load(self):
        app, order = self.run_viewer_args("--slot", "s1")
        assert order.mock_calls == [call.claim("s1"), call.wait(app), call.viewer(app, lock="lock", pick=False, seed_slot=None, open_request=None)]

    def test_an_open_slot_exits_before_plugins_load(self):
        with pytest.raises(SystemExit) as exited:
            self.run_viewer_args("--slot", "s1", lock=None)
        assert exited.value.code == 0

    def test_open_path_reaches_the_viewer_with_its_database(self):
        from wafer.app.viewer.workspace_launch import OpenRequest

        app, order = self.run_viewer_args("--slot", "s1", "--open-path", "C:/a b.png", "--open-database", "db")
        request = OpenRequest("C:/a b.png", "db")
        assert order.mock_calls == [call.claim("s1"), call.wait(app), call.viewer(app, lock="lock", pick=False, seed_slot=None, open_request=request)]

    def test_open_path_to_a_taken_workspace_is_sent_to_its_window(self):
        from wafer.app.viewer.workspace_launch import OpenRequest

        store = MagicMock()
        taken_slot = store.get_slot.return_value
        order = MagicMock()
        with patch("wafer.core.store.workspace.WorkspaceStore.instance", return_value=store):
            with pytest.raises(SystemExit) as exited:
                self.run_viewer_args("--slot", "s1", "--open-path", "C:/a.png", lock=None, order=order)
        assert exited.value.code == 0
        store.get_slot.assert_called_once_with("s1")
        order.send.assert_called_once_with(taken_slot, OpenRequest("C:/a.png", ""))
        order.wait.assert_not_called()

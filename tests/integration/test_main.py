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
            patch("wafer.app.viewer.workspace_launch.claim_workspace", order.claim),
            patch("wafer.app.viewer.workspace_launch.AppProcess") as spawner,
            patch("wafer.core.store.workspace.WorkspaceStore.instance", return_value=store),
            patch("sys.argv", ["main.py", *argv]),
        ):
            from main import main

            main()
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
        assert [name for name, _, _ in order.mock_calls] == ["claim", "wait"]

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

    def test_file_path_opens_through_the_picker_without_restoring(self, tmp_path):
        file_path = tmp_path / "a.png"
        file_path.write_bytes(b"x")
        app, viewer, spawner, order = self.launch(["s1", "s2"], str(file_path))
        viewer.assert_called_once_with(app, open_path=str(file_path))
        order.claim.assert_not_called()
        order.wait.assert_called_once()
        spawner.new_main.assert_not_called()

    def test_folder_path_falls_back_to_a_normal_launch(self, tmp_path):
        app, viewer, spawner, order = self.launch(["s1", "s2"], str(tmp_path))
        order.claim.assert_called_once_with("s1")
        viewer.assert_called_once_with(app, lock="lock")
        assert spawner.new_main.call_args_list == [call("--viewer", "--slot", "s2")]


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
    @patch("main.get_icon")
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
@patch("main.profiler")
@patch("main.setproctitle")
class TestEntryViewer:
    def test_runs_the_viewer_with_the_claimed_lock(self, _title, _profiler):
        app, lock = MagicMock(), MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_viewer") as run:
            from main import _entry_viewer

            _entry_viewer(app, lock=lock)

        run.assert_called_once_with(app, lock)

    def test_pick_hands_over_to_the_picker(self, _title, _profiler):
        app = MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_pick", side_effect=SystemExit) as pick:
            from main import _entry_viewer

            with pytest.raises(SystemExit):
                _entry_viewer(app, pick=True, seed_slot="s1")

        pick.assert_called_once_with(app, "s1")

    def test_open_path_hands_over_to_the_path_launcher(self, _title, _profiler):
        app = MagicMock()
        with patch("wafer.app.viewer.workspace_launch.run_open_path", side_effect=SystemExit) as open_path:
            from main import _entry_viewer

            with pytest.raises(SystemExit):
                _entry_viewer(app, open_path="C:/a.png")

        open_path.assert_called_once_with(app, "C:/a.png")


class TestViewerArguments:
    def run_viewer_args(self, *argv, lock="lock"):
        order = MagicMock()
        order.claim.return_value = lock
        with (
            patch("main._create_app") as create,
            patch("main._wait_install_then_load_plugins", order.wait),
            patch("main._entry_viewer", order.viewer),
            patch("wafer.app.viewer.workspace_launch.claim_workspace", order.claim),
            patch("sys.argv", ["main.py", "--viewer", *argv]),
        ):
            from main import main

            main()
        return create.return_value, order

    def test_pick_flags_reach_the_viewer_entry_without_claiming(self):
        app, order = self.run_viewer_args("--pick", "--seed-slot", "s1")
        order.claim.assert_not_called()
        order.viewer.assert_called_once_with(app, lock=None, pick=True, seed_slot="s1")

    def test_slot_is_claimed_before_plugins_load(self):
        app, order = self.run_viewer_args("--slot", "s1")
        assert order.mock_calls == [call.claim("s1"), call.wait(app), call.viewer(app, lock="lock", pick=False, seed_slot=None)]

    def test_an_open_slot_exits_before_plugins_load(self):
        with pytest.raises(SystemExit) as exited:
            self.run_viewer_args("--slot", "s1", lock=None)
        assert exited.value.code == 0

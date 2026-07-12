from unittest.mock import MagicMock, patch

from wafer.app.lifecycle import CloseReason
from wafer.builtins.commands import window as window_commands


class _Ctx:
    def __init__(self, **instances):
        self._instances = dict(instances)

    def get_instance(self, name):
        return self._instances.get(name)


class TestCloseAll:
    def test_delegates_to_tray_when_tray_instance_present(self):
        tray = MagicMock()
        window_commands.close_all(_Ctx(Tray=tray))
        tray.close_all.assert_called_once_with()

    def test_sends_quit_all_to_tray_when_tray_process_exists(self):
        win = MagicMock()
        with patch.object(window_commands.AppProcess, "get_by_args_subset", return_value=[object()]) as sub, \
                patch.object(window_commands.AppProcess, "force_close_all") as force:
            window_commands.close_all(_Ctx(MainWindow=win))

        sub.assert_called_once_with("--tray")
        win._node.send.assert_called_once_with("app.quit_all", dst="tray")
        force.assert_not_called()
        win.close.assert_not_called()

    def test_force_closes_when_tray_process_missing(self):
        win = MagicMock()
        with patch.object(window_commands.AppProcess, "get_by_args_subset", return_value=[]), \
                patch.object(window_commands.AppProcess, "force_close_all") as force:
            window_commands.close_all(_Ctx(MainWindow=win))

        force.assert_called_once_with()
        assert win._close_reason == CloseReason.SHUTDOWN
        win.close.assert_called_once_with()
        win._node.send.assert_not_called()

    def test_noop_without_window_or_tray(self):
        window_commands.close_all(_Ctx())

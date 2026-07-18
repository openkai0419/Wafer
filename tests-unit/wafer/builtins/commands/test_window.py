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


class TestRestartAllPendingInstall:
    def _patch_common(self, monkeypatch, store, *, pending):
        monkeypatch.setattr(window_commands, "WorkspaceStore", MagicMock(instance=staticmethod(lambda: store)))
        monkeypatch.setattr("wafer.plugin.settings.PluginSettings.clear_restart_scope", lambda self: None)
        monkeypatch.setattr(window_commands.installer_queue, "has_pending_queue", lambda _dir: pending)
        monkeypatch.setattr(window_commands, "get_plugin_dir", lambda: "/ext")
        monkeypatch.setattr(window_commands, "Notifier", MagicMock())

    def test_pending_delegates_to_tray_instance(self, monkeypatch):
        store = MagicMock()
        store.get_active_slot_ids.return_value = ["s1", "s2"]
        self._patch_common(monkeypatch, store, pending=True)
        monkeypatch.setattr(window_commands.AppProcess, "force_close_all", staticmethod(lambda: (_ for _ in ()).throw(AssertionError("should not force close"))))
        monkeypatch.setattr(window_commands.AppProcess, "new_main", staticmethod(lambda *a: (_ for _ in ()).throw(AssertionError("should not spawn"))))

        tray = MagicMock()
        win = MagicMock()
        window_commands.restart_all(_Ctx(Tray=tray, MainWindow=win))

        store.set_restore_slot_ids.assert_called_once_with(["s1", "s2"])
        tray.restart_all.assert_called_once_with()
        win.close.assert_not_called()

    def test_pending_delegates_to_tray_via_ipc(self, monkeypatch):
        store = MagicMock()
        store.get_active_slot_ids.return_value = ["s1"]
        self._patch_common(monkeypatch, store, pending=True)
        monkeypatch.setattr(window_commands.AppProcess, "get_by_args_subset", staticmethod(lambda *a: [object()]))
        monkeypatch.setattr(window_commands.AppProcess, "force_close_all", staticmethod(lambda: (_ for _ in ()).throw(AssertionError("should not force close"))))

        win = MagicMock()
        window_commands.restart_all(_Ctx(MainWindow=win))

        store.set_restore_slot_ids.assert_called_once_with(["s1"])
        win._node.send.assert_called_once_with("app.restart_all", dst="tray")
        win.close.assert_not_called()

    def test_pending_force_terminates_when_tray_unreachable(self, monkeypatch):
        store = MagicMock()
        store.get_active_slot_ids.return_value = ["s1", "s2"]
        self._patch_common(monkeypatch, store, pending=True)
        monkeypatch.setattr(window_commands.AppProcess, "get_by_args_subset", staticmethod(lambda *a: []))

        calls = []
        monkeypatch.setattr(window_commands.AppProcess, "force_close_all", staticmethod(lambda: calls.append("force")))
        monkeypatch.setattr(window_commands.AppProcess, "new_main", staticmethod(lambda *a: calls.append(("new_main", a))))

        win = MagicMock()
        window_commands.restart_all(_Ctx(MainWindow=win))

        store.set_restore_slot_ids.assert_called_once_with(["s1", "s2"])
        assert calls == ["force", ("new_main", ())]
        assert win._close_reason == CloseReason.SHUTDOWN
        win.close.assert_called_once_with()
        win.close_by_restart.assert_not_called()

    def test_no_pending_uses_system_restart(self, monkeypatch):
        store = MagicMock()
        monkeypatch.setattr(window_commands, "WorkspaceStore", MagicMock(instance=staticmethod(lambda: store)))
        monkeypatch.setattr("wafer.plugin.settings.PluginSettings.clear_restart_scope", lambda self: None)
        monkeypatch.setattr(window_commands.installer_queue, "has_pending_queue", lambda _dir: False)
        monkeypatch.setattr(window_commands.AppProcess, "force_close_all", staticmethod(lambda: (_ for _ in ()).throw(AssertionError("should not force close"))))

        win = MagicMock()
        window_commands.restart_all(_Ctx(MainWindow=win))

        win._perform_system_restart.assert_called_once_with(include_self=True)
        win.close_by_restart.assert_called_once_with()


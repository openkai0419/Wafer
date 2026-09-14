import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6 import QtCore, QtWidgets

from wafer.app.startup import StartupTasks
from wafer.builtins.commands.panel import _find_standalone_panel, open_panel
from wafer.builtins.updater import stage
from wafer.builtins.updater.widget import PANEL_DISPLAY_NAME, UpdateNotifierWidget
from wafer.core.commands.binding.instance_registry import InstanceRegistry
from wafer.ui.layout import standalone


def _process_until(predicate, timeout_ms=3000):
    app = QtWidgets.QApplication.instance()
    deadline = time.monotonic() + timeout_ms / 1000.0
    while not predicate() and time.monotonic() < deadline:
        app.processEvents(QtCore.QEventLoop.AllEvents, 20)
        time.sleep(0.01)


@pytest.fixture(autouse=True)
def _stub_update_network(monkeypatch):
    import wafer.builtins.updater.widget as w

    monkeypatch.setattr(w, "check_for_updates", lambda: SimpleNamespace(info=None))


@pytest.fixture(autouse=True)
def _clean_standalone_registry():
    standalone._standalone_dialogs.clear()
    yield
    for dlg in list(standalone._standalone_dialogs.values()):
        dlg.close()
    standalone._standalone_dialogs.clear()
    app = QtWidgets.QApplication.instance()
    if app:
        app.processEvents()


class TestStandalonePanel:
    def test_find_standalone_panel_matches_display_name(self):
        cls = _find_standalone_panel(PANEL_DISPLAY_NAME.lower())
        assert cls is not None
        assert getattr(cls, "STANDALONE_AVAILABLE", False) is True

    def test_find_standalone_panel_rejects_unknown(self):
        assert _find_standalone_panel("does-not-exist") is None

    def test_open_panel_creates_standalone_dialog_without_mainwindow(self, qtbot):
        assert InstanceRegistry.instance().get_one("MainWindow") is None
        widget = open_panel(name=PANEL_DISPLAY_NAME, toggle=False)
        assert isinstance(widget, QtWidgets.QWidget)
        assert "update" in standalone._standalone_dialogs
        assert widget.window().isVisible()

    def test_open_panel_reuses_visible_dialog(self, qtbot):
        first = open_panel(name=PANEL_DISPLAY_NAME, toggle=False)
        second = open_panel(name=PANEL_DISPLAY_NAME, toggle=False)
        assert first is second
        assert len(standalone._standalone_dialogs) == 1

    def test_open_panel_unknown_name_returns_none(self):
        assert open_panel(name="not-a-real-panel", toggle=False) is None

    def test_standalone_dialog_close_pops_registry(self, qtbot):
        open_panel(name=PANEL_DISPLAY_NAME, toggle=False)
        dlg = standalone._standalone_dialogs["update"]
        dlg.close()
        _process_until(lambda: "update" not in standalone._standalone_dialogs)
        assert "update" not in standalone._standalone_dialogs


class TestUpdaterCloseFromStandalone:
    def test_close_panel_closes_standalone_dialog(self, qtbot):
        widget = UpdateNotifierWidget()
        dlg = QtWidgets.QDialog()
        qtbot.addWidget(dlg)
        QtWidgets.QVBoxLayout(dlg).addWidget(widget)
        dlg.show()
        qtbot.wait(50)
        assert dlg.isVisible()
        widget._close_panel()
        _process_until(lambda: not dlg.isVisible())
        assert not dlg.isVisible()

    def test_close_panel_never_closes_mainwindow(self, qtbot):
        manager = SimpleNamespace(is_panel_visible=lambda name: False, toggled=[])
        manager.toggle_panel = lambda name: manager.toggled.append(name)
        fake_main = SimpleNamespace(_layout_manager=manager)
        InstanceRegistry.instance().register("MainWindow", fake_main)
        try:
            widget = UpdateNotifierWidget()
            dlg = QtWidgets.QDialog()
            qtbot.addWidget(dlg)
            QtWidgets.QVBoxLayout(dlg).addWidget(widget)
            dlg.show()
            qtbot.wait(50)
            widget._close_panel()
            qtbot.wait(50)
            assert dlg.isVisible()
            assert manager.toggled == []
        finally:
            del fake_main
            InstanceRegistry.instance().get_all("MainWindow")


class TestStartupTasks:
    def test_run_dispatches_plugin_prompt_and_update_schedule(self, qtbot, monkeypatch):
        import wafer.builtins.updater.startup as ust
        import wafer.plugin.setup_prompt as sp

        scheduled = []
        checked = []
        monkeypatch.setattr(ust, "schedule_startup_update_check", lambda: scheduled.append(True))
        monkeypatch.setattr(sp, "plugin_setup_needed", lambda: checked.append(True) or False)

        StartupTasks().run()
        _process_until(lambda: checked)

        assert scheduled == [True]
        assert checked == [True]

    def test_headless_logs_available_update(self, monkeypatch):
        import wafer.builtins.updater.startup as ust

        info = SimpleNamespace(latest_version="99.0.0")
        warnings: list[str] = []
        monkeypatch.setattr(ust, "process_apply_results", lambda: None)
        monkeypatch.setattr(ust.state, "is_auto_check_enabled", lambda: True)
        monkeypatch.setattr(ust, "check_for_updates", lambda: SimpleNamespace(info=info))
        monkeypatch.setattr(ust.state, "record_latest_result", lambda v: None)
        monkeypatch.setattr(ust, "should_notify_update", lambda i, skipped: True)
        monkeypatch.setattr(ust.AppLogger, "warning", staticmethod(lambda msg, *a, **k: warnings.append(msg)))

        StartupTasks(headless=True).run()

        assert any("99.0.0" in w for w in warnings)

    def test_headless_no_update_is_quiet(self, monkeypatch):
        import wafer.builtins.updater.startup as ust

        monkeypatch.setattr(ust, "process_apply_results", lambda: None)
        monkeypatch.setattr(ust.state, "is_auto_check_enabled", lambda: True)
        monkeypatch.setattr(ust, "check_for_updates", lambda: SimpleNamespace(info=None))

        StartupTasks(headless=True).run()


class TestRestartIntoLauncher:
    def test_returns_false_without_staged_update(self, qtbot):
        host = QtWidgets.QWidget()
        qtbot.addWidget(host)
        monkeypatched = stage.staged_version() == ""
        assert monkeypatched or stage.get_launcher_path() is None
        assert stage.restart_into_launcher(host) is False

    def _install_stubs(self, monkeypatch):
        monkeypatch.setattr(stage, "get_launcher_path", lambda: Path("launcher.exe"))
        monkeypatch.setattr(stage, "staged_version", lambda *a, **k: "99.0.0")
        popen_calls: list = []
        monkeypatch.setattr(stage.subprocess, "Popen", lambda *a, **k: popen_calls.append(a) or SimpleNamespace())

        class FakeAppProcess:
            terminated: list = []
            waited: list = []

            @staticmethod
            def terminate_cmd(arg, wait=False):
                FakeAppProcess.terminated.append(arg)

            @staticmethod
            def list_viewers():
                return []

            @staticmethod
            def wait_procs_then_kill(procs):
                FakeAppProcess.waited.append(list(procs))

        monkeypatch.setattr("wafer.core.platform.process.AppProcess", FakeAppProcess)
        return popen_calls, FakeAppProcess

    def test_webui_host_without_slot_id_restarts(self, qtbot, monkeypatch):
        popen_calls, _ = self._install_stubs(monkeypatch)
        host = QtWidgets.QWidget()
        qtbot.addWidget(host)
        closed = []
        host.close = lambda: closed.append(True)

        assert stage.restart_into_launcher(host) is True
        assert len(popen_calls) == 1
        assert closed == [True]

    def test_mainwindow_host_shuts_down_other_slots(self, qtbot, monkeypatch):
        from wafer.core.workspace import WorkspaceStore

        popen_calls, _ = self._install_stubs(monkeypatch)
        monkeypatch.setattr(WorkspaceStore, "get_active_slot_ids", lambda self: ["s1", "s2"])
        monkeypatch.setattr(WorkspaceStore, "set_restore_slot_ids", lambda self, ids: None)

        sent: list = []
        node = SimpleNamespace(send=lambda *a, **k: sent.append((a, k)))
        host = QtWidgets.QWidget()
        qtbot.addWidget(host)
        host._node = node
        host.slot_id = "s1"
        host.close = lambda: None

        assert stage.restart_into_launcher(host) is True
        assert len(popen_calls) == 1
        assert [a[0] for a, _ in sent] == ["slot.shutdown"]
        assert [a[1] for a, _ in sent] == ["s2"]

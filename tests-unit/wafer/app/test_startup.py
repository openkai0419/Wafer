from PySide6 import QtCore

import wafer.builtins.updater.startup as updater_startup
import wafer.plugin.setup_prompt as setup_prompt
from wafer.app.startup import StartupTasks


def test_run_headless_logs_update(monkeypatch):
    called = []
    monkeypatch.setattr(updater_startup, "log_startup_update_check", lambda: called.append("log"))
    StartupTasks(headless=True).run()
    assert called == ["log"]


def test_run_ui_schedules_update_and_prompt(monkeypatch):
    scheduled = []
    timers = []
    monkeypatch.setattr(updater_startup, "schedule_startup_update_check", lambda: scheduled.append("update"))
    monkeypatch.setattr(QtCore.QTimer, "singleShot", staticmethod(lambda ms, fn: timers.append((ms, fn))))
    StartupTasks().run()
    assert scheduled == ["update"]
    assert [fn for _, fn in timers] == [StartupTasks.prompt_plugin_setup]


def test_run_ui_defers_prompt_to_on_ready(monkeypatch):
    scheduled = []
    timers = []
    received = []
    monkeypatch.setattr(updater_startup, "schedule_startup_update_check", lambda: scheduled.append("update"))
    monkeypatch.setattr(QtCore.QTimer, "singleShot", staticmethod(lambda ms, fn: timers.append((ms, fn))))
    StartupTasks().run(on_ready=lambda prompt: received.append(prompt))
    assert scheduled == ["update"]
    assert timers == []
    assert received == [StartupTasks.prompt_plugin_setup]


def test_prompt_plugin_setup_opens_panel_when_needed(monkeypatch):
    import wafer.builtins.commands.panel as panel

    opened = []
    monkeypatch.setattr(setup_prompt, "plugin_setup_needed", lambda: True)
    monkeypatch.setattr(panel, "open_panel", lambda **k: opened.append(k))
    StartupTasks.prompt_plugin_setup()
    assert opened == [{"name": "Plugin Manager", "toggle": False}]


def test_prompt_plugin_setup_noop_when_not_needed(monkeypatch):
    import wafer.builtins.commands.panel as panel

    opened = []
    monkeypatch.setattr(setup_prompt, "plugin_setup_needed", lambda: False)
    monkeypatch.setattr(panel, "open_panel", lambda **k: opened.append(k))
    StartupTasks.prompt_plugin_setup()
    assert opened == []

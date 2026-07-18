import py_compile
from pathlib import Path

from wafer.app.tray.main_tray import TrayApp


def test_compile():
    root = Path("wafer/app/tray")
    for p in root.rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        py_compile.compile(str(p), doraise=True)


def test_close_all_waits_for_viewers_then_force_closes_remaining(monkeypatch):
    calls = []

    class _Signal:
        def __init__(self):
            self.emitted = False

        def emit(self):
            self.emitted = True

    class _Node:
        def __init__(self):
            self.sent = []

        def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    class _Thread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    viewers = [object(), object()]
    monkeypatch.setattr("wafer.app.tray.main_tray.threading.Thread", _Thread)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.list_viewers", lambda: viewers)
    monkeypatch.setattr(
        "wafer.app.tray.main_tray.AppProcess.wait_procs_then_kill",
        lambda procs: calls.append(("wait", procs)),
    )
    monkeypatch.setattr(
        "wafer.app.tray.main_tray.AppProcess.force_close_all",
        lambda: calls.append(("force_close_all", None)),
    )
    monkeypatch.setattr(
        "wafer.plugin.settings.PluginSettings.clear_restart_scope",
        lambda self: calls.append(("clear_restart_scope", None)),
    )

    fake = type("FakeTray", (), {})()
    fake._node = _Node()
    fake._close_all_ready = _Signal()

    TrayApp._shutdown_all(fake, then_restart=False)

    assert fake._node.sent == [(("app.shutdown",), {"dst": "viewer"})]
    assert calls == [
        ("clear_restart_scope", None),
        ("wait", viewers),
        ("force_close_all", None),
    ]
    assert fake._close_all_ready.emitted is True


def test_restart_all_shuts_down_then_spawns_root(monkeypatch):
    calls = []

    class _Signal:
        def __init__(self):
            self.emitted = False

        def emit(self):
            self.emitted = True

    class _Node:
        def __init__(self):
            self.sent = []

        def send(self, *args, **kwargs):
            self.sent.append((args, kwargs))

    class _Thread:
        def __init__(self, target=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    viewers = [object()]
    monkeypatch.setattr("wafer.app.tray.main_tray.threading.Thread", _Thread)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.list_viewers", lambda: viewers)
    monkeypatch.setattr(
        "wafer.app.tray.main_tray.AppProcess.wait_procs_then_kill",
        lambda procs: calls.append(("wait", procs)),
    )
    monkeypatch.setattr(
        "wafer.app.tray.main_tray.AppProcess.force_close_all",
        lambda: calls.append(("force_close_all", None)),
    )
    monkeypatch.setattr(
        "wafer.app.tray.main_tray.AppProcess.new_main",
        lambda *a, **kw: calls.append(("new_main", a, kw)),
    )
    monkeypatch.setattr(
        "wafer.plugin.settings.PluginSettings.clear_restart_scope",
        lambda self: calls.append(("clear_restart_scope", None)),
    )

    fake = type("FakeTray", (), {})()
    fake._node = _Node()
    fake._close_all_ready = _Signal()

    TrayApp._shutdown_all(fake, then_restart=True)

    assert fake._node.sent == [(("app.shutdown",), {"dst": "viewer"})]
    assert calls == [
        ("clear_restart_scope", None),
        ("wait", viewers),
        ("force_close_all", None),
        ("new_main", (), {"extra_env": {"WAFER_REPLACE_TRAY": "1"}}),
    ]
    assert fake._close_all_ready.emitted is True

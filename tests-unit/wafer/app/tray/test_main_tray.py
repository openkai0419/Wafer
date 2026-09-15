import py_compile
from pathlib import Path

from wafer.app.tray.main_tray import TrayApp


class _Store:
    def __init__(self):
        self.restore_webui = None

    def set_restore_webui(self, value):
        self.restore_webui = value


def _patch_store(monkeypatch):
    store = _Store()
    monkeypatch.setattr("wafer.core.store.workspace.WorkspaceStore.instance", classmethod(lambda cls: store))
    return store


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
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.get_by_args_subset", lambda *a: [])
    store = _patch_store(monkeypatch)
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
    assert store.restore_webui is False


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
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.get_by_args_subset", lambda *a: [])
    _patch_store(monkeypatch)
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


def test_shutdown_all_delivers_shutdown_to_webui_and_records_restore(monkeypatch):
    calls = []

    class _Signal:
        def emit(self):
            pass

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
    webuis = [object()]
    monkeypatch.setattr("wafer.app.tray.main_tray.threading.Thread", _Thread)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.list_viewers", lambda: viewers)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.get_by_args_subset", lambda *a: webuis)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.wait_procs_then_kill", lambda procs: calls.append(("wait", procs)))
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.force_close_all", lambda: None)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.new_main", lambda *a, **kw: None)
    monkeypatch.setattr("wafer.plugin.settings.PluginSettings.clear_restart_scope", lambda self: None)
    store = _patch_store(monkeypatch)

    fake = type("FakeTray", (), {})()
    fake._node = _Node()
    fake._close_all_ready = _Signal()

    TrayApp._shutdown_all(fake, then_restart=True)

    assert fake._node.sent == [
        (("app.shutdown",), {"dst": "viewer"}),
        (("app.shutdown",), {"dst": "webui"}),
    ]
    assert calls == [("wait", viewers + webuis)]
    assert store.restore_webui is True


def test_disarm_reaper_called_on_restart_only(monkeypatch):
    disarmed = []

    class _Signal:
        def emit(self):
            pass

    class _Node:
        def send(self, *args, **kwargs):
            pass

    class _Thread:
        def __init__(self, target=None, daemon=None):
            pass

        def start(self):
            pass

    monkeypatch.setattr("wafer.app.tray.main_tray.threading.Thread", _Thread)
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.list_viewers", lambda: [])
    monkeypatch.setattr("wafer.app.tray.main_tray.AppProcess.get_by_args_subset", lambda *a: [])
    _patch_store(monkeypatch)
    monkeypatch.setattr("wafer.app.tray.main_tray._disarm_child_reaper", lambda: disarmed.append(True))
    monkeypatch.setattr("wafer.plugin.settings.PluginSettings.clear_restart_scope", lambda self: None)

    def _make_fake():
        fake = type("FakeTray", (), {})()
        fake._node = _Node()
        fake._close_all_ready = _Signal()
        return fake

    close_fake = _make_fake()
    TrayApp._shutdown_all(close_fake, then_restart=False)
    assert disarmed == []
    assert close_fake.shutting_down is True

    restart_fake = _make_fake()
    TrayApp._shutdown_all(restart_fake, then_restart=True)
    assert disarmed == [True]
    assert restart_fake.shutting_down is True


def test_on_trigger_noop_while_shutting_down(monkeypatch):
    ran = []
    monkeypatch.setattr("wafer.app.tray.main_tray.Command.run", lambda *a, **kw: ran.append(a))

    fake = type("FakeTray", (), {})()
    fake.shutting_down = True
    TrayApp._on_trigger.__wrapped__(fake)
    assert ran == []

    fake.shutting_down = False
    TrayApp._on_trigger.__wrapped__(fake)
    assert ran == [("tray.show_window",)]

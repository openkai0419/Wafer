from wafer.builtins.updater import startup
from wafer.builtins.updater.service import UpdateCheckResult, UpdateInfo
from wafer.core.commands.binding.instance_registry import InstanceRegistry
from wafer.core.workspace import WorkspaceStore


class _Dispatcher:
    def post(self, fn, priority=5):
        fn()

    def invoke(self, fn):
        fn()


class _Widget:
    def __init__(self):
        self.info = None
        self.record_state = None

    def set_update_info(self, info, **kwargs):
        self.info = info
        self.record_state = kwargs.get("record_state")


class _Manager:
    def __init__(self):
        self.visible = False
        self.widget = _Widget()

    def panel_names(self):
        return [startup.PANEL_DISPLAY_NAME]

    def ensure_panel_visible(self, name):
        self.visible = True

    def panel_widget(self, name):
        return self.widget


class _MainWindow:
    def __init__(self, slot_id, manager):
        self.slot_id = slot_id
        self._layout_manager = manager
        self._dispatcher = _Dispatcher()


def _new_result(version="0.6.19", *, is_newer=True):
    info = UpdateInfo(
        current_version="0.6.18",
        latest_version=version,
        tag_name=f"v{version}",
        release_url="https://github.com/openkai0419/Wafer/releases/latest",
        download_url="https://github.com/openkai0419/Wafer/releases/latest",
        published_at="",
        release_notes="",
        is_newer=is_newer,
    )
    return UpdateCheckResult(info=info)


def _register_main_window(window):
    registry = InstanceRegistry.instance()
    previous = list(registry._by_name.get("MainWindow", []))
    registry._by_name["MainWindow"] = [window]

    def restore():
        if previous:
            registry._by_name["MainWindow"] = previous
        else:
            registry._by_name.pop("MainWindow", None)

    return restore


def test_startup_check_shows_only_for_first_viewer_in_generation(tmp_path, monkeypatch):
    store = WorkspaceStore(path=str(tmp_path / "ws.json"))
    first, _, _ = store.acquire_slot("first")
    second, _, _ = store.acquire_slot("second")
    monkeypatch.setattr(startup.WorkspaceStore, "instance", staticmethod(lambda: store))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result())

    first_manager = _Manager()
    second_manager = _Manager()

    first_window = _MainWindow(first, first_manager)
    second_window = _MainWindow(second, second_manager)

    restore = _register_main_window(first_window)
    try:
        startup.run_startup_update_check()
        restore()

        restore = _register_main_window(second_window)
        startup.run_startup_update_check()
    finally:
        restore()

    assert first_manager.visible is True
    assert first_manager.widget.info.latest_version == "0.6.19"
    assert first_manager.widget.record_state is False
    assert second_manager.visible is False


def test_startup_check_does_not_show_skipped_version(tmp_path, monkeypatch):
    store = WorkspaceStore(path=str(tmp_path / "ws.json"))
    first, _, _ = store.acquire_slot("first")
    monkeypatch.setattr(startup.WorkspaceStore, "instance", staticmethod(lambda: store))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "0.6.19")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result())
    manager = _Manager()
    window = _MainWindow(first, manager)
    restore = _register_main_window(window)
    try:
        startup.run_startup_update_check()
    finally:
        restore()

    assert manager.visible is False


def test_startup_check_does_not_show_when_update_is_not_needed(tmp_path, monkeypatch):
    store = WorkspaceStore(path=str(tmp_path / "ws.json"))
    first, _, _ = store.acquire_slot("first")
    monkeypatch.setattr(startup.WorkspaceStore, "instance", staticmethod(lambda: store))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result("0.6.18", is_newer=False))
    manager = _Manager()
    window = _MainWindow(first, manager)
    restore = _register_main_window(window)
    try:
        startup.run_startup_update_check()
    finally:
        restore()

    assert manager.visible is False


def test_startup_check_respects_auto_check_disabled(tmp_path, monkeypatch):
    store = WorkspaceStore(path=str(tmp_path / "ws.json"))
    first, _, _ = store.acquire_slot("first")
    monkeypatch.setattr(startup.WorkspaceStore, "instance", staticmethod(lambda: store))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: False)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result())
    manager = _Manager()
    window = _MainWindow(first, manager)
    restore = _register_main_window(window)
    try:
        startup.run_startup_update_check()
    finally:
        restore()

    assert manager.visible is False
    assert store.claim_viewer_startup_once(startup.STARTUP_SCOPE, first) is True


def _swap_instance(name, value):
    registry = InstanceRegistry.instance()
    previous = list(registry._by_name.get(name, []))
    if value is None:
        registry._by_name.pop(name, None)
    else:
        registry._by_name[name] = [value]

    def restore():
        if previous:
            registry._by_name[name] = previous
        else:
            registry._by_name.pop(name, None)

    return restore


def test_present_updater_uses_standalone_without_mainwindow(monkeypatch):
    from wafer.plugin.panel.handler import panel_registry
    from wafer.builtins.updater.widget import UpdateNotifierPlugin

    captured = {}

    def fake_open(factory, title, key, size=None, parent=None):
        captured.update(title=title, key=key, parent=parent)
        return _Widget()

    monkeypatch.setattr("wafer.qt.ui.layout.standalone.open_standalone", fake_open)
    had = panel_registry.get(UpdateNotifierPlugin.NAME) is not None
    if not had:
        panel_registry.register(UpdateNotifierPlugin)
    sentinel = object()
    restore_mw = _swap_instance("MainWindow", None)
    restore_web = _swap_instance("WebUIWindow", sentinel)
    try:
        widget = startup.present_updater()
    finally:
        restore_web()
        restore_mw()
        if not had:
            panel_registry._plugins.pop(UpdateNotifierPlugin.NAME, None)
            panel_registry._instances.pop(UpdateNotifierPlugin.NAME, None)

    assert isinstance(widget, _Widget)
    assert captured["key"] == "update"
    assert captured["parent"] is sentinel


def test_startup_check_presents_for_webui(monkeypatch):
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result())
    monkeypatch.setattr(startup, "process_apply_results", lambda: None)
    monkeypatch.setattr(startup, "_resolve_dispatcher", lambda: _Dispatcher())
    widget = _Widget()
    monkeypatch.setattr(startup, "present_updater", lambda: widget)

    startup.run_startup_update_check()

    assert widget.info.latest_version == "0.6.19"
    assert widget.record_state is False


def test_log_startup_update_check_reports_available(monkeypatch):
    logs = []
    monkeypatch.setattr(startup.AppLogger, "warning", staticmethod(lambda msg, **kwargs: logs.append(msg)))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "process_apply_results", lambda: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result())

    startup.log_startup_update_check()

    assert any("Update available" in m for m in logs)


def test_log_startup_update_check_silent_when_up_to_date(monkeypatch):
    logs = []
    monkeypatch.setattr(startup.AppLogger, "warning", staticmethod(lambda msg, **kwargs: logs.append(msg)))
    monkeypatch.setattr(startup.state, "is_auto_check_enabled", lambda: True)
    monkeypatch.setattr(startup.state, "skipped_version", lambda: "")
    monkeypatch.setattr(startup.state, "record_latest_result", lambda version: None)
    monkeypatch.setattr(startup, "process_apply_results", lambda: None)
    monkeypatch.setattr(startup, "check_for_updates", lambda: _new_result("0.6.18", is_newer=False))

    startup.log_startup_update_check()

    assert logs == []

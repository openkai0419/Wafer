from __future__ import annotations

from PySide6 import QtCore

from ... import _dev
from ..._version import __version__
from ...qt.commands.binding.instance_registry import InstanceRegistry
from ...qt.common.dispatcher import Dispatcher
from ...qt.common.thread import utility_pool
from ...core.store.workspace import WorkspaceStore
from ...core.logs import AppLogger
from . import stage, state
from .service import check_for_updates, should_notify_update
from .widget import PANEL_DISPLAY_NAME


STARTUP_SCOPE = "updater.auto_panel"

_dispatcher: Dispatcher | None = None


def schedule_startup_update_check(delay_ms: int = 1000) -> None:
    QtCore.QTimer.singleShot(int(delay_ms), run_startup_update_check)


def process_apply_results() -> None:
    try:
        stage.process_apply_results()
    except Exception as e:
        AppLogger.warning("Failed to process update apply results", exc=e)


def present_updater():
    from ..commands.panel import open_panel

    return open_panel(name=PANEL_DISPLAY_NAME, toggle=False)


def _resolve_dispatcher() -> Dispatcher | None:
    global _dispatcher
    main_window = InstanceRegistry.instance().get_one("MainWindow")
    if main_window is not None:
        slot_id = str(getattr(main_window, "slot_id", "") or "")
        manager = getattr(main_window, "_layout_manager", None)
        dispatcher = getattr(main_window, "_dispatcher", None)
        if dispatcher is None or manager is None or not slot_id or PANEL_DISPLAY_NAME not in manager.panel_names():
            return None
        if not WorkspaceStore.instance().claim_viewer_startup_once(STARTUP_SCOPE, slot_id):
            return None
        return dispatcher
    parent = InstanceRegistry.instance().get_one("WebUIWindow")
    if parent is None:
        return None
    if _dispatcher is None:
        _dispatcher = Dispatcher(utility_pool, parent=parent)
    return _dispatcher


def run_startup_update_check() -> None:
    if _dev.FORCE_UPDATE_ENABLED:
        AppLogger.warning(f"[Updater] DEV update source active: {_dev.source_dir()} (reporting version {__version__})")
    process_apply_results()
    if not state.is_auto_check_enabled():
        return
    dispatcher = _resolve_dispatcher()
    if dispatcher is None:
        return

    def task():
        result = check_for_updates()

        def apply_result():
            info = result.info
            if info is None:
                return
            state.record_latest_result(info.latest_version)
            if not should_notify_update(info, state.skipped_version()):
                return
            widget = present_updater()
            if widget is not None and hasattr(widget, "set_update_info"):
                widget.set_update_info(info, record_state=False)

        dispatcher.invoke(apply_result)

    try:
        dispatcher.post(task, priority=5)
    except Exception as e:
        AppLogger.warning("Failed to schedule startup update check", exc=e)


def log_startup_update_check() -> None:
    process_apply_results()
    if not state.is_auto_check_enabled():
        return
    try:
        result = check_for_updates()
    except Exception as e:
        AppLogger.warning("Failed to check for updates", exc=e)
        return
    info = result.info
    if info is None:
        return
    state.record_latest_result(info.latest_version)
    if not should_notify_update(info, state.skipped_version()):
        return
    AppLogger.warning(f"Update available: {info.latest_version} (current {__version__}). Open the WebUI window or Viewer to apply.")

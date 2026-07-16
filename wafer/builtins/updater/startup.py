from __future__ import annotations

from PySide6 import QtCore

from ...core.commands.binding.instance_registry import InstanceRegistry
from ...core.workspace import WorkspaceStore
from ...utils.logs import AppLogger
from . import stage, state
from .service import check_for_updates, should_notify_update
from .widget import PANEL_DISPLAY_NAME


STARTUP_SCOPE = "updater.auto_panel"


def schedule_startup_update_check(delay_ms: int = 1000) -> None:
    QtCore.QTimer.singleShot(int(delay_ms), run_startup_update_check)


def process_apply_results() -> None:
    try:
        stage.process_apply_results()
    except Exception as e:
        AppLogger.warning("Failed to process update apply results", exc=e)


def run_startup_update_check() -> None:
    main_window = InstanceRegistry.instance().get_one("MainWindow")
    manager = getattr(main_window, "_layout_manager", None)
    dispatcher = getattr(main_window, "_dispatcher", None)
    slot_id = str(getattr(main_window, "slot_id", "") or "")
    if manager is None or dispatcher is None or not slot_id:
        return
    process_apply_results()
    if PANEL_DISPLAY_NAME not in manager.panel_names():
        return
    if not state.is_auto_check_enabled():
        return
    if not WorkspaceStore.instance().claim_viewer_startup_once(STARTUP_SCOPE, slot_id):
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
            manager.ensure_panel_visible(PANEL_DISPLAY_NAME)
            widget = manager.panel_widget(PANEL_DISPLAY_NAME)
            if hasattr(widget, "set_update_info"):
                widget.set_update_info(info, record_state=False)

        dispatcher.invoke(apply_result)

    try:
        dispatcher.post(task, priority=5)
    except Exception as e:
        AppLogger.warning("Failed to schedule startup update check", exc=e)

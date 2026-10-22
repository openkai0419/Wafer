import time
from collections.abc import Callable

import psutil

from ..core.common.paths import get_plugin_dir
from ..core.logs import AppLogger
from ..core.platform.process import AppProcess
from ..core.platform.process_lock import SafeProcessLock
from . import installer_queue
from .install_status import INSTALL_WAITER_LOCK_NAME, read_status


POLL_INTERVAL = 0.15
_PHASE_LABEL = {
    "pip": "Installing",
    "post_install": "Setting up",
    "pending": "Preparing",
    "done": "Finalizing",
    "error": "Error",
}


def has_pending_install() -> bool:
    return installer_queue.has_pending_queue(get_plugin_dir())


def wait_for_install(
    *,
    restart_idle_tray: Callable[[], bool],
    wait_for_tray: Callable[[int], None],
    on_idle: Callable[[], None] | None = None,
) -> None:
    if not has_pending_install():
        return
    waiter_lock = acquire_waiter_lock(on_idle=on_idle)
    if waiter_lock is None:
        return
    try:
        tray_pid = prepare_tray(restart_idle_tray)
        if tray_pid is None:
            AppLogger.info("[InstallWaiter] pending install skipped; starting without it")
            return
        wait_for_tray(tray_pid)
    finally:
        waiter_lock.release()


def wait_for_install_headless() -> None:
    wait_for_install(restart_idle_tray=_skip_idle_tray, wait_for_tray=_log_until_done)


def acquire_waiter_lock(*, on_idle: Callable[[], None] | None = None) -> SafeProcessLock | None:
    while has_pending_install():
        waiter_lock = SafeProcessLock(INSTALL_WAITER_LOCK_NAME)
        if waiter_lock.acquire():
            if has_pending_install():
                return waiter_lock
            waiter_lock.release()
            return None
        if on_idle is not None:
            on_idle()
        time.sleep(POLL_INTERVAL)
    return None


def prepare_tray(restart_idle_tray: Callable[[], bool]) -> int | None:
    existing = AppProcess.get_by_args_subset("--tray")
    if not existing:
        AppLogger.info("[InstallWaiter] spawning tray for pending install")
        return AppProcess.new_main("--tray").pid
    if status_is_active(read_status()):
        AppLogger.info("[InstallWaiter] tray already installing, waiting for it")
        return existing[0].pid
    if not restart_idle_tray():
        return None
    AppLogger.info("[InstallWaiter] restarting tray to process pending install")
    AppProcess.terminate_and_wait(existing)
    return AppProcess.new_main("--tray").pid


def poll_until_done(
    tray_pid: int,
    *,
    on_status: Callable[[dict | None], None] | None = None,
    is_cancelling: Callable[[], bool] = lambda: False,
    on_idle: Callable[[], None] | None = None,
) -> None:
    while True:
        if not psutil.pid_exists(tray_pid):
            AppLogger.warning("[InstallWaiter] tray exited before install completed")
            return
        status = read_status()
        if on_status is not None:
            on_status(status)
        if is_install_finished(status, is_cancelling()):
            return
        if on_idle is not None:
            on_idle()
        time.sleep(POLL_INTERVAL)


def status_is_active(status: dict | None) -> bool:
    return status is not None and str(status.get("phase")) not in ("done", "error")


def is_install_finished(status: dict | None, cancelling: bool) -> bool:
    if status_is_active(status):
        return False
    if status is not None:
        return True
    return cancelling or not has_pending_install()


def describe_status(status: dict | None) -> str:
    if not status:
        return "Waiting"
    phase = str(status.get("phase", "pending"))
    current = status.get("current") or {}
    name = current.get("name") or ""
    index = current.get("index")
    total = current.get("total")
    label = _PHASE_LABEL.get(phase, phase.capitalize())
    if name and index and total:
        return f"{label} {name} ({index}/{total})"
    if name:
        return f"{label} {name}"
    return label


def _skip_idle_tray() -> bool:
    AppLogger.warning("[InstallWaiter] The background service is running but did not pick up the pending extension install. Starting without it; use Restart All to install.")
    return False


def _log_until_done(tray_pid: int) -> None:
    last = {"message": ""}

    def log_change(status: dict | None) -> None:
        message = describe_status(status)
        if message != last["message"]:
            last["message"] = message
            AppLogger.info(f"[InstallWaiter] {message}")

    poll_until_done(tray_pid, on_status=log_change)

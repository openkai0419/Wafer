import time

import psutil
from PySide6 import QtCore, QtWidgets

from ..core.platform.process import AppProcess
from ..plugin import installer_queue
from ..plugin.install_status import read_status, request_cancel
from ..plugin.loader import get_plugin_dir
from ..utils.logs import AppLogger
from .splash import InstallSplash


_PHASE_LABEL = {
    "pip": "Installing",
    "post_install": "Setting up",
    "pending": "Preparing",
    "done": "Finalizing",
    "error": "Error",
}
_POLL_INTERVAL = 0.15


def wait_for_install_complete(*, icon=None, app=None, parent=None) -> None:
    if not installer_queue.has_pending_queue(get_plugin_dir()):
        return
    app = app or QtWidgets.QApplication.instance()
    tray_pid = _prepare_tray(parent=parent)
    if tray_pid is None:
        AppLogger.info("[InstallWaiter] user skipped install")
        return

    splash = InstallSplash(
        "Installing extensions",
        icon=icon,
        message=_format_message(read_status()),
        show_log=True,
        cancel_label="Cancel install",
    )
    cancelling = {"value": False}

    def on_cancel():
        if cancelling["value"]:
            return
        cancelling["value"] = True
        AppLogger.info("[InstallWaiter] cancel requested by user")
        request_cancel()
        splash.set_message("Cancelling, please wait\u2026")
        if splash.cancel_button is not None:
            splash.cancel_button.setEnabled(False)

    if splash.cancel_button is not None:
        splash.cancel_button.clicked.connect(on_cancel)
    splash.show()

    try:
        _poll_until_done(splash, app, tray_pid, cancelling)
    finally:
        splash.close()


def _prepare_tray(*, parent) -> int | None:
    existing = AppProcess.get_by_args_subset("--tray")
    if not existing:
        AppLogger.info("[InstallWaiter] spawning tray for pending install")
        proc = AppProcess.new_main("--tray")
        return proc.pid
    if read_status() is not None:
        AppLogger.info("[InstallWaiter] tray already installing, attaching to splash")
        return existing[0].pid
    return _ask_restart_tray(existing, parent=parent)


def _ask_restart_tray(existing_procs, *, parent) -> int | None:
    box = QtWidgets.QMessageBox(
        QtWidgets.QMessageBox.Question,
        "Plugin install pending",
        "Background service is running but did not pick up the new plugin install.\nRestart the background service to install now, or skip and start without installing?",
        parent=parent,
    )
    restart_btn = box.addButton("Restart && install", QtWidgets.QMessageBox.AcceptRole)
    skip_btn = box.addButton("Skip", QtWidgets.QMessageBox.RejectRole)
    box.setDefaultButton(restart_btn)
    box.exec()
    if box.clickedButton() is skip_btn:
        return None
    AppLogger.info("[InstallWaiter] restarting tray to process pending install")
    AppProcess.terminate_and_wait(existing_procs)
    proc = AppProcess.new_main("--tray")
    return proc.pid


def _poll_until_done(splash: InstallSplash, app, tray_pid: int, cancelling: dict) -> None:
    while True:
        if not psutil.pid_exists(tray_pid):
            AppLogger.warning("[InstallWaiter] tray exited before install completed")
            return
        status = read_status()
        if cancelling["value"]:
            if status is None:
                return
        else:
            if status is None and not installer_queue.has_pending_queue(get_plugin_dir()):
                return
        _refresh_splash(splash, status, cancelling["value"])
        if app is not None:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)
        time.sleep(_POLL_INTERVAL)


def _refresh_splash(splash: InstallSplash, status: dict | None, cancelling: bool) -> None:
    if status is None:
        return
    if not cancelling:
        splash.set_message(_format_message(status))
    log_tail = status.get("log_tail")
    if isinstance(log_tail, list):
        splash.replace_log([str(x) for x in log_tail])


def _format_message(status: dict | None) -> str:
    if not status:
        return "Preparing"
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

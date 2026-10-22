from PySide6 import QtCore, QtWidgets

from ...core.logs import AppLogger
from ...plugin.install_status import read_status, request_cancel
from ...plugin.install_wait import describe_status, poll_until_done, wait_for_install
from .splash import InstallSplash


def wait_for_install_complete(*, icon=None, app=None, parent=None) -> None:
    app = app or QtWidgets.QApplication.instance()

    def process_events():
        if app is not None:
            app.processEvents(QtCore.QEventLoop.AllEvents, 50)

    wait_for_install(
        restart_idle_tray=lambda: _ask_restart_tray(parent=parent),
        wait_for_tray=lambda tray_pid: _wait_with_splash(tray_pid, icon=icon, on_idle=process_events),
        on_idle=process_events,
    )


def _wait_with_splash(tray_pid: int, *, icon, on_idle) -> None:
    splash = InstallSplash(
        "Installing extensions",
        icon=icon,
        message=describe_status(read_status()),
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
        splash.set_message("Cancelling, please wait…")
        if splash.cancel_button is not None:
            splash.cancel_button.setEnabled(False)

    if splash.cancel_button is not None:
        splash.cancel_button.clicked.connect(on_cancel)
    splash.show()
    try:
        poll_until_done(
            tray_pid,
            on_status=lambda status: _refresh_splash(splash, status, cancelling["value"]),
            is_cancelling=lambda: cancelling["value"],
            on_idle=on_idle,
        )
    finally:
        splash.close()


def _ask_restart_tray(*, parent) -> bool:
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
    return box.clickedButton() is not skip_btn


def _refresh_splash(splash: InstallSplash, status: dict | None, cancelling: bool) -> None:
    if status is None:
        return
    if not cancelling:
        splash.set_message(describe_status(status))
    log_tail = status.get("log_tail")
    if isinstance(log_tail, list):
        splash.replace_log([str(x) for x in log_tail])

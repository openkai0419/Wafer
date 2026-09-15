import webbrowser

from PySide6 import QtWidgets

from ...app.webui.settings import HOST_ALL, HOST_LOCAL, WebUISettings
from ...qt.commands.bridge import ActionKit, Command
from ...core.platform.process import AppProcess
from ...qt.common.notifier import Notifier


def _window(ctx):
    return ctx.get_instance("WebUIWindow")


def open_browser(ctx=None):
    win = _window(ctx)
    if win:
        webbrowser.open(win.server.browse_url)


def restart_webui(ctx=None):
    Notifier.info("Restarting WebUI...")
    AppProcess.new_main("--webui", "--no-browser", extra_env={"WAFER_REPLACE_WEBUI": "1"})


def open_settings(ctx=None):
    win = _window(ctx)
    settings = WebUISettings()

    dialog = QtWidgets.QDialog(win)
    dialog.setWindowTitle("WebUI Settings")
    form = QtWidgets.QFormLayout(dialog)

    host_combo = QtWidgets.QComboBox()
    host_combo.addItem("Local only (127.0.0.1)", HOST_LOCAL)
    host_combo.addItem("All interfaces (0.0.0.0)", HOST_ALL)
    idx = host_combo.findData(settings.host())
    host_combo.setCurrentIndex(idx if idx >= 0 else 0)

    port_spin = QtWidgets.QSpinBox()
    port_spin.setRange(1, 65535)
    port_spin.setValue(settings.port())

    note = QtWidgets.QLabel('"All interfaces" exposes the WebUI to your network. Securing access is your responsibility.\nChanges apply after restarting the WebUI.')
    note.setWordWrap(True)

    buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Cancel)
    save_btn = buttons.addButton("Save", QtWidgets.QDialogButtonBox.AcceptRole)
    restart_btn = buttons.addButton("Save && Restart", QtWidgets.QDialogButtonBox.ApplyRole)

    form.addRow("Host", host_combo)
    form.addRow("Port", port_spin)
    form.addRow(note)
    form.addRow(buttons)

    result = {"restart": False}

    def save():
        settings.set_bind(host_combo.currentData(), port_spin.value())
        dialog.accept()

    save_btn.clicked.connect(save)
    restart_btn.clicked.connect(lambda: (result.__setitem__("restart", True), save()))
    buttons.rejected.connect(dialog.reject)

    if dialog.exec() and result["restart"]:
        Command.run("webui.restart")


class WebUIBackendCommands(ActionKit.MenuBase):
    NAME = "WebUI"
    SCOPE = "webui"
    PRIORITY = 84

    @classmethod
    def commands(cls):
        return [
            ":WebUI",
            ActionKit.Command(path="webui.open_browser", display="Open Browser", func=open_browser),
            ActionKit.Command(path="webui.settings", display="Settings...", func=open_settings),
            "-",
            ActionKit.Command(path="webui.restart", display="Restart WebUI", func=restart_webui),
        ]

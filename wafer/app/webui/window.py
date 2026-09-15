from __future__ import annotations

import threading

from PySide6 import QtCore, QtWidgets

from ...builtins.log_panel import LogPanelPlugin
from ...qt.commands.bridge import Command, Context, Menu, UI
from ...core.lang.manager import t
from ...qt.common.dpi import dpix
from ...core.logs import AppLogger


class WebUIWindow(QtWidgets.QWidget):
    shutdown_requested = QtCore.Signal()
    remote_log_received = QtCore.Signal(str, str, str, str)
    _server_stopped = QtCore.Signal()

    def __init__(self, server):
        super().__init__()
        self.server = server
        self.setWindowTitle("Wafer WebUI")
        self.resize(dpix(640), dpix(480))
        UI.register_instance("WebUIWindow", self)
        self.shutdown_requested.connect(self.close)
        self.remote_log_received.connect(self._on_remote_log)
        self._server_stopped.connect(QtWidgets.QApplication.quit)
        self._closing = False

        url_edit = QtWidgets.QLineEdit(server.browse_url)
        url_edit.setReadOnly(True)
        open_btn = QtWidgets.QPushButton(t("Open Browser"))
        open_btn.clicked.connect(lambda: Command.run("webui.open_browser"))
        settings_btn = QtWidgets.QPushButton(t("Settings"))
        settings_btn.clicked.connect(lambda: Command.run("webui.settings"))
        restart_btn = QtWidgets.QPushButton(t("Restart All"))
        restart_btn.clicked.connect(lambda: Command.run("win.restart_all"))
        menu_btn = QtWidgets.QToolButton()
        menu_btn.setText(t("Menu"))
        menu_btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        menu_btn.setMenu(self._build_menu())

        top = QtWidgets.QHBoxLayout()
        top.addWidget(url_edit, 1)
        top.addWidget(open_btn)
        top.addWidget(settings_btn)
        top.addWidget(restart_btn)
        top.addWidget(menu_btn)

        self._log_panel = LogPanelPlugin().create_widget()
        layout = QtWidgets.QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self._log_panel, 1)

    def bind_remote_logs(self):
        self.server.on_dev_log = self.remote_log_received.emit

    @QtCore.Slot(str, str, str, str)
    def _on_remote_log(self, level: str, text: str, src: str, db: str):
        self._log_panel.append_log(level, text, src=src, db=db)

    @property
    def _node(self):
        return self.server.node

    def _ctx(self):
        return Context.create_context(None, "WebUIWindow", source="webui", extras={"webui": self})

    def _build_menu(self):
        session = Menu.session(None, seed_ctx=self._ctx())
        spec = session.all_roots()
        if spec is None:
            return QtWidgets.QMenu(self)
        return spec.build()

    def request_shutdown(self):
        self.shutdown_requested.emit()

    def closeEvent(self, event):
        AppLogger.info("WebUI window closing, stopping server.")
        if not self._closing:
            self._closing = True
            threading.Thread(target=self._stop_server, name="webui-stop", daemon=True).start()
        super().closeEvent(event)

    def _stop_server(self):
        self.server.stop()
        self._server_stopped.emit()

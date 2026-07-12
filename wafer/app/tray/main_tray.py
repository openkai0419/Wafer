from PySide6 import QtCore, QtWidgets
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...constants import APP_NAME
from ...core.commands.bridge import Command, Context, Menu, UI

from ...core.qt.rate_limit import qt_debounce
from ...core.ipc.broker import Broker
from ...core.ipc.node import Node
from ...core.platform.process import AppProcess
import threading


class TrayApp(QtWidgets.QSystemTrayIcon):
    _close_all_ready = QtCore.Signal()

    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        AppLogger.info("TRAY APP EXECUTED")
        self.setToolTip(f"{APP_NAME}")
        self.show_state = False
        self.activated.connect(self.on_activated)
        self.broker = Broker()
        self.broker.start()
        self._node = Node("tray")
        self._node.subscribe("app.quit_all", lambda msg: self._request_close_all() or True)
        self._node.start(self.broker.port)
        AppLogger.set_node(self._node, role="tray")
        UI.register_instance("Tray", self)
        self._close_all_ready.connect(QtWidgets.QApplication.quit)
        self.setContextMenu(self._build_menu())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_quit)

    def _build_menu(self):
        session = Menu.session(None, seed_ctx=self._ctx())
        spec = session.all_roots()
        if spec is None:
            return QtWidgets.QMenu()
        return spec.hide(["File"]).build()

    def _ctx(self):
        return Context.create_context(None, "Tray", source="tray", extras={"tray": self})

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._on_trigger()

    @qt_debounce(10)
    def _on_trigger(self):
        Command.run("tray.show_window")

    def _request_close_all(self):
        QtCore.QMetaObject.invokeMethod(self, "close_all", QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def close_all(self):
        AppLogger.info("close_all: shutting down all viewers, then tray")
        from ...plugin.settings import PluginSettings

        PluginSettings().clear_restart_scope()
        viewers = AppProcess.list_viewers()
        self._node.send("app.shutdown", dst="viewer")

        def finish():
            AppProcess.wait_procs_then_kill(viewers)
            AppProcess.force_close_all()
            self._close_all_ready.emit()

        threading.Thread(target=finish, daemon=True).start()

    def on_quit(self):
        AppLogger.info("tray shutting down")
        try:
            self._node.stop()
        except Exception as e:
            AppLogger.debug(f"TrayApp.node.stop failed: {e}")
        try:
            self.broker.stop()
        except Exception as e:
            AppLogger.debug(f"TrayApp.broker.stop failed: {e}")

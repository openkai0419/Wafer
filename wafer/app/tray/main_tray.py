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


def _disarm_child_reaper():
    app = QtWidgets.QApplication.instance()
    if app is None:
        return
    try:
        app.aboutToQuit.disconnect(AppProcess.shutdown_children)
        AppLogger.info("restart: disarmed shutdown_children so the replacement ROOT survives tray exit")
    except (RuntimeError, TypeError) as e:
        AppLogger.warning(f"restart: could not disarm shutdown_children; replacement ROOT may be reaped on tray exit: {e}")


class TrayApp(QtWidgets.QSystemTrayIcon):
    _close_all_ready = QtCore.Signal()

    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        AppLogger.info("TRAY APP EXECUTED")
        self.setToolTip(f"{APP_NAME}")
        self.show_state = False
        self.shutting_down = False
        self.activated.connect(self.on_activated)
        self.broker = Broker()
        self.broker.start()
        self._node = Node("tray")
        self._node.subscribe("app.quit_all", lambda msg: self._request_shutdown_all(then_restart=False) or True)
        self._node.subscribe("app.restart_all", lambda msg: self._request_shutdown_all(then_restart=True) or True)
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
        if self.shutting_down:
            return
        Command.run("tray.show_window")

    def _request_shutdown_all(self, *, then_restart):
        slot = "restart_all" if then_restart else "close_all"
        QtCore.QMetaObject.invokeMethod(self, slot, QtCore.Qt.QueuedConnection)

    @QtCore.Slot()
    def close_all(self):
        self._shutdown_all(then_restart=False)

    @QtCore.Slot()
    def restart_all(self):
        self._shutdown_all(then_restart=True)

    def _shutdown_all(self, *, then_restart):
        AppLogger.info(f"_shutdown_all: shutting down all viewers, then tray (restart={then_restart})")
        from ...plugin.settings import PluginSettings

        PluginSettings().clear_restart_scope()
        self.shutting_down = True
        if then_restart:
            _disarm_child_reaper()
        viewers = AppProcess.list_viewers()
        self._node.send("app.shutdown", dst="viewer")

        def finish():
            AppProcess.wait_procs_then_kill(viewers)
            AppProcess.force_close_all()
            if then_restart:
                AppProcess.new_main(extra_env={"WAFER_REPLACE_TRAY": "1"})
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

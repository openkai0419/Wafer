from PySide6 import QtWidgets
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...constants import APP_NAME
from ...core.commands.bridge import Command, Context, Menu, UI
from ...core.lang.manager import TranslatorMixin
from ...core.qt.rate_limit import qt_debounce
from ...core.ipc.broker import Broker
from ...core.ipc.node import Node
from .tray_commands import TrayMenu

TrayMenu.register()

class TrayApp(QtWidgets.QSystemTrayIcon, TranslatorMixin):

    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        AppLogger.info('TRAY APP EXECUTED')
        self.setToolTip(f'{APP_NAME}')
        self.show_state = False
        self.activated.connect(self.on_activated)
        self.broker = Broker()
        self.broker.start()
        self._node = Node('tray')
        self._node.start(self.broker.port)
        AppLogger.set_node(self._node, role='tray')
        UI.register_instance("Tray", self)
        self.setContextMenu(self._build_menu())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_quit)

    def _build_menu(self):
        return Menu.session(None, seed_ctx=self._ctx()).from_folder(TrayMenu.NAME).build()

    def _ctx(self):
        return Context.create_context(None, "Tray", source="tray", extras={"tray": self})

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._on_trigger()

    @qt_debounce(10)
    def _on_trigger(self):
        Command.run('show_window')

    def on_quit(self):
        AppLogger.info('tray shutting down')
        try:
            self._node.stop()
        except Exception as e:
            AppLogger.debug(f'TrayApp.node.stop failed: {e}')
        try:
            self.broker.stop()
        except Exception as e:
            AppLogger.debug(f'TrayApp.broker.stop failed: {e}')

    

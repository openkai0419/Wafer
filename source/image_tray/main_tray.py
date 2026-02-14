from PySide6 import QtWidgets
from ..common.profiling import logger, profiler
from ..constants import APP_NAME
from ..actions.bridge import Command, Context, Menu, UI
from ..lang.manager import TranslatorMixin
from ..qt.debounce import qt_debounce
from ..zmq.broker import Broker
from .tray_commands import TrayMenu

TrayMenu.register()

class TrayApp(QtWidgets.QSystemTrayIcon, TranslatorMixin):

    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        logger.info('TRAY APP EXECUTED')
        self.setToolTip(f'{APP_NAME}')
        self.show_state = False
        self.activated.connect(self.on_activated)
        self.broker = Broker()
        self.broker.start()
        UI.register_instance("Tray", self)
        self.setContextMenu(self._build_menu())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_delete)

    def _build_menu(self):
        return Menu.session(None, seed_ctx=self._ctx()).use(TrayMenu.prefix).build()

    def _ctx(self):
        return Context.create_context(None, "Tray", source="tray", extras={"tray": self})

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._on_trigger()

    @qt_debounce(10)
    def _on_trigger(self):
        Command.run('show_window')

    def on_delete(self):
        try:
            self.broker.stop()
        except Exception as e:
            logger.debug(f'TrayApp.broker.stop failed: {e}')

    

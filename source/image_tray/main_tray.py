from PySide6 import QtWidgets
from ..common.profiling import logger, profiler
from ..constants import APP_NAME
from ..actions.bridge import Command, Context, Menu
from ..image_collector.progress_notifier import close_publisher
from ..lang.manager import TranslatorMixin
from ..qt.debounce import qt_debounce
from ..zmq.zmq import Role, ZMQBroker, ZMQNode
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
        self.broker = ZMQBroker()
        self.broker.start()
        self.zmq = ZMQNode(Role.COMMUNICATOR, on_message=self.on_notify)
        self.zmq.start()
        self.setContextMenu(self._build_menu())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_delete)

    def _build_menu(self):
        return Menu.use_menu(TrayMenu.prefix, None, seed_ctx=self._ctx())

    def _ctx(self):
        return Context.create_context(None, "Tray", source="tray", extras={"tray": self})

    def on_notify(self, v):
        logger.info(f'NOTIFY : {v}')

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self._on_trigger()

    @qt_debounce(10)
    def _on_trigger(self):
        Command.execute('show_window', ctx=self._ctx())

    def on_delete(self):
        try:
            self.zmq.stop()
        except Exception as e:
            logger.debug(f'TrayApp.zmq.stop failed: {e}')
        try:
            self.broker.stop()
        except Exception as e:
            logger.debug(f'TrayApp.broker.stop failed: {e}')
        try:
            close_publisher()
        except Exception as e:
            logger.debug(f'TrayApp.close_publisher failed: {e}')

    

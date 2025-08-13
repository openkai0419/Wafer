import contextlib
from PySide6 import QtWidgets
from ..common.profiling import logger, profiler
from ..constants import APP_NAME
from ..image_collector.progress_notifier import close_publisher
from ..image_setting.translation import TranslatorMixin
from ..os.process import Proc
from ..qt.debounce import qt_debounce
from ..zmq.zmq import Role, ZMQBroker, ZMQNode

class TrayApp(QtWidgets.QSystemTrayIcon, TranslatorMixin):

    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        logger.info('TRAY APP EXECUTED')
        self.setToolTip(f'{APP_NAME}')
        self.menu = QtWidgets.QMenu()
        self.show_state = False
        self.show_action = self.menu.addAction(self.t.tr('Show Window'))
        self.show_action.triggered.connect(self.show_if_not)
        self.open_action = self.menu.addAction(self.t.tr('Open New Window'))
        self.open_action.triggered.connect(self.show_anyways)
        self.menu.addSeparator()
        self.reload_action = self.menu.addAction(self.t.tr('ReScan All'))
        self.reload_action.triggered.connect(self.rescan)
        self.cleanup_action = self.menu.addAction(self.t.tr('Cleanup Database'))
        self.cleanup_action.triggered.connect(self.cleanup)
        self.menu.addSeparator()
        self.test_action = self.menu.addAction(self.t.tr('Test'))
        self.test_action.triggered.connect(self.test)
        self.test_action2 = self.menu.addAction(self.t.tr('Test2'))
        self.test_action2.triggered.connect(self.test2)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction(self.t.tr('Quit'))
        self.quit_action.triggered.connect(self.quit)
        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)
        self.broker = ZMQBroker()
        self.broker.start()
        self.zmq = ZMQNode(Role.COMMUNICATOR, on_message=self.on_notify)
        self.zmq.start()
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.delete)

    def on_notify(self, v):
        logger.info(f'NOTIFY : {v}')

    def cleanup(self):
        try:
            self.zmq.send(targetprocess='ALL', table='*', topic='cleanup', message='True')
        except Exception as e:
            logger.warning(f'[toggle notify failed] {e}')

    def rescan(self):
        try:
            self.zmq.send(targetprocess='ALL', table='*', topic='rescan', message='True')
        except Exception as e:
            logger.warning(f'[toggle notify failed] {e}')

    def send_show_toggle(self, flag):
        try:
            self.zmq.send(targetprocess='ALL', table='*', topic='show_toggle', message='True' if flag else 'False')
        except Exception as e:
            logger.warning(f'[toggle notify failed] {e}')

    def get_viewer_count(self):
        try:
            return self.zmq.get_sub_count()
        except Exception as e:
            logger.warning(f'[viewer count failed] {e}')
            return 0

    @profiler.profile
    def on_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.Trigger:
            self.show_if_not()

    @qt_debounce(10)
    def show_if_not(self):
        c = self.get_viewer_count()
        logger.info(c)
        if c < 1:
            self.show_anyways()
        else:
            self.show_state = not self.show_state
            self.send_show_toggle(self.show_state)

    @qt_debounce(500)
    def show_anyways(self):
        Proc.new_main('--viewer')

    def test(self):
        logger.info('SENDING TEST')
        self.zmq.send(targetprocess='ALL', table='*', topic='none', message='TEST FUNCTION!')

    def test2(self):
        logger.info(Proc.get_subset('--collector'))

    def delete(self):
        with contextlib.suppress(Exception):
            self.zmq.stop()
        with contextlib.suppress(Exception):
            self.broker.stop()
        with contextlib.suppress(Exception):
            close_publisher()

    def quit(self):
        QtWidgets.QApplication.quit()

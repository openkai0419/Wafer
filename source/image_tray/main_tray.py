from PySide6 import QtWidgets, QtGui, QtCore
import contextlib

from ..image_collector.progress_notifier import close_publisher
from ..common.profiling import logger, profiler
from ..qt.debounce import qt_debounce
from ..common.funcs import new_main, get_setting_file_names
from ..qt.dialog import ConfirmDialog
from ..constants import APP_NAME
from ..image_setting.translation import TranslatorMixin
from ..zmq.zmq import ZMQNode, ZMQBroker, Role

class TrayApp(QtWidgets.QSystemTrayIcon, TranslatorMixin):
    @profiler.profile
    def __init__(self, icon, parent=None):
        super().__init__(icon, parent)
        logger.info("TRAY APP EXECUTED")
        self.setToolTip(f"{APP_NAME}")

        self.menu = QtWidgets.QMenu()
        self.show_state = False

        self.show_action = self.menu.addAction(self.t.tr("Show Window"))
        self.show_action.triggered.connect(self.show_if_not)
        self.open_action = self.menu.addAction(self.t.tr("Open New Window"))
        self.open_action.triggered.connect(self.show_anyways)
        self.menu.addSeparator()
        self.reload_action = self.menu.addAction(self.t.tr("ReScan All"))
        self.reload_action.triggered.connect(self.rescan)
        self.menu.addSeparator()
        self.test_action = self.menu.addAction(self.t.tr("Test"))
        self.test_action.triggered.connect(self.test)
        self.menu.addSeparator()
        self.quit_action = self.menu.addAction(self.t.tr("Quit"))
        self.quit_action.triggered.connect(self.quit)

        self.setContextMenu(self.menu)
        self.activated.connect(self.on_activated)

        self.broker = ZMQBroker()
        self.broker.start()
        self.zmq = ZMQNode(Role.COMMUNICATOR, on_message=self.on_notify)
        self.zmq.start()

        QtWidgets.QApplication.instance().aboutToQuit.connect(self.delete)
    
    def on_notify(self, v):
        logger.info(v)

    def rescan(self):
        pass

    def send_show_toggle(self, flag):
        try:
            self.zmq.send(targetprocess="viewer", table="*", topic="show_toggle", message="True" if flag else "False")
        except Exception as e:
            logger.warning(f"[toggle notify failed] {e}")

    def get_viewer_count(self):
        try:
            return self.zmq.get_sub_count()
        except Exception as e:
            logger.warning(f"[viewer count failed] {e}")
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
        new_main("--viewer")

    def test(self):
        self.zmq.send(targetprocess="ALL", table="*", topic="*", message="TEST FUNCTION!")

    def delete(self):
        # ensure background threads are stopped
        with contextlib.suppress(Exception):
            self.zmq.stop()
        with contextlib.suppress(Exception):
            self.broker.stop()
        with contextlib.suppress(Exception):
            close_publisher()

    def quit(self):
        QtWidgets.QApplication.quit()

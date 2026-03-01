from PySide6 import QtCore, QtWidgets


class WindowSnapshot:
    __slots__ = ('state', 'geometry')

    def __init__(self, window: QtWidgets.QWidget):
        self.state = window.windowState()
        self.geometry = window.normalGeometry()

    def restore(self, window: QtWidgets.QWidget):
        window.setGeometry(self.geometry)
        window.setWindowState(self.state)
        window.show()


def safe_set_window_flag(window: QtWidgets.QWidget, flag: QtCore.Qt.WindowType, on: bool):
    snap = WindowSnapshot(window)
    window.setWindowFlag(flag, on)
    snap.restore(window)

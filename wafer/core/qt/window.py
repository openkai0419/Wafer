import base64

from PySide6 import QtCore, QtWidgets


class WindowSnapshot:
    __slots__ = ('state', 'geometry')

    def __init__(self, window: QtWidgets.QWidget):
        self.state = window.windowState()
        self.geometry = window.normalGeometry()

    def apply(self, window: QtWidgets.QWidget):
        window.setGeometry(self.geometry)
        window.setWindowState(self.state)


class WindowStateController:

    def __init__(self, window: QtWidgets.QMainWindow):
        self._window = window
        self._pre_fullscreen_snap: WindowSnapshot | None = None

    @property
    def is_fullscreen(self) -> bool:
        return bool(self._window.windowState() & QtCore.Qt.WindowFullScreen)

    @property
    def is_always_on_top(self) -> bool:
        return bool(self._window.windowFlags() & QtCore.Qt.WindowStaysOnTopHint)

    def toggle_fullscreen(self):
        w = self._window
        if not self.is_fullscreen:
            self._pre_fullscreen_snap = WindowSnapshot(w)
            w.showFullScreen()
        else:
            snap = self._pre_fullscreen_snap
            self._pre_fullscreen_snap = None
            if snap and (snap.state & QtCore.Qt.WindowMaximized):
                w.showMaximized()
            else:
                w.showNormal()
                if snap:
                    w.setGeometry(snap.geometry)

    def set_always_on_top(self, on: bool):
        w = self._window
        was_fullscreen = self.is_fullscreen
        was_maximized = bool(w.windowState() & QtCore.Qt.WindowMaximized)
        w.setWindowFlag(QtCore.Qt.WindowStaysOnTopHint, on)
        if was_fullscreen:
            w.showFullScreen()
        elif was_maximized:
            w.showMaximized()
        else:
            w.showNormal()

    def restore_or_activate(self):
        w = self._window
        if w.isMinimized():
            w.setWindowState(w.windowState() & ~QtCore.Qt.WindowMinimized)
        w.show()
        w.raise_()
        w.activateWindow()

    def minimize(self):
        self._window.showMinimized()

    def save_geometry(self) -> str:
        geo_bytes = bytes(self._window.saveGeometry())
        return base64.b64encode(geo_bytes).decode('ascii')

    def restore_geometry(self, data: str):
        geo = QtCore.QByteArray(base64.b64decode(data))
        self._window.restoreGeometry(geo)

    def save_state(self) -> dict:
        return {'always_on_top': self.is_always_on_top}

    def restore_state(self, state: dict):
        if 'always_on_top' in state:
            self.set_always_on_top(state['always_on_top'])

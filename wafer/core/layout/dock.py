from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .tree import FloatingState


class PanelDockWidget(QtWidgets.QDockWidget):
    closed = QtCore.Signal(str)

    def __init__(self, name: str, title: str, parent: QtWidgets.QMainWindow | None = None):
        super().__init__(title, parent)
        self.panel_name = name
        self.setObjectName(f"panel_dock_{name}")
        self.setFeatures(
            QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
            | QtWidgets.QDockWidget.DockWidgetClosable
        )
        self.setAllowedAreas(
            QtCore.Qt.LeftDockWidgetArea
            | QtCore.Qt.RightDockWidgetArea
            | QtCore.Qt.TopDockWidgetArea
            | QtCore.Qt.BottomDockWidgetArea
        )

    def closeEvent(self, event):
        self.closed.emit(self.panel_name)
        event.accept()


class FloatingWindow(QtWidgets.QWidget):
    closed = QtCore.Signal(str)

    def __init__(self, name: str, title: str, widget: QtWidgets.QWidget):
        super().__init__(None, QtCore.Qt.Window | QtCore.Qt.WindowCloseButtonHint)
        self.panel_name = name
        self.setWindowTitle(title)
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        widget.setParent(self)
        layout.addWidget(widget)
        widget.show()

    def closeEvent(self, event):
        self.closed.emit(self.panel_name)
        event.accept()

    def take_widget(self) -> QtWidgets.QWidget | None:
        layout = self.layout()
        if layout and layout.count() > 0:
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(None)
                return w
        return None


def create_dock(
    name: str,
    title: str,
    widget: QtWidgets.QWidget,
    window: QtWidgets.QMainWindow,
    area: QtCore.Qt.DockWidgetArea = QtCore.Qt.LeftDockWidgetArea,
) -> PanelDockWidget:
    dock = PanelDockWidget(name, title, window)
    widget.setParent(dock)
    dock.setWidget(widget)
    window.addDockWidget(area, dock)
    return dock


def apply_floating(
    name: str,
    title: str,
    widget: QtWidgets.QWidget,
    state: FloatingState | None = None,
) -> FloatingWindow:
    win = FloatingWindow(name, title, widget)
    if state:
        win.setGeometry(state.x, state.y, state.width, state.height)
    else:
        win.resize(400, 300)
    win.show()
    return win


def capture_floating_state(win: FloatingWindow) -> FloatingState:
    geo = win.geometry()
    return FloatingState(geo.x(), geo.y(), geo.width(), geo.height())

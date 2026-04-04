from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ...utils.formatting import dpix
from .tree import FloatingState


class PanelDockWidget(QtWidgets.QDockWidget):
    closed = QtCore.Signal(str)

    def __init__(self, name: str, parent: QtWidgets.QMainWindow | None = None, *, closable: bool = True):
        super().__init__(name, parent)
        self.panel_name = name
        self.setObjectName(f"panel_dock_{name}")
        features = (
            QtWidgets.QDockWidget.DockWidgetMovable
            | QtWidgets.QDockWidget.DockWidgetFloatable
        )
        if closable:
            features |= QtWidgets.QDockWidget.DockWidgetClosable
        self.setFeatures(features)
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

    def __init__(self, name: str, widget: QtWidgets.QWidget, parent: QtWidgets.QWidget | None = None):
        super().__init__(
            parent,
            QtCore.Qt.Window
            | QtCore.Qt.WindowCloseButtonHint
            | QtCore.Qt.WindowMinimizeButtonHint
            | QtCore.Qt.WindowMaximizeButtonHint,
        )
        self.panel_name = name
        self.setWindowTitle(name)
        layout = QtWidgets.QVBoxLayout(self)
        m = dpix(5)
        layout.setContentsMargins(m, m, m, m)
        widget.setParent(self)
        layout.addWidget(widget)

    def closeEvent(self, event):
        self.closed.emit(self.panel_name)
        event.accept()


def create_dock(
    name: str,
    widget: QtWidgets.QWidget,
    window: QtWidgets.QMainWindow,
    area: QtCore.Qt.DockWidgetArea = QtCore.Qt.LeftDockWidgetArea,
    *,
    closable: bool = True,
) -> PanelDockWidget:
    dock = PanelDockWidget(name, window, closable=closable)
    widget.setParent(dock)
    dock.setWidget(widget)
    window.addDockWidget(area, dock)
    return dock


def apply_floating(
    name: str,
    widget: QtWidgets.QWidget,
    state: FloatingState | None = None,
    parent: QtWidgets.QWidget | None = None,
) -> FloatingWindow:
    win = FloatingWindow(name, widget, parent)
    if state:
        win.setGeometry(state.x, state.y, state.width, state.height)
    else:
        win.resize(400, 300)
    win.show()
    return win


def capture_floating_state(widget: QtWidgets.QWidget) -> FloatingState:
    geo = widget.geometry()
    return FloatingState(geo.x(), geo.y(), geo.width(), geo.height())

from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from .tree import FloatingState


class PanelDockWidget(QtWidgets.QDockWidget):
    closed = QtCore.Signal(str)

    def __init__(self, name: str, parent: QtWidgets.QMainWindow | None = None):
        super().__init__(name, parent)
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

    def __init__(self, name: str, widget: QtWidgets.QWidget, parent: QtWidgets.QWidget | None = None):
        super().__init__(parent, QtCore.Qt.Window | QtCore.Qt.WindowCloseButtonHint)
        self.panel_name = name
        self.setWindowTitle(name)
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
    widget: QtWidgets.QWidget,
    window: QtWidgets.QMainWindow,
    area: QtCore.Qt.DockWidgetArea = QtCore.Qt.LeftDockWidgetArea,
) -> PanelDockWidget:
    dock = PanelDockWidget(name, window)
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

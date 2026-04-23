from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


_FILTER_PROPERTY = "_wafer_instant_tooltip_filter"
_DISABLED_PROPERTY = "wafer_disable_instant_tooltip"


def _tooltip_text(target) -> str:
    text = getattr(target, "toolTip", None)
    if callable(text):
        return text() or ""
    return ""


def _global_pos(event) -> QtCore.QPoint:
    global_pos = getattr(event, "globalPos", None)
    if callable(global_pos):
        return global_pos()
    return QtGui.QCursor.pos()


class InstantTooltipEventFilter(QtCore.QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_target = None

    def eventFilter(self, obj, event):
        if bool(getattr(obj, "property", lambda *_: False)(_DISABLED_PROPERTY)):
            return super().eventFilter(obj, event)
        if not isinstance(obj, (QtWidgets.QWidget, QtWidgets.QGraphicsObject, QtWidgets.QGraphicsWidget)):
            return super().eventFilter(obj, event)

        text = _tooltip_text(obj)
        if not text:
            if self._current_target is obj:
                QtWidgets.QToolTip.hideText()
                self._current_target = None
            return super().eventFilter(obj, event)

        event_type = event.type()
        if event_type in (QtCore.QEvent.Enter, QtCore.QEvent.HoverEnter, QtCore.QEvent.MouseMove, QtCore.QEvent.HoverMove):
            self._show_tooltip(obj, text, _global_pos(event))
            return super().eventFilter(obj, event)
        if event_type == QtCore.QEvent.ToolTip:
            self._show_tooltip(obj, text, _global_pos(event))
            return True
        if event_type in (QtCore.QEvent.Leave, QtCore.QEvent.HoverLeave, QtCore.QEvent.Hide, QtCore.QEvent.FocusOut, QtCore.QEvent.WindowDeactivate):
            if self._current_target is obj:
                QtWidgets.QToolTip.hideText()
                self._current_target = None
        return super().eventFilter(obj, event)

    def _show_tooltip(self, obj, text: str, global_pos: QtCore.QPoint):
        if isinstance(obj, QtWidgets.QWidget):
            rect = obj.rect()
            widget = obj
        else:
            rect = QtCore.QRect()
            widget = None
        QtWidgets.QToolTip.showText(global_pos, text, widget, rect)
        self._current_target = obj


def install_instant_tooltips(app: QtWidgets.QApplication | None = None):
    app = app or QtWidgets.QApplication.instance()
    if app is None:
        return None
    existing = app.property(_FILTER_PROPERTY)
    if existing is not None:
        return existing
    tooltip_filter = InstantTooltipEventFilter(app)
    app.installEventFilter(tooltip_filter)
    app.setProperty(_FILTER_PROPERTY, tooltip_filter)
    return tooltip_filter

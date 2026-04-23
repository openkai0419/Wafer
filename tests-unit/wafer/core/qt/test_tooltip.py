from PySide6 import QtCore, QtGui, QtWidgets


def test_install_instant_tooltips_is_idempotent(qtbot):
    from wafer.core.qt.tooltip import install_instant_tooltips

    app = QtWidgets.QApplication.instance()
    first = install_instant_tooltips(app)
    second = install_instant_tooltips(app)
    assert first is second


def test_instant_tooltip_filter_shows_on_enter(qtbot, monkeypatch):
    from wafer.core.qt.tooltip import InstantTooltipEventFilter

    button = QtWidgets.QPushButton()
    button.setToolTip("Hello")
    qtbot.addWidget(button)

    shown = []
    monkeypatch.setattr(QtWidgets.QToolTip, "showText", lambda *args, **kwargs: shown.append(args[1]))

    tooltip_filter = InstantTooltipEventFilter()
    tooltip_filter.eventFilter(button, QtCore.QEvent(QtCore.QEvent.Enter))

    assert shown == ["Hello"]


def test_instant_tooltip_filter_consumes_tooltip_event(qtbot, monkeypatch):
    from wafer.core.qt.tooltip import InstantTooltipEventFilter

    button = QtWidgets.QPushButton()
    button.setToolTip("Hello")
    qtbot.addWidget(button)

    shown = []
    monkeypatch.setattr(QtWidgets.QToolTip, "showText", lambda *args, **kwargs: shown.append(args[1]))

    tooltip_filter = InstantTooltipEventFilter()
    event = QtGui.QHelpEvent(QtCore.QEvent.ToolTip, QtCore.QPoint(1, 1), QtCore.QPoint(10, 10))

    assert tooltip_filter.eventFilter(button, event) is True
    assert shown == ["Hello"]
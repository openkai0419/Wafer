from PySide6 import QtCore, QtGui, QtWidgets
from wafer.ui.popups import PopupBase


def test_popup_base_flags(qtbot):
    popup = PopupBase()
    qtbot.addWidget(popup)
    flags = popup.windowFlags()
    assert flags & QtCore.Qt.Popup
    assert flags & QtCore.Qt.FramelessWindowHint
    assert not popup.testAttribute(QtCore.Qt.WA_TranslucentBackground)
    assert popup.autoFillBackground()


def test_show_below_clamps_to_screen(qtbot):
    anchor = QtWidgets.QPushButton("anchor")
    anchor.resize(80, 24)
    anchor.show()
    qtbot.addWidget(anchor)
    popup = PopupBase(anchor)
    popup.setLayout(QtWidgets.QVBoxLayout())
    popup.layout().addWidget(QtWidgets.QLabel("popup"))
    qtbot.addWidget(popup)
    popup.show_below(anchor)
    screen = QtWidgets.QApplication.screenAt(popup.pos()) or QtWidgets.QApplication.primaryScreen()
    assert screen is not None
    assert screen.availableGeometry().contains(popup.geometry())


def test_escape_closes_popup(qtbot):
    popup = PopupBase()
    qtbot.addWidget(popup)
    popup.show()
    assert popup.isVisible()
    event = QtGui.QKeyEvent(QtCore.QEvent.KeyPress, QtCore.Qt.Key_Escape, QtCore.Qt.NoModifier)
    popup.keyPressEvent(event)
    assert not popup.isVisible()


def test_closed_signal_on_hide(qtbot):
    popup = PopupBase()
    qtbot.addWidget(popup)
    closed = []
    popup.closed.connect(lambda: closed.append(True))
    popup.show()
    popup.hide()
    assert closed
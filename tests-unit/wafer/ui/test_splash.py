import py_compile

import pytest
from PySide6 import QtWidgets, QtCore

from wafer.utils.formatting import dpix
from wafer.ui.splash import InstallSplash


@pytest.fixture
def app():
    instance = QtWidgets.QApplication.instance()
    if instance is None:
        instance = QtWidgets.QApplication([])
    return instance


def test_compile():
    py_compile.compile("wafer/ui/splash.py")


def test_creates_borderless_window(app):
    splash = InstallSplash("Test")
    flags = splash.windowFlags()
    assert flags & QtCore.Qt.FramelessWindowHint
    assert flags & QtCore.Qt.Window


def test_window_title(app):
    splash = InstallSplash("MyApp")
    assert splash.windowTitle() == "MyApp"


def test_custom_message(app):
    splash = InstallSplash("T", message="Loading...")
    labels = splash.findChildren(QtWidgets.QLabel)
    texts = [l.text() for l in labels if l.text()]
    assert "Loading..." in texts


def test_show_triggers_process_events(app):
    splash = InstallSplash("Test")
    splash.show()
    assert splash.isVisible()
    splash.close()


def test_fixed_size(app):
    splash = InstallSplash("Test", show_log=False)
    assert splash.width() == dpix(360)
    assert splash.height() == dpix(80)


def test_log_area_present_by_default(app):
    splash = InstallSplash("Test")
    assert splash.findChild(QtWidgets.QPlainTextEdit) is not None
    assert splash.height() > dpix(80)


def test_append_log_writes_text(app):
    splash = InstallSplash("Test")
    splash.append_log("Collecting numpy")
    splash.append_log("Installing collected packages")
    log = splash.findChild(QtWidgets.QPlainTextEdit)
    assert "Collecting numpy" in log.toPlainText()
    assert "Installing collected packages" in log.toPlainText()


def test_append_log_noop_when_disabled(app):
    splash = InstallSplash("Test", show_log=False)
    splash.append_log("ignored")
    assert splash.findChild(QtWidgets.QPlainTextEdit) is None


def test_window_icon_set(app):
    from PySide6 import QtGui
    pix = QtGui.QPixmap(16, 16)
    pix.fill(QtGui.QColor("red"))
    icon = QtGui.QIcon(pix)
    splash = InstallSplash("Test", icon=icon)
    assert not splash.windowIcon().isNull()

import pytest
from PySide6 import QtWidgets

from wafer.qt.common.dpi import dpix
from wafer.qt.install.splash import InstallSplash


@pytest.fixture
def app():
    instance = QtWidgets.QApplication.instance()
    if instance is None:
        instance = QtWidgets.QApplication([])
    return instance


def test_log_area_present_by_default(app):
    splash = InstallSplash("Test")
    assert splash.findChild(QtWidgets.QTextEdit) is not None
    assert splash.height() > dpix(80)


def test_append_log_writes_text(app):
    splash = InstallSplash("Test")
    splash.append_log("Collecting numpy")
    splash.append_log("Installing collected packages")
    log = splash.findChild(QtWidgets.QTextEdit)
    assert "Collecting numpy" in log.toPlainText()
    assert "Installing collected packages" in log.toPlainText()


def test_append_log_noop_when_disabled(app):
    splash = InstallSplash("Test", show_log=False)
    splash.append_log("ignored")
    assert splash.findChild(QtWidgets.QTextEdit) is None

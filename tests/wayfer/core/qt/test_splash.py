import py_compile

import pytest
from PySide6 import QtWidgets, QtCore

from wayfer.utils.formatting import dpix
from wayfer.core.qt.splash import InstallSplash


@pytest.fixture
def app():
    instance = QtWidgets.QApplication.instance()
    if instance is None:
        instance = QtWidgets.QApplication([])
    return instance


def test_compile():
    py_compile.compile('wayfer/core/qt/splash.py')


def test_creates_borderless_window(app):
    splash = InstallSplash('Test')
    flags = splash.windowFlags()
    assert flags & QtCore.Qt.FramelessWindowHint
    assert flags & QtCore.Qt.Window


def test_window_title(app):
    splash = InstallSplash('MyApp')
    assert splash.windowTitle() == 'MyApp'


def test_custom_message(app):
    splash = InstallSplash('T', message='Loading...')
    labels = splash.findChildren(QtWidgets.QLabel)
    texts = [l.text() for l in labels if l.text()]
    assert 'Loading...' in texts


def test_show_triggers_process_events(app):
    splash = InstallSplash('Test')
    splash.show()
    assert splash.isVisible()
    splash.close()


def test_fixed_size(app):
    splash = InstallSplash('Test')
    assert splash.width() == dpix(360)
    assert splash.height() == dpix(80)

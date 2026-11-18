from PySide6 import QtCore, QtWidgets
from PySide6.QtTest import QTest
import pytest

from wafer.qt.layout import standalone
from wafer.qt.layout.standalone import open_standalone


@pytest.fixture(autouse=True)
def clean_registry():
    standalone._standalone_dialogs.clear()
    yield
    for dlg in list(standalone._standalone_dialogs.values()):
        dlg.close()
    standalone._standalone_dialogs.clear()
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def flush_deletes():
    QtCore.QCoreApplication.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)
    QtCore.QCoreApplication.processEvents()


def test_escape_closes_and_the_dialog_reopens(qtbot):
    first = open_standalone(QtWidgets.QLabel, "Title", "standalone_escape_test")
    dlg = first.window()
    qtbot.waitExposed(dlg)

    QTest.keyClick(dlg, QtCore.Qt.Key_Escape)
    flush_deletes()

    assert "standalone_escape_test" not in standalone._standalone_dialogs
    second = open_standalone(QtWidgets.QLabel, "Title", "standalone_escape_test")
    assert second is not first
    assert second.window().isVisible()


def test_close_button_removes_the_dialog(qtbot):
    content = open_standalone(QtWidgets.QLabel, "Title", "standalone_close_test")
    qtbot.waitExposed(content.window())

    content.window().close()
    flush_deletes()

    assert "standalone_close_test" not in standalone._standalone_dialogs


def test_visible_dialog_is_reused(qtbot):
    first = open_standalone(QtWidgets.QLabel, "Title", "standalone_reuse_test")
    qtbot.waitExposed(first.window())

    assert open_standalone(QtWidgets.QLabel, "Title", "standalone_reuse_test") is first


def test_geometry_is_saved_on_escape(qtbot):
    content = open_standalone(QtWidgets.QLabel, "Title", "standalone_geometry_test", size=(321, 234))
    dlg = content.window()
    qtbot.waitExposed(dlg)

    QTest.keyClick(dlg, QtCore.Qt.Key_Escape)
    flush_deletes()

    reopened = open_standalone(QtWidgets.QLabel, "Title", "standalone_geometry_test", size=(600, 600))
    qtbot.waitExposed(reopened.window())
    assert reopened.window().size() == QtCore.QSize(321, 234)

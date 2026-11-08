from unittest.mock import MagicMock, patch

from PySide6 import QtCore, QtWidgets

from wafer.app.webui.window import WebUIWindow


def test_the_lock_follows_the_native_window_when_qt_recreates_it():
    window = WebUIWindow.__new__(WebUIWindow)
    window._lock = MagicMock()
    window.winId = MagicMock(return_value=77)

    with patch.object(QtWidgets.QWidget, "event", return_value=True):
        assert WebUIWindow.event(window, QtCore.QEvent(QtCore.QEvent.WinIdChange)) is True
        WebUIWindow.event(window, QtCore.QEvent(QtCore.QEvent.LayoutRequest))

    window._lock.set_window.assert_called_once_with(77)

import pytest
from PySide6 import QtWidgets


class _QtBot:
    def __init__(self):
        self._widgets = []

    def addWidget(self, widget):
        self._widgets.append(widget)
        widget.show()
        QtWidgets.QApplication.processEvents()


@pytest.fixture
def qtbot():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    bot = _QtBot()
    yield bot
    for w in reversed(bot._widgets):
        w.close()
    QtWidgets.QApplication.processEvents()

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest
from PySide6 import QtWidgets
from source.plugin_core.loader import load_plugins
from source.actions.command.state import CommandOptionStore

load_plugins(skip_install=True)

_test_temp_dir = tempfile.TemporaryDirectory()
CommandOptionStore.configure(Path(_test_temp_dir.name) / ".command_options.json")


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

import pytest
from PySide6 import QtWidgets

from source.actions.bridge import Menu


def test_build_menu_ignores_unknown_item(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    result = Menu.session(w).menu(["__unknown_command_or_folder__"])
    assert result is None


def test_build_menu_does_not_expand_string_to_chars(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    result = Menu.session(w).menu("menu")
    assert result is None

import pytest
from PySide6 import QtWidgets

from afterimages.core.actions.bridge import Menu
from afterimages.core.actions.command.maker import MenuMaker, MenuHub
from afterimages.core.actions.command.menu import is_sep_token, is_section_token


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


class TestRebaseToken:
    def test_command_strips_root(self):
        assert MenuMaker._flatten_for_use(None, "file/open", "file") == "open"

    def test_command_nested_strips_root(self):
        assert MenuMaker._flatten_for_use(None, "file/edit/paste", "file") == "edit/paste"

    def test_command_different_root_unchanged(self):
        assert MenuMaker._flatten_for_use(None, "view/zoom", "file") == "view/zoom"

    def test_sep_strips_root(self):
        result = MenuMaker._flatten_for_use(None, "file/-", "file")
        assert result == "-"
        assert is_sep_token(result)

    def test_sep_nested_strips_root(self):
        result = MenuMaker._flatten_for_use(None, "file/edit/-", "file")
        assert result == "edit/-"
        assert is_sep_token(result)

    def test_section_strips_root(self):
        result = MenuMaker._flatten_for_use(None, "file/:Section", "file")
        assert result == ":Section"
        assert is_section_token(result)

    def test_section_nested_strips_root(self):
        result = MenuMaker._flatten_for_use(None, "file/sub/:Label", "file")
        assert result == "sub/:Label"
        assert is_section_token(result)

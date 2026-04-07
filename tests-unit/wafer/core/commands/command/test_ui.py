import pytest
from PySide6 import QtWidgets

from wafer.core.commands.bridge import Menu
from wafer.core.commands.command.maker import MenuMaker, MenuHub
from wafer.core.commands.command.menu import is_sep_token, is_section_token


def test_build_menu_shows_unfound_for_unknown_item(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    spec = Menu.session(w).menu(["__unknown_command_or_folder__"])
    assert spec is not None
    menu_widget = spec.build()
    actions = menu_widget.actions()
    assert len(actions) == 1
    assert not actions[0].isEnabled()
    assert actions[0].text() == "- Unenabled __unknown_command_or_folder__"


def test_build_menu_does_not_expand_string_to_chars(qtbot):
    w = QtWidgets.QWidget()
    qtbot.addWidget(w)
    spec = Menu.session(w).menu("menu")
    assert spec is not None
    menu_widget = spec.build()
    actions = menu_widget.actions()
    assert len(actions) == 1
    assert "menu" in actions[0].text()


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

from PySide6 import QtWidgets

from source.actions.bridge import Menu
from source.actions.command.core import CommandRegistry
from source.image_viewer.commands.foldertree import FolderTreeCommands


def test_foldertree_commands_register_paths(qtbot):
    FolderTreeCommands.register()
    assert CommandRegistry().has_command("ft.menu")
    assert CommandRegistry().has_command("ft.reload_tree")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["ft.reload_tree"]).build()
    assert m is not None
    assert m.actions()

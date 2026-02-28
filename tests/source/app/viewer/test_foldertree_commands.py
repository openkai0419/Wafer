from PySide6 import QtWidgets

from source.core.actions.bridge import Menu
from source.core.actions.command.core import CommandRegistry
from source.app.viewer.commands.foldertree_commands import FolderTreeCommands


def test_foldertree_commands_register_paths(qtbot):
    FolderTreeCommands.register()
    assert CommandRegistry().has_command("ft.reload_tree")
    assert CommandRegistry().has_command("ft.next_folder_dfs")
    assert CommandRegistry().has_command("ft.prev_folder_dfs")
    assert CommandRegistry().has_command("ft.next_folder_visible")
    assert CommandRegistry().has_command("ft.prev_folder_visible")
    assert CommandRegistry().has_command("ft.parent_folder")
    assert CommandRegistry().has_command("ft.child_folder")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["ft.reload_tree"]).build()
    assert m is not None
    assert m.actions()

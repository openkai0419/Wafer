from PySide6 import QtWidgets

from source.actions.bridge import Menu
from source.actions.command.core import CommandRegistry
from source.image_viewer.commands.justified_view import JustifiedViewCommands, JustifiedViewDropCommands


def test_justified_view_commands_register_paths(qtbot):
    JustifiedViewCommands.register()
    JustifiedViewDropCommands.register()
    assert CommandRegistry().has_command("jv.drop_files_copy")
    assert CommandRegistry().has_command("jv.drop_files_move")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["jv.show_selected", "jv.select_all", "jv.scale_up", "jv.move_to_next_row"]).build()
    assert m is not None
    assert m.actions()

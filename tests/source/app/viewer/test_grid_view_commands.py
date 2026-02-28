from PySide6 import QtWidgets

from source.core.actions.bridge import Menu
from source.core.actions.command.core import CommandRegistry
from source.app.viewer.commands.grid_commands import GridViewCommands, GridViewDropCommands


def test_grid_view_commands_register_paths(qtbot):
    GridViewCommands.register()
    GridViewDropCommands.register()
    assert CommandRegistry().has_command("grid.drop_files_copy")
    assert CommandRegistry().has_command("grid.drop_files_move")
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["grid.show_selected", "grid.select_all", "grid.scale_up", "grid.move_to_next_row"]).build()
    assert m is not None
    assert m.actions()

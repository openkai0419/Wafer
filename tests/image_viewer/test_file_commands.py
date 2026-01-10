from source.actions.bridge import Menu
from source.image_viewer.commands.file_commands import FileCommands
from PySide6 import QtWidgets


def test_file_commands_register_paths(qtbot):
    FileCommands.register()
    parent = QtWidgets.QWidget()
    qtbot.addWidget(parent)
    m = Menu.session(parent).menu(["file.copy_path", "file.paste"]).build()
    assert m is not None
    assert m.actions()

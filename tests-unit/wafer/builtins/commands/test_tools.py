from functools import partial

from wafer.builtins.commands.panel import open_panel
from wafer.builtins.commands.tools import ToolCommands


def test_tools_menu_lists_folder_manager_after_batch_renamer():
    items = ToolCommands.commands()
    paths = [getattr(item, "path", item) for item in items]
    tools = paths.index(":Tools")
    assert paths[tools + 1 : tools + 3] == ["setting.batch_renamer", "setting.folder_manager"]
    command = items[tools + 2]
    assert command.display == "Folder Manager"
    assert isinstance(command.func, partial) and command.func.func is open_panel
    assert command.func.keywords == {"name": "Folder Manager"}
    assert ToolCommands.SCOPE == "*"

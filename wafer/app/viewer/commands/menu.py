from ....core.commands.bridge import ActionKit, Menu, Settings
from ....core.commands.command.menu import discover_command_classes
from ....utils.paths import resolve_data_path
from . import (
    file_commands,
    foldertree_commands,
    image_view,
    file_viewer,
    grid_commands,
    window_commands,
    query_commands,
    database_commands,
    setting_commands,
    debug_commands,
    session_commands,
)
from ...plugin_manager import commands as plugin_manager_commands
from .file_commands import FileCommands
from .foldertree_commands import show_context_menu
from .image_view import ImageViewCommands
from .setting_commands import _restore_thumbnail_size


_COMMAND_MODULES = [
    file_commands,
    query_commands,
    foldertree_commands,
    grid_commands,
    file_viewer,
    image_view,
    window_commands,
    database_commands,
    setting_commands,
    debug_commands,
    session_commands,
    plugin_manager_commands,
]


class AppMenuRegistrar(ActionKit.MenuBase):
    NAME = ""
    PRIORITY = 110

    @classmethod
    def commands(cls):
        return [
            "menus/:Menus",
            ActionKit.Command(path="menus/showimageviewmenu", display="Image View Menu", func=lambda ctx: Menu.exec_menu(ImageViewCommands.NAME, ctx)),
            ActionKit.Command(path="menus/showfilemenu", display="File View Menu", func=lambda ctx: Menu.exec_menu(FileCommands.NAME, ctx)),
            ActionKit.Command(path="menus/showfoldertreemenu", display="Folder Tree Menu", func=lambda ctx: show_context_menu(ctx)),
            ActionKit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx)),
        ]

    @staticmethod
    def setup_menu():
        Settings.configure(
            mouse_bindings=str(resolve_data_path("binding/mouse_bindings.json")),
            key_bindings=str(resolve_data_path("binding/key_bindings.json")),
            command_options=str(resolve_data_path("binding/command_options.json")),
        )
        for cls in discover_command_classes(*_COMMAND_MODULES):
            cls.register()
        AppMenuRegistrar.register()
        _restore_thumbnail_size()
        Settings.activate()



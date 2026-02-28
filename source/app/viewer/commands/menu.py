from source.core.actions.bridge import ActionKit, Menu, Settings, UI
from source.core.actions.command.menu import discover_command_classes
from source.utils.paths import resolve_data_path
from source.core.platform.folders import show_in_explorer
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
)
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
]


class AppMenuRegistrar(ActionKit.MenuBase):
    NAME = ""

    @classmethod
    def commands(cls):
        return [
            "menus/:Menus",
            ActionKit.Command(path="menus/showimageviewmenu", display="Image View Menu", func=lambda ctx: Menu.exec_menu(ImageViewCommands.NAME, ctx)),
            ActionKit.Command(path="menus/showfilemenu", display="File View Menu", func=lambda ctx: Menu.exec_menu(FileCommands.NAME, ctx)),
            ActionKit.Command(path="menus/showfoldertreemenu", display="Folder Tree Menu", func=lambda ctx: show_context_menu(ctx)),
            "binding/:Binding",
            ActionKit.Command(path="binding/keybind", display="Key Binding Window", func=lambda ctx: UI.open_shortcut_binding_editor(parent=AppMenuRegistrar._get_parent(ctx))),
            ActionKit.Command(path="binding/mousebind", display="Mouse Binding Window", func=lambda ctx: UI.open_mouse_binding_editor(parent=AppMenuRegistrar._get_parent(ctx))),
            ActionKit.Command(path="binding/openbindingfolder", display="Open Binding Files in Explorer", func=lambda ctx: show_in_explorer(str(resolve_data_path("binding/")), show_first_if_folder=True)),
            ActionKit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx)),
        ]

    @staticmethod
    def _get_parent(ctx):
        return ctx.get("widget") or None

    @staticmethod
    def setup_menu():
        for cls in discover_command_classes(*_COMMAND_MODULES):
            cls.register()
        AppMenuRegistrar.register()
        _restore_thumbnail_size()

        Settings.configure(
            mouse_bindings=str(resolve_data_path("binding/mouse_bindings.json")),
            key_bindings=str(resolve_data_path("binding/key_bindings.json")),
            command_options=str(resolve_data_path("binding/command_options.json")),
        )
        Settings.activate()



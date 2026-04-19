from ...core.commands.bridge import ActionKit, Menu, Settings
from ...utils.paths import resolve_data_path
from .file import FileCommands
from .foldertree import show_context_menu
from .image_viewer import ImageViewCommands
from .setting import _restore_thumbnail_size


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
        from wafer.plugin.loader import get_command_registry

        registry = get_command_registry()
        registry.activate("viewer")
        _restore_thumbnail_size()
        Settings.activate()

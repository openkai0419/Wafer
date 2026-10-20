from ...qt.commands.bridge import ActionKit, Menu, Settings
from ...core.common.paths import resolve_data_path
from .file import FileCommands, FileNavigationCommands
from .foldertree import show_context_menu
from ..image_viewer.commands import ImageViewCommands
from .setting import _restore_thumbnail_size


class AppMenuRegistrar(ActionKit.MenuBase):
    NAME = ActionKit.MenuPath.MENUS
    PRIORITY = 27

    @classmethod
    def commands(cls):
        return [
            ":Menus",
            ActionKit.Command(path="showimageviewmenu", display="Image View Menu", func=lambda ctx: Menu.exec_menu(ImageViewCommands.NAME, ctx)),
            ActionKit.Command(path="showfilemenu", display="File View Menu", func=lambda ctx: Menu.exec_menu([FileCommands.NAME, FileNavigationCommands.NAME], ctx)),
            ActionKit.Command(path="showfoldertreemenu", display="Folder Tree Menu", func=lambda ctx: show_context_menu(ctx)),
            ActionKit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx), hidden=True),
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

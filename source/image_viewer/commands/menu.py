from ...actions.bridge import Kit, Menu, Settings, UI
from ...common.funcs import data_path
from ...os.folders import show_in_explorer

from .file_commands import FileCommands
from .foldertree_view import FolderTreeCommands, show_context_menu
from .image_view import ImageViewCommands, ImageViewDragCommands
from .file_viewer import FileViewerCommands
from .grid_view import GridViewCommands, GridViewDragCommands, GridViewDropCommands
from .window_commands import WindowCommands
from .query_commands import QueryCommands
from .database_commands import DatabaseCommands
from .debug_commands import DebugCommands


class MenuMenu(Kit.MenuBase):
    prefix = ""

    commands = [
        "menus/:Menus",
        Kit.Command(path="menus/showimageviewmenu", display="Image View Menu", func=lambda ctx: Menu.exec_menu(ImageViewCommands.prefix, ctx)),
        Kit.Command(path="menus/showfilemenu",  display="File View Menu", func=lambda ctx: Menu.exec_menu(FileCommands.prefix, ctx)),
        Kit.Command(path="menus/showfoldertreemenu", display="Folder Tree Menu", func=lambda ctx: show_context_menu(ctx)),
        "binding/:Binding",
        Kit.Command(path="binding/keybind",  display="Key Binding Window", func=lambda ctx: UI.open_shortcut_binding_editor(parent=MenuMenu._get_parent(ctx))),
        Kit.Command(path="binding/mousebind",  display="Mouse Binding Window", func=lambda ctx: UI.open_mouse_binding_editor(parent=MenuMenu._get_parent(ctx))),
        Kit.Command(path="binding/openbindingfolder", display="Open Binding Files in Explorer", func=lambda ctx: show_in_explorer(str(data_path("binding/")), show_first_if_folder=True)),
        Kit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx)),
    ]

    @staticmethod
    def _get_parent(ctx):
        return ctx.get("widget") or None

    @staticmethod
    def setup_menu():
        FileCommands.register()
        QueryCommands.register()
        FolderTreeCommands.register()
        GridViewCommands.register()
        GridViewDragCommands.register()
        GridViewDropCommands.register()
        FileViewerCommands.register()
        ImageViewCommands.register()
        ImageViewDragCommands.register()
        DatabaseCommands.register()
        WindowCommands.register()
        DebugCommands.register()
        MenuMenu.register()

        Settings.configure(
        mouse_bindings=str(data_path("binding/mouse_bindings.json")),
        key_bindings=str(data_path("binding/key_bindings.json")),
        command_options=str(data_path("binding/command_options.json")),
        )
        Settings.activate()



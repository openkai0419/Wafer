from ...actions.bridge import Kit, Menu, Settings, UI
from ...common.funcs import data_path

from .file_commands import FileCommands
from .foldertree import FolderTreeCommands, show_context_menu
from .graphics_view import GraphicsViewCommands, GraphicsViewDragCommands
from .file_viewer import FileViewerCommands
from .justified_view import JustifiedViewCommands, JustifiedViewDragCommands, JustifiedViewDropCommands


class MenuMenu(Kit.MenuBase):
    prefix = ""

    commands = [
        Kit.Command(path="debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug())),
        Kit.Command(path="menus/showgraphicsviewmenu", display="Graphics View Menu", func=lambda ctx: Menu.exec_menu(GraphicsViewCommands.prefix, ctx)),
        Kit.Command(path="menus/showfilemenu",  display="File View Menu", func=lambda ctx: Menu.exec_menu(FileCommands.prefix, ctx)),
        Kit.Command(path="menus/showfoldertreemenu", display="Folder Tree Menu", func=lambda ctx: show_context_menu(ctx)),
        Kit.Command(path="binding/keybind",  display="Key Binding Window", func=lambda ctx: UI.open_shortcut_binding_editor(parent=MenuMenu._get_parent(ctx))),
        Kit.Command(path="binding/mousebind",  display="Mouse Binding Window", func=lambda ctx: UI.open_mouse_binding_editor(parent=MenuMenu._get_parent(ctx))),
        Kit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx)),
    ]

    @staticmethod
    def _get_parent(ctx):
        return ctx.get("widget") or None

    @staticmethod
    def setup_menu():
        FileCommands.register()
        FolderTreeCommands.register()
        JustifiedViewCommands.register()
        JustifiedViewDragCommands.register()
        JustifiedViewDropCommands.register()
        FileViewerCommands.register()
        GraphicsViewCommands.register()
        GraphicsViewDragCommands.register()
        MenuMenu.register()

        Settings.configure(
        mouse_bindings=str(data_path("binding/mouse_bindings.json")),
        key_bindings=str(data_path("binding/key_bindings.json")),
        command_options=str(data_path("binding/command_options.json")),
        )
        from .defaults import default_key_bindings, default_mouse_bindings
        Settings.activate(mouse_bindings=default_mouse_bindings(), key_bindings=default_key_bindings())



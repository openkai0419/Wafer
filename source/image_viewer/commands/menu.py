from ...actions.bridge import Kit, Menu, Settings, UI
from ...common.funcs import data_path

from .file_commands import FileCommands
from .graphicsview import GraphicsViewCommands


def setup():
    FileCommands.register()
    GraphicsViewCommands.register()

    Settings.configure(
    mouse_bindings=str(data_path("binding/mouse_bindings.json")),
    key_bindings=str(data_path("binding/key_bindings.json")),
    command_options=str(data_path("binding/command_options.json")),
    )
    from .defaults import default_key_bindings, default_mouse_bindings
    Settings.activate(mouse_bindings=default_mouse_bindings(), key_bindings=default_key_bindings())

class MenuMenu(Kit.MenuBase):
    prefix = "menu"

    def __get_parent(self, ctx):
        return ctx.get("widget") if ctx is not None and hasattr(ctx, "get") else None

    def create_definitions(self):
        setup()

        return [
            Kit.Command(path="debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug())),
            Kit.Command(path="menus/showgraphicsviewmenu", display="Graphics View", func=lambda ctx: Menu.exec_menu(GraphicsViewCommands.prefix, ctx=ctx)),
            Kit.Command(path="menus/showfilemenu",  display="File View", func=lambda ctx: Menu.exec_menu(FileCommands.prefix, ctx=ctx)),
            Kit.Command(path="binding/keybind",  display="Key Binding", func=lambda ctx: UI.open_shortcut_binding_editor(parent=self.__get_parent(ctx))),
            Kit.Command(path="binding/mousebind",  display="Mouse Binding", func=lambda ctx: UI.open_mouse_binding_editor(parent=self.__get_parent(ctx))),
            Kit.Command(path="allmenu", display="AllMenu", func=lambda ctx: Menu.exec_all_roots(ctx=ctx)),
        ]
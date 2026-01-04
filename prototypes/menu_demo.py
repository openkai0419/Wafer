from datetime import datetime

from PySide6 import QtCore, QtGui, QtWidgets
from source.actions.bridge import Command, Context, Kit, Menu, Settings, UI
from source.common.errors import show_warning


class FileMenu(Kit.MenuBase):
    prefix = "file"
    def create_definitions(self):
        items = [":File"]
        for i in range(4):
            items.append(Kit.Command(path=f"file.{i}", display=f"file {i}", func=(lambda x=i: (lambda: print(f"file {x}")))()))
        return items


class PathMenu(Kit.MenuBase):
    prefix = "path"
    def create_definitions(self):
        items = [":Path", "-"]
        for i in range(4):
            items.append(Kit.Command(path=f"path.{i}", display=f"path {i}", func=(lambda x=i: (lambda: print(f"path {x}")))()))
        i = 3
        items.append(Kit.Command(path=f"Temp/path.Test{i}", display=f"Temp {i}", func=(lambda x=i: (lambda: print(f"path {x}")))()))
        return items


class CmdMenu(Kit.MenuBase):
    prefix = "commands"
    
    def _cycle_sort_order(self):
        Command.cycle_action_group("sort_order")
    
    def _print_current_sort_order(self):
        current = Command.get_action_group_current("sort_order")
        if current:
            print(f"Current sort order: {current}")
        else:
            print("No sort order selected")

    def _print_is_demo_pane(self, ctx=None):
        w = ctx.get("widget") if ctx is not None and hasattr(ctx, "get") else None
        try:
            from .demo_app import DemoPane
            print(isinstance(w, DemoPane))
        except Exception as e:
            show_warning(None, "isDemoPane check failed", exc=e)
            print(False)

    def _toggle_key_scope_mode(self, ctx=None):
        cur = Settings.key_scope_mode()
        nxt = "focus" if cur == "cursor" else "cursor"
        Settings.set_key_scope_mode(nxt)
        print(f"Key scope mode: {nxt}")
    
    def create_definitions(self):
        return [
            ":Commands",
            Kit.Command(path="hello", display="Hello", func=lambda ctx: print(f"hello from {getattr(ctx, 'scope', '')}")),
            Kit.Command(path="time", display="Show Time", func=lambda: print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
            Kit.Command(path="test", display="print test", params=[Kit.Param(name="test", value="", description="test")], func=lambda test="": print(f"test: {test}")),
            Kit.Command(path="Debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug() if ctx is not None and hasattr(ctx, "print_debug") else print("ctx=None"))),
            Kit.Command(path="Debug/isDemoPane", display="Is DemoPane?", func=self._print_is_demo_pane),
            "-",
            ":Options",
            Kit.Command(path="Options/echo", display="Echo", params=[Kit.Param(name="text", value="echo"), Kit.Param(name="repeat", value=1, min_value=1, max_value=8)], has_options=True, func=lambda text="echo", repeat=1: print(text * repeat)),
            Kit.Command(path="Options/count", display="Count", params=[Kit.Param(name="value", value=1, description="Value"), Kit.Param(name="step", value=1, min_value=1, max_value=10)], has_options=True, func=lambda value=1, step=1: print("count", " ".join(str(i) for i in range(value, value + step)))),
            Kit.Command(path="Options/mode", display="Mode", params=[Kit.Param(name="mode", value=["A", "B", "C"], description="Mode")], has_options=True, func=lambda mode="A": print(f"mode {mode}")),
            "-",
            ":Toggle",
            Kit.Command(path="Toggle/toggleVerbose", display="Verbose Mode", checkable=True, default_checked=False, func=lambda ctx: print("verbose on" if ctx.get('checked', False) else "verbose off")),
            Kit.Command(path="Toggle/toggleKeyScopeMode", display="Toggle Key Scope (Focus/Cursor)", func=self._toggle_key_scope_mode),
            "-",
            ":Sort Order",
            Kit.Command(path="Sort/sortByName", display="Name", checkable=True, default_checked=True, action_group="sort_order", func=lambda ctx: print("Sort by Name" if ctx.get('checked', False) else "")),
            Kit.Command(path="Sort/sortByDate", display="Date", checkable=True, default_checked=False, action_group="sort_order", func=lambda ctx: print("Sort by Date" if ctx.get('checked', False) else "")),
            Kit.Command(path="Sort/sortBySize", display="Size", checkable=True, default_checked=False, action_group="sort_order", func=lambda ctx: print("Sort by Size" if ctx.get('checked', False) else "")),
            "Sort/-",
            Kit.Command(path="Sort/cycleSortOrder", display="Cycle Sort Order", func=self._cycle_sort_order),
            Kit.Command(path="Sort/printCurrentSort", display="Show Current Sort Order", func=self._print_current_sort_order),
        ]

class ContextMenu(Kit.MenuBase):
    prefix = "context"

    def _show_context_menu_here(self, ctx=None):
        Menu.exec_menu([":Menu", "-", "commands/:Test", "commands/-", "commands", "-", "file", "path", "Temp", "path.1", "Options", "echo"], ctx=ctx)
    
    def _show_all_menu(self, ctx=None):
        Menu.exec_all_roots(ctx=ctx)

    def create_definitions(self):
        return [
            ":ContextMenu",
            Kit.Command(path="showContextMenuHere", display="Show Context Menu Here", func=self._show_context_menu_here),
            Kit.Command(path="showAllMenu", display="Show All Menu Here", func=self._show_all_menu),
        ]


class MenuMenu(Kit.MenuBase):
    prefix = "menu"

    def __get_parent(self, ctx):
        return ctx.get("widget") if ctx is not None and hasattr(ctx, "get") else None

    def _open_mouse_binding_editor(self, ctx=None):
        UI.open_mouse_binding_editor(parent=self.__get_parent(ctx))

    def _open_shortcut_binding_editor(self, ctx=None):
        UI.open_shortcut_binding_editor(parent=self.__get_parent(ctx))

    def create_definitions(self):
        return [
            ":Menu",
            Kit.Command(path="binding/bindings", display="Mouse Bindings...", func=self._open_mouse_binding_editor),
            Kit.Command(path="binding/shortcutBindings", display="Shortcut Bindings...", func=self._open_shortcut_binding_editor),
        ]


def get_menu_classes() -> list[type[Kit.MenuBase]]:
    return [FileMenu, PathMenu, CmdMenu, ContextMenu, MenuMenu]


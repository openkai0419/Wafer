from datetime import datetime

from source.core.actions.bridge import Command, ActionKit, Menu, Settings, UI
from source.utils.logs import AppLogger


def _cycle_sort_order(ctx=None):
    Command.cycle_action_group("sort_order")


def _print_current_sort_order(ctx=None):
    current = Command.get_action_group_current("sort_order")
    if current:
        print(f"Current sort order: {current}")
    else:
        print("No sort order selected")


def _print_is_demo_pane(ctx=None):
    w = ctx.get("widget") if ctx is not None and hasattr(ctx, "get") else None
    try:
        from .demo_app import DemoPane
        print(isinstance(w, DemoPane))
    except Exception as e:
        AppLogger.warning("isDemoPane check failed", exc=e)
        print(False)


def _toggle_key_scope_mode(ctx=None):
    cur = Settings.key_scope_mode()
    nxt = "focus" if cur == "cursor" else "cursor"
    Settings.set_key_scope_mode(nxt)
    print(f"Key scope mode: {nxt}")


def _show_context_menu_here(ctx=None):
    s = Menu.from_context(ctx)
    if s is None:
        return
    s.menu([":Menu", "-", "commands/:Test", "commands/-", "commands", "-", "file", "path", "Temp", "path.1", "Options", "echo"]).exec()


def _show_all_menu(ctx=None):
    Menu.exec_all_roots(ctx)


def _get_ctx_parent(ctx):
    return ctx.get("widget") if ctx is not None and hasattr(ctx, "get") else None


def _open_mouse_binding_editor(ctx=None):
    UI.open_mouse_binding_editor(parent=_get_ctx_parent(ctx))


def _open_shortcut_binding_editor(ctx=None):
    UI.open_shortcut_binding_editor(parent=_get_ctx_parent(ctx))


class FileMenu(ActionKit.MenuBase):
    prefix = "file"
    commands = [":File"] + [
        ActionKit.Command(path=f"file.{i}", display=f"file {i}", func=(lambda x=i: (lambda: print(f"file {x}")))())
        for i in range(4)
    ]


class PathMenu(ActionKit.MenuBase):
    prefix = "path"
    commands = [":Path", "-"] + [
        ActionKit.Command(path=f"path.{i}", display=f"path {i}", func=(lambda x=i: (lambda: print(f"path {x}")))())
        for i in range(4)
    ] + [
        ActionKit.Command(path="Temp/path.Test3", display="Temp 3", func=(lambda: print("path 3")))
    ]


class CmdMenu(ActionKit.MenuBase):
    prefix = "commands"
    commands = [
        ":Commands",
        ActionKit.Command(path="hello", display="Hello", func=lambda ctx: print(f"hello from {getattr(ctx, 'scope', '')}")),
        ActionKit.Command(path="time", display="Show Time", func=lambda: print(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))),
        ActionKit.Command(path="test", display="print test", params=[ActionKit.Param(name="test", value="", description="test")], func=lambda test="": print(f"test: {test}")),
        ActionKit.Command(path="Debug/printCtx", display="Print Ctx", func=lambda ctx: (ctx.print_debug() if ctx is not None and hasattr(ctx, "print_debug") else print("ctx=None"))),
        ActionKit.Command(path="Debug/isDemoPane", display="Is DemoPane?", func=_print_is_demo_pane),
        "-",
        ":Options",
        ActionKit.Command(path="Options/echo", display="Echo", params=[ActionKit.Param(name="text", value="echo"), ActionKit.Param(name="repeat", value=1, min_value=1, max_value=8)], func=lambda text="echo", repeat=1: print(text * repeat)),
        ActionKit.Command(path="Options/count", display="Count", params=[ActionKit.Param(name="value", value=1, description="Value"), ActionKit.Param(name="step", value=1, min_value=1, max_value=10)], func=lambda value=1, step=1: print("count", " ".join(str(i) for i in range(value, value + step)))),
        ActionKit.Command(path="Options/mode", display="Mode", params=[ActionKit.Param(name="mode", value=["A", "B", "C"], description="Mode")], func=lambda mode="A": print(f"mode {mode}")),
        "-",
        ":Toggle",
        ActionKit.Command(path="Toggle/toggleVerbose", display="Verbose Mode", checkable=True, default_checked=False, func=lambda ctx: print("verbose on" if ctx and ctx.get("checked", False) else "verbose off")),
        ActionKit.Command(path="Toggle/toggleKeyScopeMode", display="Toggle Key Scope (Focus/Cursor)", func=_toggle_key_scope_mode),
        "-",
        ":Sort Order",
        ActionKit.Command(path="Sort/sortByName", display="Name", checkable=True, default_checked=True, action_group="sort_order", func=lambda ctx: print("Sort by Name" if ctx and ctx.get("checked", False) else "")),
        ActionKit.Command(path="Sort/sortByDate", display="Date", checkable=True, default_checked=False, action_group="sort_order", func=lambda ctx: print("Sort by Date" if ctx and ctx.get("checked", False) else "")),
        ActionKit.Command(path="Sort/sortBySize", display="Size", checkable=True, default_checked=False, action_group="sort_order", func=lambda ctx: print("Sort by Size" if ctx and ctx.get("checked", False) else "")),
        "Sort/-",
        ActionKit.Command(path="Sort/cycleSortOrder", display="Cycle Sort Order", func=_cycle_sort_order),
        ActionKit.Command(path="Sort/printCurrentSort", display="Show Current Sort Order", func=_print_current_sort_order),
    ]

class ContextMenu(ActionKit.MenuBase):
    prefix = "context"
    commands = [
        ":ContextMenu",
        ActionKit.Command(path="showContextMenuHere", display="Show Context Menu Here", func=_show_context_menu_here),
        ActionKit.Command(path="showAllMenu", display="Show All Menu Here", func=_show_all_menu),
    ]


class AppMenuRegistrar(ActionKit.MenuBase):
    prefix = "menu"
    commands = [
        ":Menu",
        ActionKit.Command(path="binding/bindings", display="Mouse Bindings...", func=_open_mouse_binding_editor),
        ActionKit.Command(path="binding/shortcutBindings", display="Shortcut Bindings...", func=_open_shortcut_binding_editor),
    ]


def get_menu_classes() -> list[type[ActionKit.MenuBase]]:
    return [FileMenu, PathMenu, CmdMenu, ContextMenu, AppMenuRegistrar]


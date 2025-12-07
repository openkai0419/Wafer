from PySide6 import QtCore, QtGui, QtWidgets
from .command.core import CommandMeta, CommandParam, CommandRegistry
from .command.menu import RegistryBackedMenu
from datetime import datetime
from .command.ui import MenuBuilder
from .binding.common import WidgetRef
from .binding.mouse.editors import MouseBindingEditor
from .binding.key.editors import ShortcutBindingEditor


class FileMenu(RegistryBackedMenu):
    path_prefix = "file"
    def create_definitions(self):
        items = [":File"]
        for i in range(4):
            items.append({
                "path": f"file.{i}",
                "meta": CommandMeta(display=f"file {i}", func=(lambda x=i: (lambda: print(f"file {x}")))()),
            })
        return items


class PathMenu(RegistryBackedMenu):
    path_prefix = "path"
    def create_definitions(self):
        items = [":Path", "-"]
        for i in range(4):
            items.append({
                "path": f"path.{i}",
                "meta": CommandMeta(display=f"path {i}", func=(lambda x=i: (lambda: print(f"path {x}")))()),
            })
        i = 3
        items.append({
            "path": f"Temp/path.Test{i}",
            "meta": CommandMeta(display=f"Temp {i}", func=(lambda x=i: (lambda: print(f"path {x}")))()),
        })
        return items


class CmdMenu(RegistryBackedMenu):
    path_prefix = "commands"
    
    def _cycle_sort_order(self):
        from .command.ui import CommandMenuBuilder
        builder = CommandMenuBuilder()
        result = builder.cycle_action_group("sort_order")
    
    def _print_current_sort_order(self):
        from .command.ui import CommandMenuBuilder
        builder = CommandMenuBuilder()
        current = builder.get_action_group_current("sort_order")
        if current:
            print(f"Current sort order: {current}")
        else:
            print("No sort order selected")
    
    def create_definitions(self):
        return [
            ":Commands",
            {"path": "hello", "meta": CommandMeta(display="Hello", params=[CommandParam(name="scope", type=str, default="", description="scope")], func=lambda scope="": print(f"hello from {scope}"))},
            {"path": "time", "meta": CommandMeta(display="Show Time", func=lambda: print(datetime.now().strftime("%Y-%m-%d %H:%M:%S")))},
            {"path": "test", "meta": CommandMeta(display="print test", params=[CommandParam(name="test", type=str, default="", description="test")], func=lambda test: print(f"test: {test}"))},
            "-",
            ":Options",
            {"path": "Options/echo", "meta": CommandMeta(display="Echo", params=[CommandParam(name="text", type=str, default="echo"), CommandParam(name="repeat", type=int, default=1, min_value=1, max_value=8)], has_options=True, func=lambda text="echo", repeat=1: print(text * repeat))},
            {"path": "Options/count", "meta": CommandMeta(display="Count", params=[CommandParam(name="value", type=int, default=1, description="Value"), CommandParam(name="step", type=int, default=1, min_value=1, max_value=10)], has_options=True, func=lambda value=1, step=1: print("count", " ".join(str(i) for i in range(value, value + step))))},
            {"path": "Options/mode", "meta": CommandMeta(display="Mode", params=[CommandParam(name="mode", type=str, default="A", choices=["A","B","C"], description="Mode")], has_options=True, func=lambda mode="A": print(f"mode {mode}"))},
            "-",
            ":Toggle",
            {"path": "Toggle/toggleVerbose", "meta": CommandMeta(display="Verbose Mode", checkable=True, default_checked=False, params=[CommandParam(name="checked", type=bool, default=False)], func=lambda checked=False: print("verbose on" if checked else "verbose off"))},
            "-",
            ":Sort Order",
            {"path": "Sort/sortByName", "meta": CommandMeta(display="Name", checkable=True, default_checked=True, action_group="sort_order", params=[CommandParam(name="checked", type=bool, default=True)], func=lambda checked=False: print("Sort by Name" if checked else ""))},
            {"path": "Sort/sortByDate", "meta": CommandMeta(display="Date", checkable=True, default_checked=False, action_group="sort_order", params=[CommandParam(name="checked", type=bool, default=False)], func=lambda checked=False: print("Sort by Date" if checked else ""))},
            {"path": "Sort/sortBySize", "meta": CommandMeta(display="Size", checkable=True, default_checked=False, action_group="sort_order", params=[CommandParam(name="checked", type=bool, default=False)], func=lambda checked=False: print("Sort by Size" if checked else ""))},
            {"path": "Sort/-"},
            {"path": "Sort/cycleSortOrder", "meta": CommandMeta(display="Cycle Sort Order", hotkey="Ctrl+Shift+S", func=self._cycle_sort_order)},
            {"path": "Sort/printCurrentSort", "meta": CommandMeta(display="Show Current Sort Order", func=self._print_current_sort_order)},
        ]

class ContextMenu(RegistryBackedMenu):
    path_prefix = "context"

    def _prepare_context_menu(self):
        from .command.core import COMMAND_MENU_MARKER
        active_popup = QtWidgets.QApplication.activePopupWidget()
        if active_popup and active_popup.property(COMMAND_MENU_MARKER):
            active_popup.close()
        pos = QtGui.QCursor.pos()
        w = QtWidgets.QApplication.widgetAt(pos)
        if w is None:
            return None, None, None
        target = w
        while target and not hasattr(target, "binding_scope"):
            target = target.parentWidget()
        if not target:
            return None, None, None
        provider = target.provider if hasattr(target, "provider") and callable(getattr(target, "provider")) else None
        return target, provider, pos

    def _show_context_menu_here(self):
        target, provider, pos = self._prepare_context_menu()
        if not target:
            return
        b = MenuBuilder(target, context_provider=provider)
        b.build([":Menu", "-", "commands/:Test", "commands/-", "commands", "-", "file", "path", "Temp", "path.1", "Options"]) 
        m = b.menu
        m.exec(pos)
    
    def _show_all_menu(self):
        target, provider, pos = self._prepare_context_menu()
        if not target:
            return
        m = MenuBuilder(target, context_provider=provider).build_all_roots()
        m.exec(pos)

    def create_definitions(self):
        return [
            ":ContextMenu",
            {"path": "showContextMenuHere", "meta": CommandMeta(display="Show Context Menu Here", func=self._show_context_menu_here)},
            {"path": "showAllMenu", "meta": CommandMeta(display="Show All Menu Here", func=self._show_all_menu)},
        ]

class MenuMenu(RegistryBackedMenu):
    path_prefix = "menu"
    
    def _collect_widgets(self):
        out = []
        for tl in QtWidgets.QApplication.topLevelWidgets():
            for w in tl.findChildren(QtWidgets.QWidget):
                if hasattr(w, "set_mouse_bindings"):
                    name = getattr(w, "name", "") or None
                    if name:
                        out.append(WidgetRef(name, w))
        return out
    
    def _open_mouse_binding_editor(self):
        ws = self._collect_widgets()
        if not ws:
            return
        dlg = MouseBindingEditor(ws)
        dlg.exec()

    def _open_shortcut_binding_editor(self):
        ws = self._collect_widgets()
        if not ws:
            return
        cmds = list(CommandRegistry().get_all_commands().keys())
        dlg = ShortcutBindingEditor(ws, cmds)
        dlg.exec()

    def create_definitions(self):
        return [
            ":Menu",
            {"path": "binding/bindings", "meta": CommandMeta(display="Mouse Bindings...", func=self._open_mouse_binding_editor)},
            {"path": "binding/shortcutBindings", "meta": CommandMeta(display="Shortcut Bindings...", func=self._open_shortcut_binding_editor)},
        ]
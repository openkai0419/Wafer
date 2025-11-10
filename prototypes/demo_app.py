from typing import Dict, List, Tuple
import json
from PySide6 import QtCore, QtGui, QtWidgets
from .command.core import CommandRegistry
from .command.utils import to_payload_json, is_json_text, show_error
from .mouseeventmanager import MouseEventManager, MouseEventDispatcher, MouseActionKey, ClickType, MouseButton
from .shortcutmanager import ShortcutManager
from .menu_demo import FileMenu, PathMenu, CmdMenu, MenuMenu
from .command.ui import MenuBuilder
from .binding_editors import WidgetRef, MouseBindingEditor, ShortcutBindingEditor
from .binding_store import MouseBindingStore


class DemoPane(QtWidgets.QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(240, 160)
        
        self._registry = CommandRegistry()
        self._mouse_manager = MouseEventManager()
        self._mouse_dispatcher = MouseEventDispatcher(self, self._mouse_manager)
        self._mouse_bindings: Dict[MouseActionKey, str] = {}
        self._store = MouseBindingStore()
        self._shortcut_manager = ShortcutManager()
        self._mouse_manager.set_resolver(self._resolve_fallback)
        self._header = QtWidgets.QLabel(name, self)
        self._header.setAlignment(QtCore.Qt.AlignCenter)
        l = QtWidgets.QVBoxLayout(self)
        l.addWidget(self._header, 1)

    def set_mouse_bindings(self, bindings: Dict[MouseActionKey, object]):
        self._mouse_bindings = {}
        self._mouse_manager.clear()
        for k, cmd in bindings.items():
            if isinstance(cmd, str) and is_json_text(cmd):
                s = cmd.strip()
            elif isinstance(cmd, dict) and "id" in cmd:
                s = to_payload_json(cmd)
            else:
                s = str(cmd)
            self._mouse_bindings[k] = s
            self._mouse_manager.bind(k, lambda e=None, c=s: self._exec(c))
        self._mouse_manager.set_resolver(self._resolve_fallback)

    def get_mouse_bindings(self) -> Dict[MouseActionKey, str]:
        return dict(self._mouse_bindings)

    def _resolve_fallback(self, key: MouseActionKey, event=None):
        cmd = self._store.resolve(self.name, key)
        if not cmd:
            return
        if isinstance(cmd, str) and is_json_text(cmd):
            self._exec(cmd)
            return
        if isinstance(cmd, dict) and "id" in cmd:
            try:
                self._exec(to_payload_json(cmd))
            except Exception:
                show_error(self, "Failed to resolve command")
            return
        if isinstance(cmd, str):
            self._exec(cmd)

    def set_shortcut_bindings(self, bindings: Dict[str, str]):
        self._shortcut_manager.set_bindings(self, bindings)

    def get_shortcut_bindings(self) -> Dict[str, str]:
        return self._shortcut_manager.get_bindings(self)

    def _exec(self, cmd):
        try:
            if not cmd:
                return
            if isinstance(cmd, str) and is_json_text(cmd):
                try:
                    d = json.loads(cmd)
                except Exception:
                    d = None
                if isinstance(d, dict) and "id" in d and isinstance(d.get("args"), dict) and not d.get("args"):
                    from .command.state import CommandOptionStore
                    try:
                        stored = CommandOptionStore().get(d.get("id"))
                        self._registry.execute_payload(stored, {"widget": self.name})
                        return
                    except Exception:
                        pass
                self._registry.execute_payload(cmd, {"widget": self.name})
            elif isinstance(cmd, dict) and "id" in cmd:
                self._registry.execute_payload(cmd, {"widget": self.name})
            elif isinstance(cmd, str):
                from .command.state import CommandOptionStore
                try:
                    payload = CommandOptionStore().get(cmd)
                except Exception:
                    payload = {"id": cmd, "args": {}}
                self._registry.execute_payload(payload, {"widget": self.name})
        except Exception as e:
            show_error(self, str(e))
            raise




class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Prototype Command Test")
        cw = QtWidgets.QWidget(self)
        l = QtWidgets.QHBoxLayout(cw)
        self.pane1 = DemoPane("Widget A", cw)
        self.pane2 = DemoPane("Widget B", cw)
        l.addWidget(self.pane1, 1)
        l.addWidget(self.pane2, 1)
        self.setCentralWidget(cw)
        CmdMenu()
        FileMenu()
        PathMenu()
        MenuMenu()
        self._setup_defaults()
        self._setup_menu()

    def _setup_defaults(self):
        from .binding_defaults import default_mouse_bindings
        defs = default_mouse_bindings()
        applied1 = {}
        applied2 = {}
        try:
            from .binding_store import MouseBindingStore
            from pathlib import Path
            path = str(Path(__file__).resolve().parent / "mouse_bindings.json")
            store = MouseBindingStore()
            loaded = store.load_from_file(path)
            if not loaded:
                initial: Dict[MouseActionKey, Dict[str, object]] = {}
                for k, v in defs.items():
                    initial[k] = {"*": v}
                store.set_all(initial)
            data = store.get_all()
            for key, scopes in data.items():
                cmd1 = scopes.get("Widget A") or scopes.get("*")
                cmd2 = scopes.get("Widget B") or scopes.get("*")
                if cmd1:
                    applied1[key] = cmd1
                if cmd2:
                    applied2[key] = cmd2
        except Exception:
            pass
        self.pane1.set_mouse_bindings(applied1)
        self.pane2.set_mouse_bindings(applied2)
        self.pane1.set_shortcut_bindings({})
        self.pane2.set_shortcut_bindings({})

    def _setup_menu(self):
        mb = self.menuBar()
        m = mb.addMenu("Edit")
        act_mouse = QtGui.QAction("Mouse Bindings...", self)
        act_short = QtGui.QAction("Shortcut Bindings...", self)
        act_mouse.triggered.connect(self._edit_mouse)
        act_short.triggered.connect(self._edit_short)
        m.addAction(act_mouse)
        m.addAction(act_short)

    def _edit_mouse(self):
        widgets = [WidgetRef("Widget A", self.pane1), WidgetRef("Widget B", self.pane2)]
        dlg = MouseBindingEditor(widgets, self)
        dlg.exec()

    def _edit_short(self):
        widgets = [WidgetRef("Widget A", self.pane1), WidgetRef("Widget B", self.pane2)]
        cmds = list(CommandRegistry().get_all_commands().keys())
        dlg = ShortcutBindingEditor(widgets, cmds, self)
        dlg.exec()


def main():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    w = MainWindow()
    w.resize(640, 400)
    w.show()
    app.exec()


if __name__ == "__main__":
    main()

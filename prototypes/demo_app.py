from typing import Dict, List, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from .commandbase import CommandRegistry
from .mouseeventmanager import MouseEventManager, MouseEventDispatcher, MouseActionKey, ClickType, MouseButton
from .shortcutmanager import ShortcutManager
from .menu_demo import FileMenu, PathMenu, CmdMenu
from .commandbase import MenuBuilder
from .binding_editors import WidgetRef, MouseBindingEditor, ShortcutBindingEditor


class DemoPane(QtWidgets.QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(240, 160)
        self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        
        self._registry = CommandRegistry()
        self._mouse_manager = MouseEventManager()
        self._mouse_dispatcher = MouseEventDispatcher(self, self._mouse_manager)
        self._mouse_bindings: Dict[MouseActionKey, str] = {}
        self._shortcut_manager = ShortcutManager()
        self._header = QtWidgets.QLabel(name, self)
        self._header.setAlignment(QtCore.Qt.AlignCenter)
        l = QtWidgets.QVBoxLayout(self)
        l.addWidget(self._header, 1)

    def set_mouse_bindings(self, bindings: Dict[MouseActionKey, str]):
        self._mouse_bindings = dict(bindings)
        self._mouse_manager.clear()
        for k, cmd in self._mouse_bindings.items():
            self._mouse_manager.bind(k, lambda e=None, c=cmd: self._exec(c))

    def get_mouse_bindings(self) -> Dict[MouseActionKey, str]:
        return dict(self._mouse_bindings)

    def set_shortcut_bindings(self, bindings: Dict[str, str]):
        self._shortcut_manager.set_bindings(self, bindings)

    def get_shortcut_bindings(self) -> Dict[str, str]:
        return self._shortcut_manager.get_bindings(self)

    def contextMenuEvent(self, event: QtGui.QContextMenuEvent):
        if self.name == "Widget B":
            m = MenuBuilder(self).build_all_roots()
        else:
            b = MenuBuilder(self, context_provider=lambda: {"widget": self.name})
            b.build(["commands/:Commands", "commands/-","commands", "-", "file", "path", "Temp", "path.1", "Options" ])
            m = b.menu
        m.exec(event.globalPos())

    def _exec(self, cmd: str):
        try:
            if cmd:
                self._registry.execute(cmd, widget=self.name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))




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
        self._setup_defaults()
        self._setup_menu()

    def _setup_defaults(self):
        self.pane1.set_mouse_bindings({MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, ()): "time"})
        self.pane2.set_mouse_bindings({MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE, ()): "hello"})
        self.pane1.set_shortcut_bindings({"Ctrl+H": "hello"})
        self.pane2.set_shortcut_bindings({"Ctrl+T": "time"})

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
        cmds = list(CommandRegistry().get_all_commands().keys())
        dlg = MouseBindingEditor(widgets, cmds, self)
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

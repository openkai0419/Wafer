from typing import Dict, List, Tuple
from PySide6 import QtCore, QtGui, QtWidgets
from .commandbase import CommandMenuBuilder, CommandRegistry
from .mouseeventmanager import MouseEventManager, MouseEventDispatcher, MouseActionKey, ClickType, MouseButton
from .shortcutmanager import ShortcutManager
from .menu_demo import FileMenu, PathMenu, CmdMenu, AllMenu


class DemoPane(QtWidgets.QFrame):
    def __init__(self, name: str, parent=None):
        super().__init__(parent)
        self.name = name
        self.setFrameShape(QtWidgets.QFrame.StyledPanel)
        self.setMinimumSize(240, 160)
        self.setContextMenuPolicy(QtCore.Qt.DefaultContextMenu)
        self._menu_builder = CommandMenuBuilder()
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
            m = AllMenu().build_menu(self)
        else:
            m = CmdMenu(context_provider=lambda: {"widget": self.name}).build_menu(self)
            m.addSeparator()
            m.addMenu(FileMenu().build_submenu(self))
            m.addMenu(PathMenu().build_submenu(self))
        m.exec(event.globalPos())

    def _exec(self, cmd: str):
        try:
            if cmd:
                self._registry.execute(cmd, widget=self.name)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))


class WidgetRef:
    def __init__(self, name: str, widget: DemoPane):
        self.name = name
        self.widget = widget
    def __str__(self):
        return self.name


class MouseBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], commands: List[str], parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.commands = commands
        self.setWindowTitle("Mouse Bindings")
        self.resize(520, 380)
        self._setup()
        self._load()

    def _setup(self):
        l = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.sel_widget = QtWidgets.QComboBox(self)
        for w in self.widgets:
            self.sel_widget.addItem(w.name, w)
        self.sel_widget.currentIndexChanged.connect(self._load)
        row.addWidget(QtWidgets.QLabel("Widget:"))
        row.addWidget(self.sel_widget, 1)
        l.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Key", "Click", "Command"])
        self.table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.table, 1)
        form = QtWidgets.QHBoxLayout()
        self.box_button = QtWidgets.QComboBox(self)
        for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.NONE]:
            self.box_button.addItem(b.name, b)
        self.box_click = QtWidgets.QComboBox(self)
        for c in [ClickType.SINGLE, ClickType.DOUBLE, ClickType.WHEEL_UP, ClickType.WHEEL_DOWN]:
            self.box_click.addItem(c.name, c)
        self.box_cmd = QtWidgets.QComboBox(self)
        for c in self.commands:
            self.box_cmd.addItem(c, c)
        btn_add = QtWidgets.QPushButton("Add", self)
        btn_del = QtWidgets.QPushButton("Delete", self)
        btn_add.clicked.connect(self._add)
        btn_del.clicked.connect(self._del)
        form.addWidget(QtWidgets.QLabel("Button"))
        form.addWidget(self.box_button)
        form.addWidget(QtWidgets.QLabel("Type"))
        form.addWidget(self.box_click)
        form.addWidget(QtWidgets.QLabel("Command"))
        form.addWidget(self.box_cmd, 1)
        form.addWidget(btn_add)
        form.addWidget(btn_del)
        l.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def _load(self):
        wref = self.sel_widget.currentData()
        if not isinstance(wref, WidgetRef):
            return
        b = wref.widget.get_mouse_bindings()
        self.table.setRowCount(0)
        for k, v in b.items():
            self._append_row(k, v)

    def _append_row(self, key: MouseActionKey, cmd: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(key.button.name))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(key.click_type.name))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(cmd))

    def _add(self):
        b = self.box_button.currentData()
        c = self.box_click.currentData()
        cmd = self.box_cmd.currentData()
        mk = MouseActionKey(b, c, ())
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(b.name))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(c.name))
        self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(cmd))

    def _del(self):
        for idx in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(idx)

    def _apply(self):
        wref = self.sel_widget.currentData()
        if not isinstance(wref, WidgetRef):
            self.reject()
            return
        bindings: Dict[MouseActionKey, str] = {}
        for r in range(self.table.rowCount()):
            bname = self.table.item(r, 0).text().strip()
            cname = self.table.item(r, 1).text().strip()
            cmd = self.table.item(r, 2).text().strip()
            b = getattr(MouseButton, bname, MouseButton.NONE)
            c = getattr(ClickType, cname, ClickType.SINGLE)
            bindings[MouseActionKey(b, c, ())] = cmd
        wref.widget.set_mouse_bindings(bindings)
        self.accept()


class ShortcutBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], commands: List[str], parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.commands = commands
        self.setWindowTitle("Shortcut Bindings")
        self.resize(520, 380)
        self._setup()
        self._load()

    def _setup(self):
        l = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        self.sel_widget = QtWidgets.QComboBox(self)
        for w in self.widgets:
            self.sel_widget.addItem(w.name, w)
        self.sel_widget.currentIndexChanged.connect(self._load)
        row.addWidget(QtWidgets.QLabel("Widget:"))
        row.addWidget(self.sel_widget, 1)
        l.addLayout(row)
        self.table = QtWidgets.QTableWidget(0, 2, self)
        self.table.setHorizontalHeaderLabels(["Shortcut", "Command"])
        self.table.horizontalHeader().setStretchLastSection(True)
        l.addWidget(self.table, 1)
        form = QtWidgets.QHBoxLayout()
        self.edit_seq = QtWidgets.QKeySequenceEdit(self)
        self.box_cmd = QtWidgets.QComboBox(self)
        for c in self.commands:
            self.box_cmd.addItem(c, c)
        btn_add = QtWidgets.QPushButton("Add", self)
        btn_del = QtWidgets.QPushButton("Delete", self)
        btn_add.clicked.connect(self._add)
        btn_del.clicked.connect(self._del)
        form.addWidget(QtWidgets.QLabel("Shortcut"))
        form.addWidget(self.edit_seq)
        form.addWidget(QtWidgets.QLabel("Command"))
        form.addWidget(self.box_cmd, 1)
        form.addWidget(btn_add)
        form.addWidget(btn_del)
        l.addLayout(form)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def _load(self):
        wref = self.sel_widget.currentData()
        if not isinstance(wref, WidgetRef):
            return
        b = wref.widget.get_shortcut_bindings()
        self.table.setRowCount(0)
        for seq, cmd in b.items():
            self._append_row(seq, cmd)

    def _append_row(self, seq: str, cmd: str):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(seq))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(cmd))

    def _add(self):
        seq = self.edit_seq.keySequence().toString()
        cmd = self.box_cmd.currentData()
        if not seq or not cmd:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(seq))
        self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(cmd))
        self.edit_seq.clear()

    def _del(self):
        for idx in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(idx)

    def _apply(self):
        wref = self.sel_widget.currentData()
        if not isinstance(wref, WidgetRef):
            self.reject()
            return
        bindings: Dict[str, str] = {}
        for r in range(self.table.rowCount()):
            seq = self.table.item(r, 0).text().strip()
            cmd = self.table.item(r, 1).text().strip()
            if seq and cmd:
                bindings[seq] = cmd
        wref.widget.set_shortcut_bindings(bindings)
        self.accept()


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
        self._setup_defaults()
        self._setup_menu()

    def _setup_defaults(self):
        self.pane1.set_mouse_bindings({MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, ()): "cmd.time"})
        self.pane2.set_mouse_bindings({MouseActionKey(MouseButton.MIDDLE, ClickType.SINGLE, ()): "cmd.hello"})
        self.pane1.set_shortcut_bindings({"Ctrl+H": "cmd.hello"})
        self.pane2.set_shortcut_bindings({"Ctrl+T": "cmd.time"})

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

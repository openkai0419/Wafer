from typing import Dict, List
from PySide6 import QtCore, QtGui, QtWidgets
from .mouseeventmanager import MouseActionKey, ClickType, MouseButton

class WidgetRef:
    def __init__(self, name: str, widget):
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

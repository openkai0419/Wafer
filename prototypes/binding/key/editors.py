from typing import Dict, List, Any
import json
from PySide6 import QtCore, QtWidgets
from ...command.core import CommandRegistry
from ...command.ui import CommandOptionsDialog
from ...utils import to_payload_json, format_payload_display
from ..common import WidgetRef

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
        btn_opts = QtWidgets.QPushButton("Edit Options", self)
        btn_add.clicked.connect(self._add)
        btn_del.clicked.connect(self._del)
        btn_opts.clicked.connect(self._edit_selected_options)
        form.addWidget(QtWidgets.QLabel("Shortcut"))
        form.addWidget(self.edit_seq)
        form.addWidget(QtWidgets.QLabel("Command"))
        form.addWidget(self.box_cmd, 1)
        form.addWidget(btn_add)
        form.addWidget(btn_del)
        form.addWidget(btn_opts)
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
    def _append_row(self, seq: str, cmd: object):
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(seq))
        if isinstance(cmd, dict) and "id" in cmd:
            try:
                payload = to_payload_json(cmd)
            except Exception:
                payload = str(cmd)
            disp = self._display(payload)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(disp))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, payload)
        else:
            txt = str(cmd)
            try:
                payload = to_payload_json({"id": txt, "args": {}})
            except Exception:
                payload = txt
            disp = self._display(payload)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(disp))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, payload)
    def _add(self):
        seq = self.edit_seq.keySequence().toString()
        cmd = self.box_cmd.currentData()
        if not seq or not cmd:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(seq))
        if isinstance(cmd, dict) and "id" in cmd:
            try:
                payload = to_payload_json(cmd)
            except Exception:
                payload = str(cmd)
            disp = self._display(payload)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(disp))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, payload)
        else:
            try:
                payload = to_payload_json({"id": str(cmd), "args": {}})
            except Exception:
                payload = str(cmd)
            disp = self._display(payload)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(disp))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, payload)
        self.edit_seq.clear()
    def _edit_selected_options(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            return
        reg = CommandRegistry()
        for r in rows:
            raw = self.table.item(r, 1).text().strip()
            cmd = raw
            try:
                if raw.startswith("{") and raw.endswith("}"):
                    d = json.loads(raw)
                    if isinstance(d, dict) and "id" in d:
                        cmd = str(d.get("id"))
            except Exception:
                pass
            cls = reg.get_command(cmd)
            if not cls:
                continue
            meta = getattr(cls, "meta", None)
            if not meta or not getattr(meta, "has_options", False):
                continue
            dlg = CommandOptionsDialog(cls, self, binding_mode=True)
            if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.did_save():
                payload_dict = {"id": cmd, "args": dlg.get_values()}
                try:
                    payload = to_payload_json(payload_dict)
                except Exception:
                    payload = str(payload_dict)
                disp = self._display(payload)
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(disp))
                self.table.item(r, 1).setData(QtCore.Qt.UserRole, payload)
    def _del(self):
        for idx in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(idx)
    def _apply(self):
        wref = self.sel_widget.currentData()
        if not isinstance(wref, WidgetRef):
            self.reject()
            return
        bindings: Dict[str, object] = {}
        for r in range(self.table.rowCount()):
            seq = self.table.item(r, 0).text().strip()
            text = self.table.item(r, 1).text().strip()
            if seq and text:
                payload = self.table.item(r, 1).data(QtCore.Qt.UserRole)
                bindings[seq] = payload if payload else text
        wref.widget.set_shortcut_bindings(bindings)
        self.accept()
    def _display(self, value: Any) -> str:
        return format_payload_display(value)

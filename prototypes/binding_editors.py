from typing import Dict, List, Tuple, Any
import os
from pathlib import Path
import json
from PySide6 import QtCore, QtGui, QtWidgets
from .mouseeventmanager import MouseActionKey, ClickType, MouseButton
from .command.ui import MenuBuilder, CommandOptionsDialog
from .command.core import CommandRegistry
from .binding_store import MouseBindingStore
from .command.utils import to_payload_json, is_json_text, show_error

class WidgetRef:
    def __init__(self, name: str, widget):
        self.name = name
        self.widget = widget
    def __str__(self):
        return self.name

class MouseBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.setWindowTitle("Mouse Bindings")
        self.resize(980, 640)
        self._store = MouseBindingStore()
        self._draft: Dict[MouseActionKey, Dict[str, str]] = {}
        self._setup()
        self._load_actions()
        self._reload_sections()

    def _setup(self):
        l = QtWidgets.QVBoxLayout(self)
        body = QtWidgets.QHBoxLayout()
        self.list_actions = QtWidgets.QListWidget(self)
        self.list_actions.currentRowChanged.connect(lambda _: self._reload_sections())
        body.addWidget(self.list_actions, 0)
        self.scroll = QtWidgets.QScrollArea(self)
        self.scroll.setWidgetResizable(True)
        self.panel = QtWidgets.QWidget(self.scroll)
        self.scroll.setWidget(self.panel)
        self.panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self.sections_container = QtWidgets.QWidget(self.panel)
        self.sections_layout = QtWidgets.QVBoxLayout(self.sections_container)
        self.sections_layout.setContentsMargins(0,0,0,0)
        self.sections_layout.setSpacing(8)
        self.panel_layout.addWidget(self.sections_container, 1)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch(1)
        self.btn_reset_action = QtWidgets.QPushButton("初期化", self.panel)
        self.btn_reset_action.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_reset_action.clicked.connect(self._reset_current_action)
        footer.addWidget(self.btn_reset_action, 0)
        self.panel_layout.addLayout(footer)
        self.sections: List['MouthSection'] = []
        body.addWidget(self.scroll, 1)
        l.addLayout(body, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def _actions(self) -> List[Tuple[str, MouseButton, ClickType]]:
        r: List[Tuple[str, MouseButton, ClickType]] = []
        for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
            r.append((f"{b.name} SINGLE", b, ClickType.SINGLE))
            r.append((f"{b.name} DOUBLE", b, ClickType.DOUBLE))
        r.append(("WHEEL UP", MouseButton.NONE, ClickType.WHEEL_UP))
        r.append(("WHEEL DOWN", MouseButton.NONE, ClickType.WHEEL_DOWN))
        return r

    def _held_buttons_for_sections(self) -> List[MouseButton]:
        return [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]

    def _load_actions(self):
        self.list_actions.clear()
        for label, _, _ in self._actions():
            self.list_actions.addItem(label)
        if self.list_actions.count() > 0:
            self.list_actions.setCurrentRow(0)

    def _current_action(self) -> Tuple[MouseButton, ClickType]:
        idx = self.list_actions.currentRow()
        items = self._actions()
        if idx < 0 or idx >= len(items):
            return (MouseButton.LEFT, ClickType.SINGLE)
        _, b, c = items[idx]
        return (b, c)

    def _reload_sections(self, skip_save: bool = False):
        if not skip_save:
            self._save_current_sections_to_draft()
        self._clear_sections()
        self.sections.clear()
        b, c = self._current_action()
        data = self._merged_data()
        for hb in self._held_buttons_for_sections():
            s = MouthSection(self.panel, self.widgets, hb, self._store)
            s.set_action(b, c)
            s.load_from_data(data)
            self.sections_layout.addWidget(s)
            self.sections.append(s)
        self.sections_layout.addStretch(1)

    def _save_current_sections_to_draft(self):
        if not hasattr(self, 'sections') or not self.sections:
            return
        for s in self.sections:
            try:
                key = s._current_key()
            except Exception:
                continue
            if key in self._draft:
                self._draft.pop(key, None)
            d = s.collect_entries()
            if key in d:
                scopes = d[key]
                if scopes:
                    self._draft[key] = dict(scopes)

    def _merged_data(self) -> Dict[MouseActionKey, Dict[str, object]]:
        base = self._store.get_all()
        for k, v in self._draft.items():
            if v:
                base[k] = dict(v)
            elif k in base:
                base.pop(k, None)
        return base

    def _clear_sections(self):
        lay = self.sections_layout
        while True:
            item = lay.takeAt(0)
            if not item:
                break
            w = item.widget()
            if w is not None:
                try:
                    w.hide()
                    w.setParent(None)
                except Exception:
                    pass
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._clear_layout_recursive(sub)
        try:
            self.panel.update()
            self.scroll.viewport().update()
            QtWidgets.QApplication.processEvents()
        except Exception:
            pass

    def _clear_layout_recursive(self, layout: QtWidgets.QLayout):
        while True:
            it = layout.takeAt(0)
            if not it:
                break
            w = it.widget()
            if w is not None:
                try:
                    w.hide()
                    w.setParent(None)
                except Exception:
                    pass
                w.deleteLater()
            sub = it.layout()
            if sub is not None:
                self._clear_layout_recursive(sub)

    def _scope_targets(self) -> List[str]:
        return ["*"] + [w.name for w in self.widgets]

    def _apply(self):
        self._save_current_sections_to_draft()
        data = self._store.get_all()
        for key, scopes in self._draft.items():
            if scopes:
                data[key] = dict(scopes)
            else:
                data.pop(key, None)
        self._store.set_all(data)
        for wref in self.widgets:
            if hasattr(wref.widget, "set_mouse_bindings"):
                bindings = {}
                for key, scopes in data.items():
                    cmd_widget = scopes.get(wref.name) or scopes.get("*")
                    if cmd_widget:
                        bindings[key] = cmd_widget
                wref.widget.set_mouse_bindings(bindings)
        try:
            path = str(Path(__file__).resolve().parent / "mouse_bindings.json")
            self._store.save_to_file(path)
        except Exception:
            pass
        self.accept()

    def _reset_to_defaults(self):
        try:
            from .binding_defaults import default_mouse_bindings
            defs = default_mouse_bindings()
            nd: Dict[MouseActionKey, Dict[str, object]] = {}
            for k, v in defs.items():
                nd[k] = {"*": v}
            self._draft = nd
            self._reload_sections()
        except Exception:
            pass

    def _reset_current_action(self):
        try:
            b, c = self._current_action()
            from .binding_defaults import default_mouse_bindings
            defs = default_mouse_bindings()
            cur = self._store.get_all()
            aff_keys = set()
            for k in cur.keys():
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in defs.keys():
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in list(self._draft.keys()):
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in aff_keys:
                if k in defs:
                    self._draft[k] = {"*": defs[k]}
                else:
                    self._draft[k] = {}
            # 再描画時に既存セクションの古い値を上書きしないため save をスキップ
            self._reload_sections(skip_save=True)
        except Exception:
            pass


class MouthSection(QtWidgets.QGroupBox):
    def __init__(self, parent: QtWidgets.QWidget, widgets: List[WidgetRef], held_button: MouseButton, store: MouseBindingStore):
        super().__init__(parent)
        self.widgets = widgets
        self.held_button = held_button
        self.store = store
        self.button: MouseButton = MouseButton.LEFT
        self.click: ClickType = ClickType.SINGLE
        self.setTitle("")
        l = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QHBoxLayout()
        self.btn_global = QtWidgets.QPushButton(self._title(), self)
        self.btn_global.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_global.setStyleSheet("padding:4px 12px;")
        self.btn_global.clicked.connect(lambda: self._pick_cmd("*"))
        header.addWidget(self.btn_global, 0)
        self.btn_overrides = QtWidgets.QToolButton(self)
        self.btn_overrides.setText("項目別")
        self.btn_overrides.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.btn_overrides.setStyleSheet("padding:4px 4px;")
        self.ov_menu = QtWidgets.QMenu(self.btn_overrides)
        self.ov_menu.aboutToShow.connect(self._refresh_overrides_menu)
        self.btn_overrides.setMenu(self.ov_menu)
        header.addWidget(self.btn_overrides, 0)
        header.addStretch(1)
        l.addLayout(header)
        self.global_edit = QtWidgets.QLineEdit(self)
        self.global_edit.setReadOnly(True)
        l.addWidget(self.global_edit)
        self.overrides_container = QtWidgets.QWidget(self)
        self.overrides_layout = QtWidgets.QVBoxLayout(self.overrides_container)
        self.overrides_layout.setContentsMargins(4,4,4,4)
        self.overrides_layout.setSpacing(6)
        self.override_edits: Dict[str, QtWidgets.QLineEdit] = {}
        self._payloads: Dict[str, object] = {}
        self.list_order: List[str] = []
        l.addWidget(self.overrides_container)
        self.overrides_container.setVisible(False)

    def set_action(self, button: MouseButton, click: ClickType):
        self.button = button
        self.click = click
        t = self._title()
        self.setTitle("")
        if hasattr(self, 'btn_global'):
            self.btn_global.setText(t)

    def _title(self) -> str:
        if self.held_button == self.button:
            return "★ 単独での機能"
        return f"{self.held_button.name} 押しながら"

    def load_from_store(self, store: MouseBindingStore):
        self.global_edit.clear()
        for e in self.override_edits.values():
            e.clear()
        self._payloads.clear()
        data = store.get_all()
        found: Dict[str,str] = {}
        for key, scopes in data.items():
            if key.button != self.button or key.click_type != self.click:
                continue
            if tuple(key.held_buttons) != (self.held_button,) and not (self.held_button == self.button and not key.held_buttons):
                continue
            if "*" in scopes:
                v = scopes.get("*", "")
                if isinstance(v, dict) and "id" in v:
                    found["*"] = str(v.get("id"))
                    self._payloads["*"] = v
                else:
                    found["*"] = str(v or "")
            for scope, cmd in scopes.items():
                if scope != "*" and cmd:
                    if isinstance(cmd, dict) and "id" in cmd:
                        found[scope] = str(cmd.get("id"))
                        self._payloads[scope] = cmd
                    else:
                        found[scope] = str(cmd)
        self._rebuild_overrides_entries(found)
        g = found.get("*")
        if g:
            disp = self._display(self._payloads.get("*", g))
            self.global_edit.setText(disp)
        self.overrides_container.setVisible(any(s != "*" for s in found))
    def load_from_data(self, data: Dict[MouseActionKey, Dict[str,object]]):
        self.global_edit.clear()
        for e in self.override_edits.values():
            e.clear()
        self._payloads.clear()
        found: Dict[str,str] = {}
        for key, scopes in data.items():
            if key.button != self.button or key.click_type != self.click:
                continue
            if tuple(key.held_buttons) != (self.held_button,) and not (self.held_button == self.button and not key.held_buttons):
                continue
            if "*" in scopes:
                v = scopes.get("*", "")
                if isinstance(v, dict) and "id" in v:
                    found["*"] = str(v.get("id"))
                    self._payloads["*"] = v
                else:
                    found["*"] = str(v or "")
            for scope, cmd in scopes.items():
                if scope != "*" and cmd:
                    if isinstance(cmd, dict) and "id" in cmd:
                        found[scope] = str(cmd.get("id"))
                        self._payloads[scope] = cmd
                    else:
                        found[scope] = str(cmd)
        self._rebuild_overrides_entries(found)
        g = found.get("*")
        if g:
            disp = self._display(self._payloads.get("*", g))
            self.global_edit.setText(disp)
        self.overrides_container.setVisible(any(s != "*" for s in found))

    def _pick_cmd(self, scope: str):
        if scope == "*":
            btn = self.global_edit
        else:
            btn = self.override_edits.get(scope)
        if btn is None:
            return
        try:
            builder = MenuBuilder(self)
            def _prep(m: QtWidgets.QMenu, sc=scope):
                act_none = QtGui.QAction("なし(解除)", m)
                act_none.triggered.connect(lambda _, s=sc: self._on_select(s, None))
                first = m.actions()[0] if m.actions() else None
                if first:
                    m.insertAction(first, act_none)
                    m.insertSeparator(first)
                else:
                    m.addAction(act_none)
            builder.popup_all_roots(btn, selection_callback=lambda cid, sc=scope: self._on_select(sc, cid), context_provider=None, prepare=_prep, allow_options_with_selection=True)
        except Exception as e:
            show_error(self, str(e))

    def _on_select(self, scope: str, cid):
        if cid is None:
            if scope == "*":
                self.global_edit.setText("")
                self._clear_binding("*")
            else:
                self._remove_override(scope)
            if not self.override_edits:
                self.overrides_container.setVisible(False)
            self._refresh_overrides_menu()
            return
        dedicated = None
        try:
            if isinstance(cid, str) and cid.startswith("{") and cid.endswith("}"):
                dedicated = cid
        except Exception:
            dedicated = None
        if dedicated is None:
            try:
                dedicated = to_payload_json({"id": str(cid), "args": {}})
            except Exception:
                dedicated = str(cid)
        target_display = dedicated
        if scope == "*":
            self.global_edit.setText(self._display(target_display))
            if dedicated is not None:
                self._payloads["*"] = dedicated
            else:
                self._payloads.pop("*", None)
        else:
            if scope in self.override_edits:
                self.override_edits[scope].setText(self._display(target_display))
                if dedicated is not None:
                    self._payloads[scope] = dedicated
                else:
                    self._payloads.pop(scope, None)
        if scope != "*" and cid:
            self.overrides_container.setVisible(True)

    def collect_entries(self) -> Dict[MouseActionKey, Dict[str, object]]:
        key = self._current_key()
        scopes: Dict[str, object] = {}
        if "*" in self._payloads:
            scopes["*"] = self._to_saved(self._payloads["*"])
        else:
            gtxt = self.global_edit.text().strip()
            if gtxt:
                scopes["*"] = self._to_saved(gtxt)
        for scope, edit in self.override_edits.items():
            if scope in self._payloads:
                scopes[scope] = self._to_saved(self._payloads[scope])
            else:
                txt = edit.text().strip()
                if txt:
                    scopes[scope] = self._to_saved(txt)
        return {key: scopes} if scopes else {}

    def _refresh_overrides_menu(self):
        self.ov_menu.clear()
        remaining = [w.name for w in self.widgets if w.name not in self.override_edits]
        if not remaining:
            act = self.ov_menu.addAction("No more widgets")
            act.setEnabled(False)
            self.btn_overrides.setEnabled(False)
            return
        self.btn_overrides.setEnabled(True)
        for scope in remaining:
            act = self.ov_menu.addAction(scope)
            act.triggered.connect(lambda _, sc=scope: self._add_override(sc))

    def _rebuild_overrides_entries(self, found: Dict[str,str]):
        while True:
            it = self.overrides_layout.takeAt(0)
            if not it:
                break
            w = it.widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        self.override_edits.clear()
        ordered = sorted([s for s in found.keys() if s != "*"]) if found else []
        for scope in ordered:
            self._create_override_row(scope, found.get(scope, ""))
        self.overrides_layout.addStretch(1)
        self._refresh_overrides_menu()

    def _create_override_row(self, scope: str, value: str):
        row = QtWidgets.QWidget(self.overrides_container)
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0,0,0,0)
        rl.setSpacing(6)
        btn = QtWidgets.QPushButton(scope, row)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setStyleSheet("padding:2px 10px;")
        btn.clicked.connect(lambda _, sc=scope: self._pick_cmd(sc))
        edit = QtWidgets.QLineEdit(row)
        edit.setReadOnly(True)
        if value:
            edit.setText(self._display(value))
        rl.addWidget(btn,0)
        rl.addWidget(edit,1)
        self.override_edits[scope] = edit
        self.overrides_layout.insertWidget(self.overrides_layout.count(), row)

    def _add_override(self, scope: str):
        if scope in self.override_edits:
            return
        self._create_override_row(scope, "")
        self.overrides_container.setVisible(True)
        self._refresh_overrides_menu()

    def _remove_override(self, scope: str):
        edit = self.override_edits.pop(scope, None)
        if not edit:
            return
        row = edit.parent()
        try:
            idx = self.overrides_layout.indexOf(row)
            if idx >= 0:
                it = self.overrides_layout.takeAt(idx)
                w = it.widget()
                if w:
                    w.hide()
                    w.setParent(None)
                    w.deleteLater()
            else:
                row.hide()
                row.setParent(None)
                row.deleteLater()
        except Exception:
            row.setParent(None)
            row.deleteLater()
        if not self.override_edits:
            self.overrides_container.setVisible(False)
        self._clear_binding(scope)
        self._payloads.pop(scope, None)

    def _current_key(self) -> MouseActionKey:
        return MouseActionKey(self.button, self.click, () if self.held_button == self.button else (self.held_button,))

    def _clear_binding(self, scope: str):
        try:
            self.store.set_binding(self._current_key(), scope, None)
        except Exception:
            pass

    def _build_payload_with_options(self, cid: str):
        reg = CommandRegistry()
        cls = reg.get_command(cid)
        if not cls:
            try:
                return to_payload_json({"id": cid, "args": {}})
            except Exception:
                return {"id": cid, "args": {}}
        meta = getattr(cls, "meta", None)
        if not meta or not getattr(meta, "has_options", False):
            try:
                return to_payload_json({"id": cid, "args": {}})
            except Exception:
                return {"id": cid, "args": {}}
        dlg = CommandOptionsDialog(cls, self, binding_mode=True)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.did_save():
            try:
                return to_payload_json({"id": cid, "args": dlg.get_values()})
            except Exception:
                return {"id": cid, "args": dlg.get_values()}
        return to_payload_json({"id": cid, "args": {}})

    def _display(self, value: Any) -> str:
        try:
            return to_payload_json(value)
        except Exception:
            return str(value)

    def _to_saved(self, value: Any) -> Any:
        try:
            return to_payload_json(value)
        except Exception:
            return value

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
            s = self._display(cmd)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(s))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, s)
        else:
            txt = str(cmd)
            s = self._display(txt)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(s))

    def _add(self):
        seq = self.edit_seq.keySequence().toString()
        cmd = self.box_cmd.currentData()
        if not seq or not cmd:
            return
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(seq))
        if isinstance(cmd, dict) and "id" in cmd:
            s = self._display(cmd)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(s))
            self.table.item(r, 1).setData(QtCore.Qt.UserRole, s)
        else:
            try:
                s = to_payload_json({"id": str(cmd), "args": {}})
            except Exception:
                s = str(cmd)
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(s))
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
                payload = {"id": cmd, "args": dlg.get_values()}
                try:
                    s = to_payload_json(payload)
                except Exception:
                    s = str(payload)
                self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(s))
                self.table.item(r, 1).setData(QtCore.Qt.UserRole, s)

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

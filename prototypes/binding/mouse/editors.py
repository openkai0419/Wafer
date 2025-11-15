from typing import Dict, List, Tuple, Any
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from .mouseeventmanager import MouseActionKey, ClickType, MouseButton
from ...command.ui import MenuBuilder, CommandOptionsDialog
from ...command.core import CommandRegistry
from .store import MouseBindingStore
from ...utils import show_error, format_payload_display, CommandPayload
from ..common import WidgetRef

class MouseBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.setWindowTitle("Mouse Bindings")
        self.resize(640, 480)
        self._store = MouseBindingStore()
        self._draft: Dict[MouseActionKey, Dict[str, str]] = {}
        self._setup()
        self._load_actions()
        self._reload_sections()
    def _setup(self):
        l = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        left_container = QtWidgets.QWidget(self.splitter)
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(0,0,0,0)
        left_layout.setSpacing(4)
        label_actions = QtWidgets.QLabel("マウス操作:", left_container)
        self.list_actions = QtWidgets.QListWidget(left_container)
        self.list_actions.currentRowChanged.connect(lambda _: self._reload_sections())
        left_layout.addWidget(label_actions, 0)
        left_layout.addWidget(self.list_actions, 1)
        self.scroll = QtWidgets.QScrollArea(self.splitter)
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
        self.btn_reset_action = QtWidgets.QPushButton("初期設定に戻す", self.panel)
        self.btn_reset_action.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_reset_action.clicked.connect(self._reset_current_action)
        footer.addWidget(self.btn_reset_action, 0)
        self.panel_layout.addLayout(footer)
        self.sections: List['MouthSection'] = []
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(self.scroll)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([120, 420])
        self.splitter.setStretchFactor(0,0)
        self.splitter.setStretchFactor(1,1)
        l.addWidget(self.splitter, 1)
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
            path = str(Path(__file__).resolve().parent.parent.parent / "mouse_bindings.json")
            self._store.save_to_file(path)
        except Exception:
            pass
        self.accept()
    def _reset_to_defaults(self):
        try:
            from .defaults import default_mouse_bindings
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
            from .defaults import default_mouse_bindings
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
        self.btn_overrides.setText("カスタム")
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
        self._payloads: Dict[str, CommandPayload] = {}
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
    def load_from_data(self, data: Dict[MouseActionKey, Dict[str,CommandPayload]]):
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
                v = scopes.get("*", None)
                if not isinstance(v, CommandPayload):
                    raise TypeError("Mouse binding payload must be CommandPayload")
                found["*"] = v.id
                self._payloads["*"] = v
            for scope, cmd in scopes.items():
                if scope != "*" and cmd:
                    if not isinstance(cmd, CommandPayload):
                        raise TypeError("Mouse binding payload must be CommandPayload")
                    found[scope] = cmd.id
                    self._payloads[scope] = cmd
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
                self._payloads.pop("*", None)
            else:
                self._remove_override(scope)
            if not self.override_edits:
                self.overrides_container.setVisible(False)
            self._refresh_overrides_menu()
            return
        if not isinstance(cid, CommandPayload):
            raise TypeError("Selection must provide CommandPayload")
        dedicated = cid
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
    def collect_entries(self) -> Dict[MouseActionKey, Dict[str, CommandPayload]]:
        key = self._current_key()
        scopes: Dict[str, CommandPayload] = {}
        if "*" in self._payloads:
            scopes["*"] = self._to_saved(self._payloads["*"])
        for scope in list(self.override_edits.keys()):
            if scope in self._payloads:
                scopes[scope] = self._to_saved(self._payloads[scope])
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
    def _build_payload_with_options(self, cid: str) -> CommandPayload:
        reg = CommandRegistry()
        cls = reg.get_command(cid)
        if not cls:
            return CommandPayload(cid, {})
        meta = getattr(cls, "meta", None)
        if not meta or not getattr(meta, "has_options", False):
            return CommandPayload(cid, {})
        dlg = CommandOptionsDialog(cls, self, binding_mode=True)
        if dlg.exec() == QtWidgets.QDialog.Accepted and dlg.did_save():
            return CommandPayload(cid, dlg.get_values())
        return CommandPayload(cid, {})
    def _display(self, value: Any) -> str:
        return format_payload_display(value)
    def _to_saved(self, value: CommandPayload) -> CommandPayload:
        return value

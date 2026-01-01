from typing import Dict, List, Tuple, Any
from pathlib import Path
from dataclasses import dataclass
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.funcs import uipx
from .mouseeventmanager import MouseActionKey, ClickType, MouseButton, ModifierKey
from ...facade import Settings, UI
from .store import MouseBindingStore
from ...command.payload import format_payload_display
from ...command.payload import CommandPayload
from ..common import WidgetRef
from source.common.errors import show_warning


@dataclass(frozen=True)
class MouseQualifier:
    kind: str
    value: object | None

class MouseBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self.setWindowTitle("Mouse Bindings")
        self.resize(uipx(640), uipx(480))
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
        left_layout.setSpacing(uipx(4))
        label_actions = QtWidgets.QLabel("マウス操作:", left_container)
        self.list_actions = QtWidgets.QListWidget(left_container)
        self.list_actions.setAlternatingRowColors(True)
        self.list_actions.currentRowChanged.connect(lambda _: self._reload_sections())
        left_layout.addWidget(label_actions, 0)
        left_layout.addWidget(self.list_actions, 1)
        self.scroll = QtWidgets.QScrollArea(self.splitter)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.scroll.setStyleSheet("QScrollArea{border:none;} QScrollArea> QWidget{background:#000;}")
        self.panel = QtWidgets.QWidget(self.scroll)
        self.panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.scroll.setWidget(self.panel)
        self.panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self.sections_container = QtWidgets.QWidget(self.panel)
        self.sections_container.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.sections_layout = QtWidgets.QVBoxLayout(self.sections_container)
        self.sections_layout.setContentsMargins(0,0,0,0)
        self.sections_layout.setSpacing(uipx(8))
        self.panel_layout.addWidget(self.sections_container, 1)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch(1)
        self.btn_reset_action = QtWidgets.QPushButton("初期設定に戻す", self.panel)
        self.btn_reset_action.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_reset_action.clicked.connect(self._reset_current_action)
        footer.addWidget(self.btn_reset_action, 0)
        self.panel_layout.addLayout(footer)
        self.sections: List['MouseSection'] = []
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(self.scroll)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([uipx(120), uipx(420)])
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
        for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
            r.append((f"{b.name} DRAG", b, ClickType.DRAG_START))
        r.append(("WHEEL UP", MouseButton.NONE, ClickType.WHEEL_UP))
        r.append(("WHEEL DOWN", MouseButton.NONE, ClickType.WHEEL_DOWN))
        r.append(("DROP", MouseButton.NONE, ClickType.DROP))
        return r

    def _qualifiers_for_sections(self, button: MouseButton, click: ClickType) -> List[MouseQualifier]:
        qs: List[MouseQualifier] = [MouseQualifier("none", None)]
        mods = [ModifierKey.SHIFT, ModifierKey.CTRL, ModifierKey.ALT]
        if click == ClickType.DROP:
            for m in mods:
                qs.append(MouseQualifier("modifier", m))
            return qs
        if click in (ClickType.WHEEL_UP, ClickType.WHEEL_DOWN, ClickType.DROP):
            for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
                qs.append(MouseQualifier("mouse", b))
        else:
            for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
                if b != button:
                    qs.append(MouseQualifier("mouse", b))
        for m in mods:
            qs.append(MouseQualifier("modifier", m))
        return qs
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
        for q in self._qualifiers_for_sections(b, c):
            s = MouseSection(self.panel, self.widgets, q, self._store)
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
            except Exception as e:
                show_warning(self, "MouseBindingEditor _current_key failed", exc=e)
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
        err = None
        err_count = 0
        while True:
            item = lay.takeAt(0)
            if not item:
                break
            w = item.widget()
            if w is not None:
                try:
                    w.hide()
                    w.setParent(None)
                except Exception as e:
                    err = err or e
                    err_count += 1
                w.deleteLater()
            sub = item.layout()
            if sub is not None:
                self._clear_layout_recursive(sub)
        try:
            self.panel.update()
            self.scroll.viewport().update()
            QtWidgets.QApplication.processEvents()
        except Exception as e:
            err = err or e
            err_count += 1
        if err is not None:
            show_warning(self, f"MouseBindingEditor clear sections had {err_count} errors", exc=err)
    def _clear_layout_recursive(self, layout: QtWidgets.QLayout):
        err = None
        err_count = 0
        while True:
            it = layout.takeAt(0)
            if not it:
                break
            w = it.widget()
            if w is not None:
                try:
                    w.hide()
                    w.setParent(None)
                except Exception as e:
                    err = err or e
                    err_count += 1
                w.deleteLater()
            sub = it.layout()
            if sub is not None:
                self._clear_layout_recursive(sub)
        if err is not None:
            show_warning(self, f"MouseBindingEditor clear layout had {err_count} errors", exc=err)
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
            from ..manager import BindingManager
            self._store.save_to_file(BindingManager.instance().mouse_bindings_path())
        except Exception as e:
            show_warning(self, "MouseBindingEditor save_to_file failed", exc=e)
        self.accept()
    def _reset_to_defaults(self):
        try:
            specs = Settings.seed_mouse_specs()
            if specs is None:
                return
            self._draft = MouseBindingStore.normalize_specs(specs)
            self._reload_sections()
        except Exception as e:
            show_warning(self, "MouseBindingEditor reset_to_defaults failed", exc=e)
    def _reset_current_action(self):
        try:
            b, c = self._current_action()
            specs = Settings.seed_mouse_specs()
            if specs is None:
                return
            defs = MouseBindingStore.normalize_specs(specs)
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
                self._draft[k] = dict(defs[k]) if k in defs else {}
            self._reload_sections(skip_save=True)
        except Exception as e:
            show_warning(self, "MouseBindingEditor reset_current_action failed", exc=e)

class MouseSection(QtWidgets.QGroupBox):
    def __init__(self, parent: QtWidgets.QWidget, widgets: List[WidgetRef], qualifier: MouseQualifier, store: MouseBindingStore):
        super().__init__(parent)
        self.widgets = widgets
        self.qualifier = qualifier
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
        self.btn_overrides.setText("専用")
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
        self.overrides_layout.setContentsMargins(uipx(4),uipx(4),uipx(4),uipx(4))
        self.overrides_layout.setSpacing(uipx(6))
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
        if self.qualifier.kind == "none":
            return "★ 単独での機能"
        if self.qualifier.kind == "mouse":
            b = self.qualifier.value
            if isinstance(b, MouseButton):
                return f"{b.name} 押しながら"
            return "(invalid)"
        if self.qualifier.kind == "modifier":
            m = self.qualifier.value
            if m == ModifierKey.SHIFT:
                return "Shift 押しながら"
            if m == ModifierKey.CTRL:
                return "Ctrl 押しながら"
            if m == ModifierKey.ALT:
                return "Alt 押しながら"
            return "(invalid)"
        return "(invalid)"
    def load_from_data(self, data: Dict[MouseActionKey, Dict[str,CommandPayload]]):
        self.global_edit.clear()
        for e in self.override_edits.values():
            e.clear()
        self._payloads.clear()
        found: Dict[str,str] = {}
        expected_key = self._current_key()
        for key, scopes in data.items():
            if key != expected_key:
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
        btn = self.global_edit if scope == "*" else self.override_edits.get(scope)
        if btn is None:
            return
        
        if self._is_drag_type():
            self._show_category_menu(btn, scope, "drag")
        elif self._is_drop_type():
            self._show_category_menu(btn, scope, "drop")
        else:
            builder = UI.get_builder(self)
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
    
    def _is_drag_type(self) -> bool:
        return self.click == ClickType.DRAG_START
    
    def _is_drop_type(self) -> bool:
        return self.click == ClickType.DROP
    
    def _show_category_menu(self, btn, scope: str, category: str):
        from ...command.core import CommandRegistry
        registry = CommandRegistry()
        widget_scope = None if scope == "*" else scope
        commands = registry.get_commands_by_category(category, widget_scope=widget_scope)
        
        menu = QtWidgets.QMenu(btn)
        act_none = menu.addAction("なし(解除)")
        act_none.triggered.connect(lambda: self._on_select(scope, None))
        
        if commands:
            menu.addSeparator()
            for cid, cmd_class in sorted(commands.items()):
                meta = getattr(cmd_class, "meta", None)
                if meta:
                    display = getattr(meta, "display", cid)
                    act = menu.addAction(display)
                    payload = CommandPayload(cid, {})
                    act.triggered.connect(lambda _, p=payload: self._on_select(scope, p))
        else:
            act_empty = menu.addAction(f"({category}コマンドなし)")
            act_empty.setEnabled(False)
        
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))
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
        rl.setSpacing(uipx(6))
        btn = QtWidgets.QPushButton(scope, row)
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setStyleSheet("padding:2px 10px;")
        btn.clicked.connect(lambda _, sc=scope: self._pick_cmd(sc))
        edit = QtWidgets.QLineEdit(row)
        edit.setReadOnly(True)
        pv = self._payloads.get(scope)
        if pv:
            edit.setText(self._display(pv))
        elif value:
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
        except Exception as e:
            show_warning(self, f"MouseSection remove override failed: {scope}", exc=e)
            try:
                row.setParent(None)
                row.deleteLater()
            except Exception as e2:
                show_warning(self, f"MouseSection remove override cleanup failed: {scope}", exc=e2)
                return
        if not self.override_edits:
            self.overrides_container.setVisible(False)
        self._clear_binding(scope)
        self._payloads.pop(scope, None)
    def _current_key(self) -> MouseActionKey:
        held: tuple[MouseButton, ...] = ()
        mods: tuple[ModifierKey, ...] = ()
        if self.qualifier.kind == "mouse":
            b = self.qualifier.value
            if isinstance(b, MouseButton):
                held = (b,)
        elif self.qualifier.kind == "modifier":
            m = self.qualifier.value
            if isinstance(m, ModifierKey):
                mods = (m,)
        btn = MouseButton.NONE if self.click in (ClickType.WHEEL_UP, ClickType.WHEEL_DOWN, ClickType.DROP) else self.button
        return MouseActionKey(btn, self.click, held, mods)
    def _clear_binding(self, scope: str):
        try:
            self.store.set_binding(self._current_key(), scope, None)
        except Exception as e:
            show_warning(self, f"MouseSection clear binding failed: {scope}", exc=e)
    def _build_payload_with_options(self, cid: str) -> CommandPayload:
        return CommandPayload(cid, {})
    def _display(self, value: Any) -> str:
        return format_payload_display(value)
    def _to_saved(self, value: CommandPayload) -> CommandPayload:
        return value

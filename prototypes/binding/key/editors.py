from typing import Dict, List, Any, Tuple
from pathlib import Path
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.funcs import uipx
from ...command.ui import MenuBuilder
from ...utils import format_payload_display, CommandPayload
from ..common import WidgetRef
from .store import KeyBindingStore
from .shortcutmanager import ShortcutManager
from .sequence import KeySequence, KeySpecCatalog

class _SelectableList(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)
    def mousePressEvent(self, e: QtGui.QMouseEvent):
        idx = self.indexAt(e.pos())
        if not idx.isValid():
            super().mousePressEvent(e)
            try:
                if self.count() > 0:
                    self.setCurrentRow(0)
            except Exception:
                pass
            return
        super().mousePressEvent(e)

class KeyBindingEditor(QtWidgets.QDialog):
    def __init__(self, widgets: List[WidgetRef], commands: List[str] | None = None, parent=None):
        super().__init__(parent)
        self.widgets = widgets
        self._commands = list(commands) if isinstance(commands, list) else []
        self.setWindowTitle("Key Bindings")
        self.resize(uipx(600), uipx(480))
        self._store = KeyBindingStore()
        self._cat = KeySpecCatalog()
        self._mod_keys: List[str] = []
        self._main_keys: List[str] = []
        self._draft: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        self._filter_cmd_id: str | None = None
        self._build_ui()
        self._load_existing()
        self._refresh_lists()
        self._refresh_shortcuts()
        QtCore.QTimer.singleShot(0, self._clear_initial_selection)

    def _build_ui(self):
        l = QtWidgets.QVBoxLayout(self)
        row = QtWidgets.QHBoxLayout()
        col_mod = QtWidgets.QVBoxLayout()
        col_main = QtWidgets.QVBoxLayout()
        col_list = QtWidgets.QVBoxLayout()
        col_mod.addWidget(QtWidgets.QLabel("装飾キー"), 0)
        self.list_mods = _SelectableList(self)
        self.list_mods.currentItemChanged.connect(lambda: self._refresh_shortcuts())
        col_mod.addWidget(self.list_mods, 1)
        col_main.addWidget(QtWidgets.QLabel("主キー"), 0)
        self.list_main = _SelectableList(self)
        self.list_main.currentItemChanged.connect(lambda: self._refresh_shortcuts())
        col_main.addWidget(self.list_main, 1)
        btns = QtWidgets.QHBoxLayout()
        self.btn_add_binding = QtWidgets.QPushButton("新規追加", self)
        self.btn_add_binding.clicked.connect(self._add_binding)
        btns.addWidget(self.btn_add_binding, 0)
        self.btn_search = QtWidgets.QPushButton("コマンド検索", self)
        self.btn_search.clicked.connect(self._search)
        btns.addWidget(self.btn_search, 0)
        self.btn_reset_all = QtWidgets.QPushButton("デフォルト設定に戻す", self)
        self.btn_reset_all.clicked.connect(self._reset_all_defaults)
        btns.addWidget(self.btn_reset_all, 0)
        btns.addStretch(1)
        col_list.addLayout(btns)
        self.section_container = QtWidgets.QWidget(self)
        self.section_layout = QtWidgets.QVBoxLayout(self.section_container)
        self.section_layout.setContentsMargins(0,0,0,0)
        self.section_layout.setSpacing(uipx(6))
        scroll = QtWidgets.QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        scroll.setWidget(self.section_container)
        col_list.addWidget(scroll, 1)
        row.addLayout(col_mod, 1)
        row.addLayout(col_main, 1)
        row.addLayout(col_list, 6)
        l.addLayout(row, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        l.addWidget(bb, 0)

    def _load_existing(self):
        self._mod_keys = ["(なし)"]
        self._main_keys = []
        data = self._store.get_all()
        seqs: List[KeySequence] = []
        for seq, scopes in data.items():
            if isinstance(scopes, dict) and "*" in scopes and isinstance(scopes["*"], CommandPayload):
                seqs.append(seq)
        for seq, scopes in self._draft.items():
            if isinstance(scopes, dict) and "*" in scopes and isinstance(scopes["*"], CommandPayload):
                seqs.append(seq)
        for w in self.widgets:
            try:
                b = w.widget.get_shortcut_bindings()
                for s in b.keys():
                    pass
            except Exception:
                pass
        for seq in seqs:
            mod = seq.modifier or "(なし)"
            key = seq.key
            if mod and mod not in self._mod_keys:
                self._mod_keys.append(mod)
            if key and key not in self._main_keys:
                self._main_keys.append(key)

    def _refresh_lists(self):
        self.list_mods.clear()
        ordered_mods = ["(すべて)", "(なし)"] + self._sort_modifiers(self._mod_keys)
        items_mod = []
        seen = set()
        for k in ordered_mods:
            if k in seen:
                continue
            seen.add(k)
            if k in self._mod_keys or k in ("(すべて)", "(なし)"):
                items_mod.append(k)
        for k in items_mod:
            self.list_mods.addItem(k)
        self.list_main.clear()
        ordered_main = ["(すべて)"] + self._sort_main_keys(self._main_keys)
        items_main = []
        seen2 = set()
        for k in ordered_main:
            if k in seen2:
                continue
            seen2.add(k)
            if k in self._main_keys or k == "(すべて)":
                items_main.append(k)
        for k in items_main:
            self.list_main.addItem(k)
        try:
            self.list_mods.setCurrentRow(0)
            self.list_main.setCurrentRow(0)
        except Exception:
            pass

    def _clear_initial_selection(self):
        try:
            if self.list_mods.count() > 0:
                self.list_mods.setCurrentRow(0)
            if self.list_main.count() > 0:
                self.list_main.setCurrentRow(0)
        except Exception:
            pass
        self._refresh_shortcuts()

    def _split_seq(self, seq: KeySequence) -> Tuple[str, str]:
        mod = seq.modifier or "(なし)"
        key = seq.key
        return (mod, key)

    def _refresh_shortcuts(self):
        self._rebuild_sections()
        self._update_add_button_enabled()

    def _rebuild_key_lists(self, preserve: bool = True):
        old_mod = self.list_mods.currentItem().text() if self.list_mods.currentRow() >= 0 else None
        old_main = self.list_main.currentItem().text() if self.list_main.currentRow() >= 0 else None
        self._load_existing()
        self._refresh_lists()
        if preserve:
            if old_mod:
                for i in range(self.list_mods.count()):
                    if self.list_mods.item(i).text() == old_mod:
                        self.list_mods.setCurrentRow(i)
                        break
            if old_main:
                for i in range(self.list_main.count()):
                    if self.list_main.item(i).text() == old_main:
                        self.list_main.setCurrentRow(i)
                        break
    
    def _select_lists_for_sequence(self, seq: KeySequence):
        mod, key = self._split_seq(seq)
        if mod:
            for i in range(self.list_mods.count()):
                if self.list_mods.item(i).text() == mod:
                    self.list_mods.setCurrentRow(i)
                    break
        if key:
            for i in range(self.list_main.count()):
                if self.list_main.item(i).text() == key:
                    self.list_main.setCurrentRow(i)
                    break

    def _mod_priority(self, name: str) -> int:
        return self._cat.modifier_priority(name)

    def _sort_modifiers(self, mods: List[str]) -> List[str]:
        return self._cat.sort_modifiers(mods)

    def _key_sort_tuple(self, k: str) -> tuple:
        return self._cat.key_sort_tuple(k)

    def _sort_main_keys(self, keys: List[str]) -> List[str]:
        return self._cat.sort_main_keys(keys)

    def _add_binding(self):
        d = _TwoKeyCaptureDialog(self)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        key_seq = d.result_sequence()
        if key_seq is None:
            return
        btn = self.btn_add_binding
        builder = MenuBuilder(self)
        def _prep(m: QtWidgets.QMenu):
            act_none = QtGui.QAction("なし(解除)", m)
            act_none.triggered.connect(lambda: self._on_select_command(key_seq, None))
            first = m.actions()[0] if m.actions() else None
            if first:
                m.insertAction(first, act_none)
                m.insertSeparator(first)
            else:
                m.addAction(act_none)
        builder.popup_all_roots(btn, selection_callback=lambda cid: self._on_select_command(key_seq, cid), context_provider=None, prepare=_prep, allow_options_with_selection=True)

    def _on_select_command(self, seq: KeySequence, cid):
        if cid is None:
            if seq in self._draft:
                self._draft.pop(seq, None)
            data = self._store.get_all()
            if seq in data:
                data.pop(seq, None)
                self._store.set_all(data)
            self._refresh_shortcuts()
            self._rebuild_sections()
            self._rebuild_key_lists()
            return
        if not isinstance(cid, CommandPayload):
            raise TypeError("Selection must provide CommandPayload")
        entry = self._draft.setdefault(seq, {})
        entry["*"] = cid
        self._refresh_shortcuts()
        self._rebuild_key_lists(preserve=False)
        self._select_lists_for_sequence(seq)

    def _apply(self):
        data = self._store.get_all()
        for seq, scopes in self._draft.items():
            if scopes:
                data[seq] = dict(scopes)
            else:
                data.pop(seq, None)
        self._store.set_all(data)
        for wref in self.widgets:
            bindings = {}
            for seq, scopes in data.items():
                target = scopes.get(wref.name) or scopes.get("*")
                if target:
                    bindings[seq] = target
            try:
                wref.widget.set_shortcut_bindings(bindings)
            except Exception:
                pass
        try:
            path = str(Path(__file__).resolve().parent.parent.parent / "key_bindings.json")
            self._store.save_to_file(path)
        except Exception:
            pass
        self.accept()

    def _display(self, value: Any) -> str:
        return format_payload_display(value)

    def _update_add_button_enabled(self):
        self.btn_add_binding.setEnabled(True)

    def _search(self):
        btn = self.btn_search
        builder = MenuBuilder(self)
        def _prep(m: QtWidgets.QMenu):
            act_none = QtGui.QAction("なし(解除)", m)
            act_none.triggered.connect(lambda: self._on_search_select(None))
            first = m.actions()[0] if m.actions() else None
            if first:
                m.insertAction(first, act_none)
                m.insertSeparator(first)
            else:
                m.addAction(act_none)
        builder.popup_all_roots(btn, selection_callback=lambda cid: self._on_search_select(cid), context_provider=None, prepare=_prep, allow_options_with_selection=True)

    def _on_search_select(self, cid):
        if cid is None:
            self._filter_cmd_id = None
            self._refresh_shortcuts()
            return
        if not isinstance(cid, CommandPayload):
            raise TypeError("Selection must provide CommandPayload")
        self._filter_cmd_id = cid.id
        self._refresh_shortcuts()

    def _rebuild_sections(self):
        while True:
            it = self.section_layout.takeAt(0)
            if not it:
                break
            w = it.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        sel_mod = self.list_mods.currentItem().text() if self.list_mods.currentRow() >= 0 else None
        sel_main = self.list_main.currentItem().text() if self.list_main.currentRow() >= 0 else None
        if sel_mod == "(すべて)":
            sel_mod = None
        if sel_main == "(すべて)":
            sel_main = None
        data = self._store.get_all()
        merged: Dict[KeySequence, Dict[str, CommandPayload]] = {}
        for k, v in data.items():
            if isinstance(v, dict):
                merged[k] = dict(v)
        for k, v in self._draft.items():
            merged[k] = dict(v)
        seqs: List[KeySequence] = []
        for seq, scopes in merged.items():
            a, b = self._split_seq(seq)
            if sel_mod is not None and sel_mod != a:
                continue
            if sel_main is not None and sel_main != b:
                continue
            if self._filter_cmd_id:
                found = False
                for v in scopes.values():
                    if isinstance(v, CommandPayload) and v.id == self._filter_cmd_id:
                        found = True
                        break
                if found:
                    seqs.append(seq)
            else:
                g = scopes.get("*")
                if isinstance(g, CommandPayload):
                    seqs.append(seq)
        def _section_key(s: KeySequence):
            return (self._key_sort_tuple(s.key), self._mod_priority(s.modifier or ""), s.modifier or "")
        for seq in sorted(seqs, key=_section_key):
            section = _KeySequenceSection(self.section_container, self.widgets, seq, merged.get(seq, {}), self._on_section_update, self._on_section_remove, self._on_section_reassign)
            self.section_layout.addWidget(section)
        self.section_layout.addStretch(1)
        self.section_container.setVisible(bool(seqs))

    def _on_section_update(self, seq: KeySequence, scopes: Dict[str, CommandPayload]):
        if scopes:
            self._draft[seq] = dict(scopes)
        else:
            self._draft.pop(seq, None)
        self._refresh_shortcuts()

    def _on_section_remove(self, seq: KeySequence):
        self._draft.pop(seq, None)
        data = self._store.get_all()
        if seq in data:
            data.pop(seq, None)
            self._store.set_all(data)
        self._refresh_shortcuts()
        self._rebuild_key_lists()

    def _on_section_reassign(self, old_seq: KeySequence, new_seq: KeySequence, scopes: Dict[str, CommandPayload]):
        if not isinstance(new_seq, KeySequence) or old_seq == new_seq:
            return
        self._draft.pop(old_seq, None)
        data = self._store.get_all()
        if old_seq in data:
            data.pop(old_seq, None)
            self._store.set_all(data)
        self._draft[new_seq] = dict(scopes or {})
        self._refresh_shortcuts()
        self._rebuild_key_lists(preserve=False)
        self._select_lists_for_sequence(new_seq)

    def _reset_all_defaults(self):
        from .defaults import default_key_bindings
        defs = default_key_bindings()
        self._draft = {}
        for spec, payload in defs:
            if not spec:
                continue
            seq = KeySequence(spec)
            self._draft[seq] = {"*": payload}
        self._store.set_all({})
        self._refresh_shortcuts()
        self._load_existing()
        self._refresh_lists()

class _TwoKeyCaptureDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("キー入力")
        self._mgr = ShortcutManager()
        self._pressed_keys: List[Tuple[int, str]] = []
        self._final_keys: List[str] = []
        self._press_snapshot: List[Tuple[int, str]] = []
        l = QtWidgets.QVBoxLayout(self)
        self.lbl = QtWidgets.QLabel("最大2つまでキーを押してください", self)
        l.addWidget(self.lbl)
        row = QtWidgets.QHBoxLayout()
        self.e1 = QtWidgets.QLineEdit(self)
        self.e1.setReadOnly(True)
        self.e1.setPlaceholderText("1つ目のキー")
        self.e2 = QtWidgets.QLineEdit(self)
        self.e2.setReadOnly(True)
        self.e2.setPlaceholderText("2つ目のキー")
        row.addWidget(self.e1)
        row.addWidget(self.e2)
        l.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self._mgr.add_key_listener(self, on_press=self._on_press, on_release=self._on_release)

    def _on_press(self, k: int):
        if self._final_keys:
            self._final_keys.clear()
            self._press_snapshot.clear()
            self._clear_display()
        if len(self._pressed_keys) >= 2:
            return
        if not self._mgr._resolver.is_key_bindable(k):
            return
        name = self._mgr.key_name(k, pretty=True)
        if any(key == k for key, _ in self._pressed_keys):
            return
        self._pressed_keys.append((k, name))
        self._press_snapshot = list(self._pressed_keys)
        self._update_display()

    def _on_release(self, k: int):
        if self._final_keys:
            return
        remaining = [(key, n) for key, n in self._pressed_keys if key != k]
        if remaining:
            self._pressed_keys = remaining
            return
        self._pressed_keys.clear()
        snap = list(self._press_snapshot) if self._press_snapshot else []
        self._finalize_combo(snap)
        self._press_snapshot.clear()

    def _clear_display(self):
        self.e1.clear()
        self.e2.clear()
        
    def _update_display(self):
        self.e1.clear()
        self.e2.clear()
        if len(self._pressed_keys) >= 1:
            self.e1.setText(self._pressed_keys[0][1])
        if len(self._pressed_keys) >= 2:
            self.e2.setText(self._pressed_keys[1][1])

    def _finalize_combo(self, keys: List[Tuple[int, str]] | None = None):
        if self._final_keys:
            return
        src = list(keys) if keys is not None else list(self._press_snapshot) or list(self._pressed_keys)
        if not src:
            return
        self._final_keys = [self._mgr.key_name(k, pretty=False) for k, _ in src]
        if len(src) >= 1:
            self.e1.setText(src[0][1])
        if len(src) >= 2:
            self.e2.setText(src[1][1])
    
    def _reset_state(self):
        self._pressed_keys.clear()
        self._press_snapshot.clear()
        if not self._final_keys:  # 確定していない場合のみクリア
            self._clear_display()

    def result_sequence(self) -> KeySequence | None:
        if not self._final_keys:
            return None
        print(self._final_keys)
        return KeySequence(self._final_keys[:2])

    def accept(self) -> None:
        if not self._final_keys:
            if self._press_snapshot:
                self._finalize_combo(list(self._press_snapshot))
            elif self._pressed_keys:
                self._finalize_combo(list(self._pressed_keys))
        super().accept()

    def focusOutEvent(self, event):
        if self._pressed_keys:
            self._reset_state()
        super().focusOutEvent(event)
    
    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.WindowStateChange:
            if self._pressed_keys:
                self._reset_state()
        elif event.type() == QtCore.QEvent.ActivationChange and not self.isActiveWindow():
            if self._pressed_keys:
                self._reset_state()
        super().changeEvent(event)

    def done(self, r: int) -> None:
        try:
            self._mgr.remove_key_listeners(self)
        except Exception:
            pass
        super().done(r)

class _KeySequenceSection(QtWidgets.QGroupBox):
    def __init__(self, parent: QtWidgets.QWidget, widgets: List[WidgetRef], sequence: KeySequence, scopes: Dict[str, CommandPayload], on_update, on_remove, on_reassign):
        super().__init__(parent)
        self.widgets = widgets
        self.sequence = sequence
        self.scopes = dict(scopes)
        self.on_update = on_update
        self.on_remove = on_remove
        self.on_reassign = on_reassign
        self.setTitle(str(self.sequence))
        l = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QHBoxLayout()
        self.btn_global = QtWidgets.QPushButton("コマンド", self)
        self.btn_global.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_global.clicked.connect(lambda: self._pick_cmd("*"))
        header.addWidget(self.btn_global,0)
        self.btn_overrides = QtWidgets.QToolButton(self)
        self.btn_overrides.setText("カスタム")
        self.btn_overrides.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.ov_menu = QtWidgets.QMenu(self.btn_overrides)
        self.ov_menu.aboutToShow.connect(self._refresh_overrides_menu)
        self.btn_overrides.setMenu(self.ov_menu)
        header.addWidget(self.btn_overrides,0)
        btn_assign = QtWidgets.QPushButton("割当変更", self)
        btn_assign.setCursor(QtCore.Qt.PointingHandCursor)
        btn_assign.clicked.connect(self._assign)
        header.addWidget(btn_assign,0)
        rem = QtWidgets.QToolButton(self)
        rem.setText("削除")
        rem.clicked.connect(lambda: self.on_remove(self.sequence))
        header.addWidget(rem,0)
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
        l.addWidget(self.overrides_container)
        self.overrides_container.setVisible(False)
        self._payloads: Dict[str, CommandPayload] = {}
        self._load()

    def _assign(self):
        d = _TwoKeyCaptureDialog(self)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        new_seq = d.result_sequence()
        if not new_seq:
            return
        scopes: Dict[str, CommandPayload] = {}
        if "*" in self._payloads:
            scopes["*"] = self._payloads["*"]
        for scope in list(self.override_edits.keys()):
            if scope in self._payloads:
                scopes[scope] = self._payloads[scope]
        self.on_reassign(self.sequence, new_seq, scopes)

    def _load(self):
        found: Dict[str,str] = {}
        for scope, cmd in self.scopes.items():
            if isinstance(cmd, CommandPayload):
                found[scope] = cmd.id
                self._payloads[scope] = cmd
        self._rebuild(found)
        g = self._payloads.get("*")
        if g:
            self.global_edit.setText(format_payload_display(g))
        self.overrides_container.setVisible(any(s != "*" for s in self._payloads.keys()))

    def _pick_cmd(self, scope: str):
        btn = self.global_edit if scope == "*" else self.override_edits.get(scope)
        if btn is None:
            return
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

    def _on_select(self, scope: str, cid):
        if cid is None:
            if scope == "*":
                self.global_edit.setText("")
                self._payloads.pop("*", None)
            else:
                self._remove_override(scope)
            self._commit()
            return
        if not isinstance(cid, CommandPayload):
            raise TypeError("Selection must provide CommandPayload")
        if scope == "*":
            self.global_edit.setText(format_payload_display(cid))
            self._payloads["*"] = cid
        else:
            if scope in self.override_edits:
                self.override_edits[scope].setText(format_payload_display(cid))
                self._payloads[scope] = cid
        if scope != "*" and cid:
            self.overrides_container.setVisible(True)
        self._commit()

    def _commit(self):
        scopes: Dict[str, CommandPayload] = {}
        if "*" in self._payloads:
            scopes["*"] = self._payloads["*"]
        for scope in list(self.override_edits.keys()):
            if scope in self._payloads:
                scopes[scope] = self._payloads[scope]
        self.on_update(self.sequence, scopes)
        self._refresh_overrides_menu()

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

    def _rebuild(self, found: Dict[str,str]):
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
            self._create_row(scope, found.get(scope, ""))
        self.overrides_layout.addStretch(1)
        self._refresh_overrides_menu()

    def _create_row(self, scope: str, value: str):
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
            edit.setText(format_payload_display(pv))
        elif value:
            edit.setText(value)
        rl.addWidget(btn,0)
        rl.addWidget(edit,1)
        self.override_edits[scope] = edit
        self.overrides_layout.insertWidget(self.overrides_layout.count(), row)

    def _add_override(self, scope: str):
        if scope in self.override_edits:
            return
        self._create_row(scope, "")
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
        self._payloads.pop(scope, None)
        if not self.override_edits:
            self.overrides_container.setVisible(False)
        self._commit()

ShortcutBindingEditor = KeyBindingEditor

from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets
from .....utils.formatting import dpix
from ...command.payload import CommandPayload
from ..common import WidgetRef
from .store import KeyBindingStore
from .shortcutmanager import ShortcutManager
from .sequence import KeySequence, KeySpecCatalog
from ..editors_common import BindingEditorBase, ScopedPayloadSectionBase, DraftOverlay, clear_layout, popup_command_picker
from ....lang.manager import t


class _SelectableList(QtWidgets.QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlternatingRowColors(True)

    def mousePressEvent(self, e: QtGui.QMouseEvent):
        idx = self.indexAt(e.pos())
        if not idx.isValid():
            super().mousePressEvent(e)
            if self.count() > 0:
                self.setCurrentRow(0)
            return
        super().mousePressEvent(e)


class KeyBindingEditor(BindingEditorBase):
    def __init__(self, widgets: list[WidgetRef], commands: list[str] | None = None, parent=None):
        if parent is None and isinstance(commands, QtWidgets.QWidget):
            parent = commands
            commands = None
        super().__init__(widgets, KeyBindingStore.instance(), parent)
        self._commands = list(commands or [])
        self.setWindowTitle(t("Key Bindings"))
        self.resize(dpix(600), dpix(480))
        self._cat = KeySpecCatalog()
        self._mod_keys: list[str] = []
        self._main_keys: list[str] = []
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
        col_mod.addWidget(QtWidgets.QLabel(t("Modifier Key")), 0)
        self.list_mods = _SelectableList(self)
        self.list_mods.currentItemChanged.connect(lambda: self._refresh_shortcuts())
        col_mod.addWidget(self.list_mods, 1)
        col_main.addWidget(QtWidgets.QLabel(t("Main Key")), 0)
        self.list_main = _SelectableList(self)
        self.list_main.currentItemChanged.connect(lambda: self._refresh_shortcuts())
        col_main.addWidget(self.list_main, 1)
        btns = QtWidgets.QHBoxLayout()
        self.btn_add_binding = QtWidgets.QPushButton(t("Add New"), self)
        self.btn_add_binding.clicked.connect(self._add_binding)
        btns.addWidget(self.btn_add_binding, 0)
        self.btn_search = QtWidgets.QPushButton(t("Search Command"), self)
        self.btn_search.clicked.connect(self._search)
        btns.addWidget(self.btn_search, 0)
        self.btn_reset_all = QtWidgets.QPushButton(t("Reset to Defaults"), self)
        self.btn_reset_all.clicked.connect(self._reset_all_defaults)
        btns.addWidget(self.btn_reset_all, 0)
        btns.addStretch(1)
        col_list.addLayout(btns)
        self.section_container = QtWidgets.QWidget(self)
        self.section_layout = QtWidgets.QVBoxLayout(self.section_container)
        self.section_layout.setContentsMargins(0, 0, 0, 0)
        self.section_layout.setSpacing(dpix(6))
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
        self._mod_keys = [t("(None)")]
        self._main_keys = []
        merged = self._merged_data()
        seqs: list[KeySequence] = []
        for seq, scopes in merged.items():
            if DraftOverlay.has_any_payload(scopes):
                seqs.append(seq)
        for seq in seqs:
            mod = seq.modifier or t("(None)")
            key = seq.key
            if mod and mod not in self._mod_keys:
                self._mod_keys.append(mod)
            if key and key not in self._main_keys:
                self._main_keys.append(key)

    def _refresh_lists(self):
        self.list_mods.clear()
        ordered_mods = [t("(All)"), t("(None)")] + self._sort_modifiers(self._mod_keys)
        items_mod = []
        seen = set()
        for k in ordered_mods:
            if k in seen:
                continue
            seen.add(k)
            if k in self._mod_keys or k in (t("(All)"), t("(None)")):
                items_mod.append(k)
        for k in items_mod:
            self.list_mods.addItem(k)
        self.list_main.clear()
        ordered_main = [t("(All)")] + self._sort_main_keys(self._main_keys)
        items_main = []
        seen2 = set()
        for k in ordered_main:
            if k in seen2:
                continue
            seen2.add(k)
            if k in self._main_keys or k == t("(All)"):
                items_main.append(k)
        for k in items_main:
            self.list_main.addItem(k)
        if self.list_mods.count() > 0:
            self.list_mods.setCurrentRow(0)
        if self.list_main.count() > 0:
            self.list_main.setCurrentRow(0)

    def _clear_initial_selection(self):
        if self.list_mods.count() > 0:
            self.list_mods.setCurrentRow(0)
        if self.list_main.count() > 0:
            self.list_main.setCurrentRow(0)
        self._refresh_shortcuts()

    def _split_seq(self, seq: KeySequence) -> tuple[str, str]:
        mod = seq.modifier or t("(None)")
        key = seq.key
        return (mod, key)

    def _refresh_shortcuts(self):
        self._rebuild_sections()

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

    def _sort_modifiers(self, mods: list[str]) -> list[str]:
        return self._cat.sort_modifiers(mods, exclude=(t("(All)"), t("(None)")))

    def _key_sort_tuple(self, k: str) -> tuple:
        return self._cat.key_sort_tuple(k)

    def _sort_main_keys(self, keys: list[str]) -> list[str]:
        return self._cat.sort_main_keys(keys, exclude=(t("(All)"),))

    def _add_binding(self):
        d = _TwoKeyCaptureDialog(self)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        key_seq = d.result_sequence()
        if key_seq is None:
            return
        popup_command_picker(self, self.btn_add_binding, scope="*", on_select=lambda _, cid: self._on_select_command(key_seq, cid), allow_options_with_selection=True)

    def _on_select_command(self, seq: KeySequence, cid):
        if cid is None:
            self._draft.delete(seq)
            self._refresh_shortcuts()
            self._rebuild_sections()
            self._rebuild_key_lists()
            return
        if not isinstance(cid, CommandPayload):
            raise TypeError("Selection must provide CommandPayload")
        self._draft.update(seq, {"*": cid})
        self._refresh_shortcuts()
        self._rebuild_key_lists(preserve=False)
        self._select_lists_for_sequence(seq)

    def _apply(self):
        data = self._merged_data()
        self._store.set_all(data)
        self._apply_to_widgets(data, "set_shortcut_bindings")
        from ..manager import BindingManager

        self._save_store(BindingManager.instance().key_bindings_path())
        self.accept()

    def _search(self):
        popup_command_picker(self, self.btn_search, scope="*", on_select=lambda _, cid: self._on_search_select(cid), allow_options_with_selection=True)

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
        clear_layout(self.section_layout, self, "KeyBindingEditor rebuild")
        sel_mod = self.list_mods.currentItem().text() if self.list_mods.currentRow() >= 0 else None
        sel_main = self.list_main.currentItem().text() if self.list_main.currentRow() >= 0 else None
        if sel_mod == t("(All)"):
            sel_mod = None
        if sel_main == t("(All)"):
            sel_main = None
        merged = self._merged_data()
        seqs: list[KeySequence] = []
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
                if DraftOverlay.has_any_payload(scopes):
                    seqs.append(seq)

        def _section_key(s: KeySequence):
            return (self._key_sort_tuple(s.key), self._mod_priority(s.modifier or ""), s.modifier or "")

        for seq in sorted(seqs, key=_section_key):
            section = _KeySequenceSection(self.section_container, self.widgets, seq, merged.get(seq, {}), self._on_section_update, self._on_section_remove, self._on_section_reassign)
            self.section_layout.addWidget(section)
        self.section_layout.addStretch(1)
        self.section_container.setVisible(bool(seqs))

    def _on_section_update(self, seq: KeySequence, scopes: dict[str, CommandPayload]):
        self._draft.update(seq, scopes)
        self._refresh_shortcuts()

    def _on_section_remove(self, seq: KeySequence):
        self._draft.delete(seq)
        self._refresh_shortcuts()
        self._rebuild_key_lists()

    def _on_section_reassign(self, old_seq: KeySequence, new_seq: KeySequence, scopes: dict[str, CommandPayload]):
        if not isinstance(new_seq, KeySequence) or old_seq == new_seq:
            return
        self._draft.delete(old_seq)
        self._draft.update(new_seq, scopes or {})
        self._refresh_shortcuts()
        self._rebuild_key_lists(preserve=False)
        self._select_lists_for_sequence(new_seq)

    def _reset_all_defaults(self):
        self._reset_draft_to_seed()
        self._refresh_shortcuts()
        self._load_existing()
        self._refresh_lists()


class _TwoKeyCaptureDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle(t("Key Input"))
        self._mgr = ShortcutManager()
        self._pressed_keys: list[tuple[int, str]] = []
        self._final_keys: list[str] = []
        self._press_snapshot: list[tuple[int, str]] = []
        l = QtWidgets.QVBoxLayout(self)
        self.lbl = QtWidgets.QLabel(t("Press up to 2 keys"), self)
        l.addWidget(self.lbl)
        row = QtWidgets.QHBoxLayout()
        self.e1 = QtWidgets.QLineEdit(self)
        self.e1.setReadOnly(True)
        self.e1.setPlaceholderText(t("First Key"))
        self.e2 = QtWidgets.QLineEdit(self)
        self.e2.setReadOnly(True)
        self.e2.setPlaceholderText(t("Second Key"))
        row.addWidget(self.e1)
        row.addWidget(self.e2)
        l.addLayout(row)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self._mgr.add_key_listener(self, on_press=self._on_press, on_release=self._on_release, consume=True)

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

    def _finalize_combo(self, keys: list[tuple[int, str]] | None = None):
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
        if not self._final_keys:
            self._clear_display()

    def result_sequence(self) -> KeySequence | None:
        if not self._final_keys:
            return None
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
        if event.type() == QtCore.QEvent.WindowStateChange or (event.type() == QtCore.QEvent.ActivationChange and not self.isActiveWindow()):
            if self._pressed_keys:
                self._reset_state()
        super().changeEvent(event)

    def done(self, r: int) -> None:
        self._mgr.remove_key_listeners(self)
        super().done(r)


class _KeySequenceSection(ScopedPayloadSectionBase):
    def __init__(self, parent: QtWidgets.QWidget, widgets: list[WidgetRef], sequence: KeySequence, scopes: dict[str, CommandPayload], on_update, on_remove, on_reassign):

        super().__init__(parent, widgets, header_button_text=t("Command"))
        self.sequence = sequence
        self.on_update = on_update
        self.on_remove = on_remove
        self.on_reassign = on_reassign
        self.setTitle(str(self.sequence))
        btn_assign = QtWidgets.QPushButton(t("Reassign"), self)
        btn_assign.setCursor(QtCore.Qt.PointingHandCursor)
        btn_assign.clicked.connect(self._assign)
        self.header.insertWidget(2, btn_assign, 0)
        rem = QtWidgets.QToolButton(self)
        rem.setText(t("Delete"))
        rem.clicked.connect(lambda: self.on_remove(self.sequence))
        self.header.insertWidget(3, rem, 0)
        self.load_from_scopes(scopes)

    def _assign(self):
        d = _TwoKeyCaptureDialog(self)
        if d.exec() != QtWidgets.QDialog.Accepted:
            return
        new_seq = d.result_sequence()
        if not new_seq:
            return
        scopes: dict[str, CommandPayload] = {}
        if "*" in self._payloads:
            scopes["*"] = self._payloads["*"]
        for scope in list(self.override_edits.keys()):
            if scope in self._payloads:
                scopes[scope] = self._payloads[scope]
        self.on_reassign(self.sequence, new_seq, scopes)

    def _after_change(self) -> None:
        super()._after_change()
        self.on_update(self.sequence, self.collect_scopes())


ShortcutBindingEditor = KeyBindingEditor

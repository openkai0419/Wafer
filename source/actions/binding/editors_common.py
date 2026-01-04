from __future__ import annotations

from typing import Any, Dict, List

from PySide6 import QtCore, QtGui, QtWidgets

from source.common.errors import show_warning
from source.common.funcs import uipx

from ..command.payload import CommandPayload, format_payload_display
from ..command.ui import MenuBuilder
from .common import WidgetRef


def clear_layout(layout: QtWidgets.QLayout, owner: QtWidgets.QWidget | None, label: str) -> None:
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
            clear_layout(sub, owner, label)
    if err is not None:
        show_warning(owner, f"{label} had {err_count} errors", exc=err)


def popup_command_picker(
    parent: QtWidgets.QWidget,
    btn: QtWidgets.QWidget,
    *,
    scope: str,
    on_select,
    allow_options_with_selection: bool = True,
):
    builder = MenuBuilder(parent)

    def _prep(m: QtWidgets.QMenu, sc=scope):
        act_none = QtGui.QAction("なし(解除)", m)
        act_none.triggered.connect(lambda _, s=sc: on_select(s, None))
        first = m.actions()[0] if m.actions() else None
        if first:
            m.insertAction(first, act_none)
            m.insertSeparator(first)
        else:
            m.addAction(act_none)

    builder.popup_all_roots(
        btn,
        selection_callback=lambda cid, sc=scope: on_select(sc, cid),
        context_provider=None,
        prepare=_prep,
        allow_options_with_selection=allow_options_with_selection,
    )


class ScopedPayloadSectionBase(QtWidgets.QGroupBox):
    def __init__(
        self,
        parent: QtWidgets.QWidget,
        widgets: List[WidgetRef],
        *,
        header_button_text: str,
    ):
        super().__init__(parent)
        self.widgets = widgets
        self._payloads: Dict[str, CommandPayload] = {}
        l = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QHBoxLayout()
        self.header = header
        self.btn_global = QtWidgets.QPushButton(header_button_text, self)
        self.btn_global.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_global.clicked.connect(lambda: self._pick_cmd("*"))
        header.addWidget(self.btn_global, 0)
        self.btn_overrides = QtWidgets.QToolButton(self)
        self.btn_overrides.setText("専用")
        self.btn_overrides.setPopupMode(QtWidgets.QToolButton.InstantPopup)
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
        self.overrides_layout.setContentsMargins(uipx(4), uipx(4), uipx(4), uipx(4))
        self.overrides_layout.setSpacing(uipx(6))
        self.override_edits: Dict[str, QtWidgets.QLineEdit] = {}
        l.addWidget(self.overrides_container)
        self.overrides_container.setVisible(False)

    def set_header_button_text(self, text: str) -> None:
        self.btn_global.setText(str(text))

    def load_from_scopes(self, scopes: Dict[str, Any]) -> None:
        self.global_edit.clear()
        for e in self.override_edits.values():
            e.clear()
        self._payloads.clear()
        found: Dict[str, str] = {}
        for scope, cmd in (scopes or {}).items():
            if isinstance(cmd, CommandPayload):
                found[str(scope)] = cmd.id
                self._payloads[str(scope)] = cmd
        self._rebuild(found)
        g = self._payloads.get("*")
        if g:
            self.global_edit.setText(format_payload_display(g))
        self.overrides_container.setVisible(any(s != "*" for s in self._payloads.keys()))

    def collect_scopes(self) -> Dict[str, CommandPayload]:
        scopes: Dict[str, CommandPayload] = {}
        if "*" in self._payloads:
            scopes["*"] = self._payloads["*"]
        for scope in list(self.override_edits.keys()):
            if scope in self._payloads:
                scopes[scope] = self._payloads[scope]
        return scopes

    def _pick_cmd(self, scope: str) -> None:
        btn = self.global_edit if scope == "*" else self.override_edits.get(scope)
        if btn is None:
            return
        popup_command_picker(self, btn, scope=scope, on_select=self._on_select, allow_options_with_selection=True)

    def _on_select(self, scope: str, cid) -> None:
        if cid is None:
            if scope == "*":
                self.global_edit.setText("")
                self._payloads.pop("*", None)
            else:
                self._remove_override(scope)
            self._after_change()
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
        self._after_change()

    def _after_change(self) -> None:
        if not self.override_edits:
            self.overrides_container.setVisible(False)
        self._refresh_overrides_menu()

    def _refresh_overrides_menu(self) -> None:
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

    def _rebuild(self, found: Dict[str, str]) -> None:
        clear_layout(self.overrides_layout, self, "ScopedPayloadSectionBase rebuild")
        self.override_edits.clear()
        ordered = sorted([s for s in found.keys() if s != "*"]) if found else []
        for scope in ordered:
            self._create_row(scope, found.get(scope, ""))
        self.overrides_layout.addStretch(1)
        self._refresh_overrides_menu()

    def _create_row(self, scope: str, value: str) -> None:
        row = QtWidgets.QWidget(self.overrides_container)
        rl = QtWidgets.QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
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
            edit.setText(format_payload_display(value))
        rl.addWidget(btn, 0)
        rl.addWidget(edit, 1)
        self.override_edits[scope] = edit
        self.overrides_layout.insertWidget(self.overrides_layout.count(), row)

    def _add_override(self, scope: str) -> None:
        if scope in self.override_edits:
            return
        self._create_row(scope, "")
        self.overrides_container.setVisible(True)
        self._refresh_overrides_menu()

    def _remove_override(self, scope: str) -> None:
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
            show_warning(self, f"ScopedPayloadSectionBase remove override failed: {scope}", exc=e)
            try:
                row.setParent(None)
                row.deleteLater()
            except Exception as e2:
                show_warning(self, f"ScopedPayloadSectionBase remove override cleanup failed: {scope}", exc=e2)
                return
        self._payloads.pop(scope, None)

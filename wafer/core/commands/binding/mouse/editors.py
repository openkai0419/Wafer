from __future__ import annotations

from dataclasses import dataclass
from PySide6 import QtCore, QtGui, QtWidgets
from .....utils.formatting import dpix
from .types import MouseActionKey, ClickType, MouseButton, ModifierKey
from ...command.maker import MenuMaker
from ...command.menu_builder import MenuBuilder
from .store import MouseBindingStore
from ...command.payload import CommandPayload
from ..common import WidgetRef
from .....utils.logs import AppLogger
from ..editors_common import BindingEditorBase, ScopedPayloadSectionBase, clear_layout


@dataclass(frozen=True)
class MouseQualifier:
    kind: str
    value: object | None


class MouseBindingEditor(BindingEditorBase):
    def __init__(self, widgets: list[WidgetRef], parent=None):
        super().__init__(widgets, MouseBindingStore.instance(), parent)
        self.setWindowTitle("Mouse Bindings")
        self.resize(dpix(640), dpix(480))
        self._setup()
        self._load_actions()
        self._reload_sections()

    def _setup(self):
        l = QtWidgets.QVBoxLayout(self)
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal, self)
        left_container = QtWidgets.QWidget(self.splitter)
        left_layout = QtWidgets.QVBoxLayout(left_container)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(dpix(4))
        label_actions = QtWidgets.QLabel(self.t.tr("Mouse Actions:"), left_container)
        self.list_actions = QtWidgets.QListWidget(left_container)
        self.list_actions.setAlternatingRowColors(True)
        self.list_actions.currentRowChanged.connect(lambda _: self._reload_sections())
        left_layout.addWidget(label_actions, 0)
        left_layout.addWidget(self.list_actions, 1)
        self.scroll = QtWidgets.QScrollArea(self.splitter)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
        from wafer.core.color.theme import ThemeManager

        _p = ThemeManager.instance().palette
        self.scroll.setStyleSheet(f"QScrollArea{{border:none;}} QScrollArea> QWidget{{background:{_p.bg_primary};}}")
        self.panel = QtWidgets.QWidget(self.scroll)
        self.panel.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.scroll.setWidget(self.panel)
        self.panel_layout = QtWidgets.QVBoxLayout(self.panel)
        self.sections_container = QtWidgets.QWidget(self.panel)
        self.sections_container.setAttribute(QtCore.Qt.WA_StyledBackground, True)
        self.sections_layout = QtWidgets.QVBoxLayout(self.sections_container)
        self.sections_layout.setContentsMargins(0, 0, 0, 0)
        self.sections_layout.setSpacing(dpix(8))
        self.panel_layout.addWidget(self.sections_container, 1)
        footer = QtWidgets.QHBoxLayout()
        footer.addStretch(1)
        self.btn_reset_action = QtWidgets.QPushButton(self.t.tr("Reset to Defaults"), self.panel)
        self.btn_reset_action.setCursor(QtCore.Qt.PointingHandCursor)
        self.btn_reset_action.clicked.connect(self._reset_current_action)
        footer.addWidget(self.btn_reset_action, 0)
        self.panel_layout.addLayout(footer)
        self.sections: list[MouseSection] = []
        self.splitter.addWidget(left_container)
        self.splitter.addWidget(self.scroll)
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setSizes([dpix(120), dpix(420)])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        l.addWidget(self.splitter, 1)
        bb = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel, self)
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)

    def _actions(self) -> list[tuple[str, MouseButton, ClickType]]:
        r: list[tuple[str, MouseButton, ClickType]] = []
        for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
            r.append((f"{b.name} SINGLE", b, ClickType.SINGLE))
            r.append((f"{b.name} DOUBLE", b, ClickType.DOUBLE))
        for b in [MouseButton.LEFT, MouseButton.RIGHT, MouseButton.MIDDLE, MouseButton.X1, MouseButton.X2]:
            r.append((f"{b.name} DRAG", b, ClickType.DRAG_START))
        r.append(("WHEEL UP", MouseButton.NONE, ClickType.WHEEL_UP))
        r.append(("WHEEL DOWN", MouseButton.NONE, ClickType.WHEEL_DOWN))
        r.append(("DROP", MouseButton.NONE, ClickType.DROP))
        return r

    def _qualifiers_for_sections(self, button: MouseButton, click: ClickType) -> list[MouseQualifier]:
        qs: list[MouseQualifier] = [MouseQualifier("none", None)]
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

    def _current_action(self) -> tuple[MouseButton, ClickType]:
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
        if not hasattr(self, "sections") or not self.sections:
            return
        for s in self.sections:
            try:
                key = s._current_key()
            except Exception as e:
                AppLogger.warning("MouseBindingEditor _current_key failed", exc=e)
                continue
            d = s.collect_entries()
            scopes = d.get(key, {})
            self._draft.update(key, scopes)

    def _clear_sections(self):
        clear_layout(self.sections_layout, self, "MouseBindingEditor clear sections")
        try:
            self.panel.update()
            self.scroll.viewport().update()
            QtWidgets.QApplication.processEvents()
        except Exception as e:
            AppLogger.warning("MouseBindingEditor clear sections update failed", exc=e)

    def _apply(self):
        self._save_current_sections_to_draft()
        data = self._merged_data()
        self._store.set_all(data)
        self._apply_to_widgets(data, "set_mouse_bindings")
        from ..manager import BindingManager

        self._save_store(BindingManager.instance().mouse_bindings_path())
        self.accept()

    def _reset_to_defaults(self):
        try:
            self._reset_draft_to_seed()
            self._reload_sections()
        except Exception as e:
            AppLogger.warning("MouseBindingEditor reset_to_defaults failed", exc=e)

    def _reset_current_action(self):
        try:
            b, c = self._current_action()
            defs = MouseBindingStore.instance()._seed_data()
            cur = self._store.get_all()
            aff_keys = set()
            for k in cur:
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in defs:
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in list(self._draft.keys()):
                if k.button == b and k.click_type == c:
                    aff_keys.add(k)
            for k in aff_keys:
                if k in defs:
                    self._draft.update(k, dict(defs[k]))
                else:
                    self._draft.delete(k)
            self._reload_sections(skip_save=True)
        except Exception as e:
            AppLogger.warning("MouseBindingEditor reset_current_action failed", exc=e)


class MouseSection(ScopedPayloadSectionBase):
    def __init__(self, parent: QtWidgets.QWidget, widgets: list[WidgetRef], qualifier: MouseQualifier, store: MouseBindingStore):
        super().__init__(parent, widgets, header_button_text="")
        self.qualifier = qualifier
        self.store = store
        self.button: MouseButton = MouseButton.LEFT
        self.click: ClickType = ClickType.SINGLE
        self.setTitle("")
        self.btn_global.setStyleSheet(f"padding:{dpix(4)}px {dpix(12)}px;")
        self.btn_overrides.setStyleSheet(f"padding:{dpix(4)}px {dpix(4)}px;")
        self.list_order: list[str] = []

    def set_action(self, button: MouseButton, click: ClickType):
        self.button = button
        self.click = click
        t = self._title()
        self.setTitle("")
        self.set_header_button_text(t)

    def _title(self) -> str:
        if self.qualifier.kind == "none":
            return self.t.tr("★ No Modifier")
        if self.qualifier.kind == "mouse":
            b = self.qualifier.value
            if isinstance(b, MouseButton):
                return self.t("{button} +", button=b.name)
            return "(invalid)"
        if self.qualifier.kind == "modifier":
            m = self.qualifier.value
            if m == ModifierKey.SHIFT:
                return self.t.tr("Shift +")
            if m == ModifierKey.CTRL:
                return self.t.tr("Ctrl +")
            if m == ModifierKey.ALT:
                return self.t.tr("Alt +")
            return "(invalid)"
        return "(invalid)"

    def load_from_data(self, data: dict[MouseActionKey, dict[str, CommandPayload]]):
        expected_key = self._current_key()
        scopes = data.get(expected_key, {})
        self.load_from_scopes(scopes)

    def _pick_cmd(self, scope: str):
        btn = self.global_edit if scope == "*" else self.override_edits.get(scope)
        if btn is None:
            return

        if self._is_drag_type():
            self._show_category_menu(btn, scope, "drag")
        elif self._is_drop_type():
            self._show_category_menu(btn, scope, "drop")
        else:
            super()._pick_cmd(scope)

    def _is_drag_type(self) -> bool:
        return self.click == ClickType.DRAG_START

    def _is_drop_type(self) -> bool:
        return self.click == ClickType.DROP

    def _show_category_menu(self, btn, scope: str, category: str):
        from ...command.core import CommandRegistry

        registry = CommandRegistry.instance()
        widget_scope = None if scope == "*" else scope
        commands = registry.get_commands_by_category(category, widget_scope=widget_scope)

        names = sorted(commands.keys()) if commands else []
        maker = MenuMaker()
        builder = MenuBuilder(maker, self)

        def _prep(m: QtWidgets.QMenu, sc=scope, cat=category):
            act_none = QtGui.QAction(self.t.tr("None (Unset)"), m)
            act_none.triggered.connect(lambda _, s=sc: self._on_select(s, None))
            first = m.actions()[0] if m.actions() else None
            if first:
                m.insertAction(first, act_none)
                m.insertSeparator(first)
            else:
                m.addAction(act_none)
            if not names:
                m.addSeparator()
                act_empty = m.addAction(self.t("(No {cat} commands)", cat=cat))
                act_empty.setEnabled(False)

        builder.popup_names(
            btn,
            names,
            selection_callback=lambda payload, sc=scope: self._on_select(sc, payload),
            context_provider=None,
            prepare=_prep,
            allow_options_with_selection=True,
        )

    def _on_select(self, scope: str, cid):
        super()._on_select(scope, cid)

    def collect_entries(self) -> dict[MouseActionKey, dict[str, CommandPayload]]:
        key = self._current_key()
        scopes = self.collect_scopes()
        return {key: scopes} if scopes else {}

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

from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import json
from PySide6 import QtCore, QtGui, QtWidgets
from source.lang.manager import TranslatorMixin
from source.common.funcs import uipx
from .core import CommandMeta, CommandRegistry
from ..utils import show_error, CommandPayload
from .menu import (
    split_parts,
    is_sep_token,
    sep_path,
    is_section_token,
    section_parts,
    chain_providers,
    MenuHub,
)
from .state import CommandOptionStore


class CommandOptionsDialog(QtWidgets.QDialog, TranslatorMixin):
    def __init__(self, command_class: type, parent=None, execute_callback: Optional[Callable[[Dict[str, Any]], None]] = None, binding_mode: bool = False):
        super().__init__(parent)
        self.command_class = command_class
        self.widgets: Dict[str, QtWidgets.QWidget] = {}
        store = CommandOptionStore()
        payload = store.get(getattr(self.command_class.meta, "id", ""))
        self._initial = dict(payload.args or {})
        self._execute_callback = execute_callback
        self._did_save = False
        self._binding_mode = bool(binding_mode)
        self._setup_ui()

    def _setup_ui(self):
        self.setWindowTitle(self.t.tr(self.command_class.meta.display) + " " + self.t.tr("Options"))
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        for param in self.command_class.meta.params:
            label = QtWidgets.QLabel(self.t.tr(param.description or param.name))
            widget = self._create_widget(param)
            self.widgets[param.name] = widget
            form.addRow(label, widget)
        layout.addLayout(form)
        row = QtWidgets.QHBoxLayout()
        row.addStretch(1)
        if self._binding_mode:
            btn_save = QtWidgets.QPushButton("設定", self)
            btn_cancel = QtWidgets.QPushButton("キャンセル", self)
            btn_save.clicked.connect(self._on_save)
            btn_cancel.clicked.connect(self.reject)
            row.addWidget(btn_save)
            row.addWidget(btn_cancel)
        else:
            btn_save = QtWidgets.QPushButton("保存", self)
            btn_execute = QtWidgets.QPushButton("保存して実行", self)
            btn_cancel = QtWidgets.QPushButton("キャンセル", self)
            btn_execute.clicked.connect(self._on_execute)
            btn_save.clicked.connect(self._on_save)
            btn_cancel.clicked.connect(self.reject)
            row.addWidget(btn_save)
            row.addWidget(btn_execute)
            row.addWidget(btn_cancel)
        layout.addLayout(row)

    def _create_widget(self, param) -> QtWidgets.QWidget:
        if param.choices:
            combo = QtWidgets.QComboBox()
            for choice in param.choices:
                combo.addItem(str(choice), choice)
            base = self._initial.get(param.name, param.default)
            if base is not None:
                idx = combo.findData(base)
                if idx >= 0:
                    combo.setCurrentIndex(idx)
            return combo
        def make_bool():
            w = QtWidgets.QCheckBox()
            w.setChecked(bool(self._initial.get(param.name, param.default)))
            return w
        def make_int():
            w = QtWidgets.QSpinBox()
            if param.min_value is not None:
                w.setMinimum(param.min_value)
            if param.max_value is not None:
                w.setMaximum(param.max_value)
            w.setValue(int(self._initial.get(param.name, param.default) or 0))
            return w
        def make_float():
            w = QtWidgets.QDoubleSpinBox()
            if param.min_value is not None:
                w.setMinimum(param.min_value)
            if param.max_value is not None:
                w.setMaximum(param.max_value)
            w.setValue(float(self._initial.get(param.name, param.default) or 0.0))
            return w
        def make_str():
            w = QtWidgets.QLineEdit()
            w.setText(str(self._initial.get(param.name, param.default) or ""))
            return w
        factories = {bool: make_bool, int: make_int, float: make_float}
        f = factories.get(param.type, make_str)
        return f()

    def get_values(self) -> Dict[str, Any]:
        values = {}
        for param in self.command_class.meta.params:
            widget = self.widgets[param.name]
            if isinstance(widget, QtWidgets.QComboBox):
                values[param.name] = widget.currentData()
            elif isinstance(widget, QtWidgets.QCheckBox):
                values[param.name] = widget.isChecked()
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                values[param.name] = widget.value()
            elif isinstance(widget, QtWidgets.QLineEdit):
                text = widget.text()
                if param.type == int:
                    values[param.name] = int(text) if text else param.default
                elif param.type == float:
                    values[param.name] = float(text) if text else param.default
                else:
                    values[param.name] = text
        return values

    def did_save(self) -> bool:
        return bool(self._did_save)

    def _on_execute(self):
        values = self.get_values()
        try:
            if callable(self._execute_callback):
                self._execute_callback(values)
                self._did_save = True
                self.accept()
        except Exception:
            pass

    def _on_save(self):
        self._did_save = True
        self.accept()


class CommandMenuBuilder(TranslatorMixin):
    def __init__(self):
        self.registry = CommandRegistry()

    _check_states: Dict[str, bool] = {}

    def _wrap_provider_with_checked(self, provider: Optional[Callable[[], Dict[str, Any]]], checked: Optional[bool], meta: CommandMeta) -> Callable[[], Dict[str, Any]]:
        def _p():
            base = provider() if provider else {}
            if meta.checkable and checked is not None:
                base = dict(base)
                base["checked"] = bool(checked)
            return base
        return _p

    def _display_override(self, root_menu: QtWidgets.QMenu, cache: Dict[str, QtWidgets.QMenu], parent: QtWidgets.QWidget, target_menu: QtWidgets.QMenu, command_id: str, meta: CommandMeta, display_map: Optional[Dict[str, str]]):
        if display_map and command_id in display_map:
            disp = display_map.get(command_id) or self.t.tr(meta.display)
            dparts = split_parts(disp)
            if len(dparts) > 1:
                target_menu = self._get_or_create_submenu_chain(root_menu, cache, dparts[:-1], parent)
            text_override = dparts[-1] if dparts else self.t.tr(meta.display)
            return target_menu, text_override
        return target_menu, None

    def build(self, parent: QtWidgets.QWidget, command_names: List[str], context_provider: Optional[Callable[[], Dict[str, Any]]] = None, display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[Any], None]] = None) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        return self.build_into(menu, parent, command_names, context_provider, display_map, selection_callback)

    def build_into(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, command_names: List[str], context_provider: Optional[Callable[[], Dict[str, Any]]] = None, display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        menus_cache: Dict[str, QtWidgets.QMenu] = {}
        for name in command_names:
            if is_sep_token(name):
                parts = sep_path(str(name))
                if not parts:
                    menu.addSeparator()
                    continue
                target_menu = self._get_or_create_submenu_chain(menu, menus_cache, parts, parent)
                target_menu.addSeparator()
                continue
            if is_section_token(name):
                parts = section_parts(str(name))
                if not parts:
                    continue
                text = parts[-1]
                target_menu = menu if len(parts) == 1 else self._get_or_create_submenu_chain(menu, menus_cache, parts[:-1], parent)
                target_menu.addAction(self._create_section_action(parent, self.t.tr(text) or text))
                continue
            path_parts = split_parts(name)
            command_id = path_parts[-1] if len(path_parts) > 1 else name
            target_menu = menu if len(path_parts) <= 1 else self._get_or_create_submenu_chain(menu, menus_cache, path_parts[:-1], parent)
            command_class = self.registry.get_command(command_id)
            if not command_class:
                raise ValueError(f"Unknown command id: {command_id}")
            meta = command_class.meta
            target_menu, text_override = self._display_override(menu, menus_cache, parent, target_menu, command_id, meta, display_map)
            self._add_entry(target_menu, parent, command_id, meta, context_provider, bool(meta.has_options) if (allow_options_with_selection or not selection_callback) else False, text_override, selection_callback, allow_options_with_selection)
        return menu

    def _add_entry(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, name: str, meta: CommandMeta, context_provider: Optional[Callable[[], Dict[str, Any]]], with_options: bool, text_override: Optional[str], selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        container = self._create_row_widget(parent, text, meta.hotkey, meta.icon or None, with_options, None, (lambda: self._show_options_and_close_menu(name, parent, context_provider, menu, selection_callback if allow_options_with_selection else None)) if with_options else None, menu)
        widget_action.setDefaultWidget(container)
        if meta.checkable and selection_callback is None:
            widget_action.setCheckable(True)
            checked = self._get_checked(name, meta)
            widget_action.setChecked(checked)
            self._update_checkmark(container, checked)
            widget_action.toggled.connect(lambda state, n=name, c=container: self._on_toggled(n, c, state))
        if selection_callback is None:
            widget_action.triggered.connect(lambda checked=False, n=name, m=meta, p=context_provider: self._execute_and_close_menu(n, self._wrap_provider_with_checked(p, checked, m), menu))
        else:
            widget_action.triggered.connect(lambda checked=False, n=name: self._select_and_close_menu(n, menu, selection_callback))
        main_area = container.findChild(QtWidgets.QWidget, "rowMain")
        if main_area is not None:
            def _row_click_any(event):
                if event.button() == QtCore.Qt.LeftButton:
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click_any
        menu.addAction(widget_action)

    def _select_and_close_menu(self, name: str, menu: QtWidgets.QMenu, callback: Callable[[Any], None]):
        menu.close()
        try:
            payload = CommandPayload(name, {})
            callback(payload)
        except Exception:
            pass

    def _get_checked(self, name: str, meta: CommandMeta) -> bool:
        if name in self._check_states:
            return bool(self._check_states[name])
        return bool(meta.default_checked)

    def _on_toggled(self, name: str, container: QtWidgets.QWidget, state: bool):
        self._check_states[name] = bool(state)
        self._update_checkmark(container, state)

    def _update_checkmark(self, container: QtWidgets.QWidget, state: bool):
        lbl = container.findChild(QtWidgets.QLabel, "checkMark")
        if lbl is not None:
            lbl.setText("✓" if state else "")

    def _create_row_widget(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: Optional[str], has_options: bool, on_main_click: Optional[Callable[[], None]], on_options: Optional[Callable[[], None]], menu: QtWidgets.QMenu) -> QtWidgets.QWidget:
        w = CommandMenuRow(parent, text, hotkey, icon, has_options, menu)
        if on_main_click is not None:
            def _row_click(event):
                if event.button() == QtCore.Qt.LeftButton:
                    on_main_click()
            w.findChild(QtWidgets.QWidget, "rowMain").mouseReleaseEvent = _row_click
        if has_options and on_options is not None:
            btn = w.findChild(QtWidgets.QToolButton)
            if btn is not None:
                btn.clicked.connect(lambda: self._on_row_options(menu, on_options))
        return w

    def _on_row_options(self, menu: QtWidgets.QMenu, on_options: Callable[[], None]):
        menu.close()
        on_options()

    def _execute_and_close_menu(self, name: str, provider: Optional[Callable[[], Dict[str, Any]]], menu: QtWidgets.QMenu):
        menu.close()
        self._execute(name, provider)

    def _show_options_and_close_menu(self, command_name: str, parent: QtWidgets.QWidget, context_provider: Optional[Callable[[], Dict[str, Any]]], menu: QtWidgets.QMenu, selection_callback: Optional[Callable[[Any], None]] = None):
        menu.close()
        self._show_options(command_name, parent, context_provider, selection_callback)

    def _show_options(self, command_name: str, parent: QtWidgets.QWidget, context_provider: Optional[Callable[[], Dict[str, Any]]], selection_callback: Optional[Callable[[Any], None]] = None):
        command_class = self.registry.get_command(command_name)
        if not command_class:
            return
        def _exec_from_dialog(opts: Dict[str, Any]):
            context = context_provider() if context_provider else {}
            merged = dict(opts)
            merged.update(context)
            if getattr(command_class.meta, "checkable", False):
                merged["checked"] = bool(self._get_checked(command_name, command_class.meta))
            self._execute(command_name, lambda: merged)
        dialog = CommandOptionsDialog(command_class, parent, execute_callback=_exec_from_dialog, binding_mode=bool(selection_callback))
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.did_save():
            options = dialog.get_values()
            if not callable(selection_callback):
                try:
                    CommandOptionStore().set(command_name, options)
                except Exception:
                    pass
            if callable(selection_callback):
                try:
                    selection_callback(CommandPayload(command_name, options))
                except Exception:
                    selection_callback(CommandPayload(command_name, {}))
        else:
            if callable(selection_callback):
                selection_callback(CommandPayload(command_name, {}))

    def _execute(self, name: str, provider: Optional[Callable[[], Dict[str, Any]]] ):
        args: Dict[str, Any] = {}
        try:
            stored = CommandOptionStore().get(name)
            if stored:
                args.update(dict(stored.args or {}))
        except Exception:
            pass
        if provider:
            try:
                cur = provider() or {}
                if isinstance(cur, dict):
                    args.update(cur)
            except Exception:
                pass
        try:
            self.registry.execute(name, **args)
        except Exception as e:
            show_error(None, str(e), self.t.tr("Error"))

    def _get_or_create_submenu_chain(self, root_menu: QtWidgets.QMenu, cache: Dict[str, QtWidgets.QMenu], parts: List[str], parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        cur_path = ""
        current = root_menu
        for part in parts:
            cur_path = (cur_path + "/" + part).lstrip("/")
            if cur_path in cache:
                current = cache[cur_path]
                continue
            m = QtWidgets.QMenu(self.t.tr(part) or part, parent)
            current.addMenu(m)
            cache[cur_path] = m
            current = m
        return current

    def _create_section_action(self, parent: QtWidgets.QWidget, text: str) -> QtWidgets.QAction:
        a = QtWidgets.QWidgetAction(parent)
        w = QtWidgets.QWidget(parent)
        l = QtWidgets.QHBoxLayout(w)
        s = uipx(11)
        l.setContentsMargins(int(s * 1.6), int(s / 4), int(s * 1.6), 0)
        lbl = QtWidgets.QLabel(text)
        lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        lbl.setStyleSheet("color: gray; font-size: {}px;".format(s))
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
        l.addWidget(lbl)
        a.setDefaultWidget(w)
        return a


class CommandMenuRow(QtWidgets.QWidget):
    def __init__(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: Optional[str], has_options: bool, menu: QtWidgets.QMenu):
        super().__init__(parent)
        self.setObjectName("commandMenuRow")
        l = QtWidgets.QHBoxLayout(self)
        l.setContentsMargins(8, 2, 6, 2)
        l.setSpacing(0)
        self.setStyleSheet(
            "#commandMenuRow #rowMain{border:1px solid transparent;border-radius:4px;background:transparent;}"
            "#commandMenuRow #rowMain:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
            "#commandMenuRow QToolButton{border:1px solid transparent;border-radius:4px;background:transparent;}"
            "#commandMenuRow QToolButton:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
            "#commandMenuRow QLabel{background:transparent;}"
        )
        gutter_w = 22
        try:
            style = menu.style() if menu is not None else self.style()
            icon_sz = style.pixelMetric(QtWidgets.QStyle.PM_SmallIconSize, None, menu)
            frame_w = style.pixelMetric(QtWidgets.QStyle.PM_DefaultFrameWidth, None, menu)
            gutter_w = max(0, int(icon_sz + frame_w))
        except Exception:
            gutter_w = 22
        main = QtWidgets.QWidget(self)
        main.setObjectName("rowMain")
        main.setCursor(QtCore.Qt.PointingHandCursor)
        main.setAttribute(QtCore.Qt.WA_Hover, True)
        ml = QtWidgets.QHBoxLayout(main)
        ml.setContentsMargins(4, 2, 8, 2)
        ml.setSpacing(6)
        chk = QtWidgets.QLabel("", main)
        chk.setObjectName("checkMark")
        chk.setFixedWidth(gutter_w)
        chk.setAlignment(QtCore.Qt.AlignCenter)
        chk.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        ml.addWidget(chk, 0)
        if icon:
            il = QtWidgets.QLabel(main)
            qicon = QtGui.QIcon(icon) if isinstance(icon, str) else icon
            pm = qicon.pixmap(16, 16)
            il.setPixmap(pm)
            ml.addWidget(il, 0)
        tl = QtWidgets.QLabel(text, main)
        tl.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        ml.addWidget(tl, 1)
        ss = QtGui.QKeySequence(hotkey).toString() if hotkey else ""
        sl = QtWidgets.QLabel(ss, main)
        sl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        sl.setMinimumWidth(60 if hotkey else 0)
        ml.addWidget(sl, 0)
        l.addWidget(main, 1)
        if has_options:
            btn = QtWidgets.QToolButton(self)
            btn.setText("□")
            btn.setAutoRaise(True)
            btn.setFixedWidth(22)
            btn.setCursor(QtCore.Qt.PointingHandCursor)
            btn.setFocusPolicy(QtCore.Qt.NoFocus)
            l.addWidget(btn, 0)
        else:
            sp = QtWidgets.QWidget(self)
            sp.setFixedWidth(22)
            sp.setVisible(False)
            l.addWidget(sp, 0)


class MenuBuilder:
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None):
        self._menu = QtWidgets.QMenu(parent)
        self._builder = CommandMenuBuilder()
        self._hub = MenuHub()
        self._ctx = context_provider

    @property
    def menu(self) -> QtWidgets.QMenu:
        return self._menu

    def _add_names(self, dst: List[str], names: List[str], seen: set[str], after_rebase: bool) -> None:
        for n in names:
            if not (is_sep_token(n) or is_section_token(n)):
                if n in seen:
                    raise ValueError(f"Duplicate item after rebase: {n}" if after_rebase else f"Duplicate item: {n}")
                seen.add(n)
            dst.append(n)

    def _collect_folder(self, key: str, rebase_to: str, on_missing: str) -> List[str]:
        names = self._hub.collect_items_by_folder(key, rebase_to=rebase_to)
        if not names:
            raise ValueError(on_missing)
        return names

    def _flatten_for_use(self, n: str, base: str) -> str:
        if is_sep_token(n):
            sp = sep_path(str(n))
            if sp and sp[0] == base:
                sp = sp[1:]
                return "/".join(sp + ["-"]) if sp else "-"
            return n
        if is_section_token(n):
            parts = section_parts(str(n))
            if parts and parts[0] == base:
                head, label = parts[1:-1], parts[-1]
                return "/".join(head + [":" + label]) if head else ":" + label
            return n
        p = split_parts(str(n))
        if p and p[0] == base:
            p = p[1:]
            return "/".join(p)
        return n

    def _build_into(self, names: List[str], selection_callback: Optional[Callable[[Any], None]], context_provider: Optional[Callable[[], Dict[str, Any]]], allow_options_with_selection: bool) -> QtWidgets.QMenu:
        if names:
            ctx = chain_providers(self._ctx, context_provider)
            self._builder.build_into(self._menu, self._menu, names, context_provider=ctx, display_map=None, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection)
        return self._menu

    def build(self, items: List[str], selection_callback: Optional[Callable[[Any], None]] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        self._menu.clear()
        all_names: List[str] = []
        seen: set[str] = set()
        for it in items:
            if not it:
                continue
            if is_sep_token(it) or is_section_token(it):
                all_names.append(it)
                continue
            if "/" in it:
                parts = split_parts(it)
                if len(parts) >= 2:
                    orig_folder = parts[-1]
                    if self._hub.has_folder(orig_folder):
                        prefixes = self._hub.find_folder_prefixes(orig_folder)
                        if not prefixes:
                            raise ValueError(f"Unknown folder: {orig_folder}")
                        if len(prefixes) > 1:
                            raise ValueError(f"Ambiguous folder: {orig_folder}")
                        names = self._collect_folder(prefixes[0], rebase_to=it, on_missing=f"Unknown folder: {orig_folder}")
                        self._add_names(all_names, names, seen, after_rebase=True)
                        continue
                if self._hub.has_folder(it):
                    names = self._collect_folder(it, rebase_to=it, on_missing=f"Unknown folder: {it}")
                    self._add_names(all_names, names, seen, after_rebase=True)
                    continue
                path_cid = split_parts(it)[-1]
                if not self._hub.get_path_by_command_id(path_cid):
                    raise ValueError(f"Unknown command path or folder: {it}")
                self._add_names(all_names, [it], seen, after_rebase=False)
                continue
            p = self._hub.get_path_by_command_id(it)
            if p:
                self._add_names(all_names, [it], seen, after_rebase=False)
            else:
                prefixes = self._hub.find_folder_prefixes(it) if self._hub.has_folder(it) else []
                if len(prefixes) > 1:
                    raise ValueError(f"Ambiguous folder: {it}")
                if len(prefixes) == 1:
                    names = self._collect_folder(prefixes[0], rebase_to=it, on_missing=f"Unknown command or folder id: {it}")
                else:
                    names = self._collect_folder(it, rebase_to=it, on_missing=f"Unknown command or folder id: {it}")
                self._add_names(all_names, names, seen, after_rebase=True)
        return self._build_into(all_names, selection_callback, context_provider, allow_options_with_selection)

    def use(self, folder: str, context_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> QtWidgets.QMenu:
        self._menu.clear()
        s = (folder or "").strip("/")
        if not s:
            raise ValueError("Folder is required")
        if self._hub.get_path_by_command_id(s):
            raise ValueError(f"Command id is not allowed: {s}")
        names: List[str] = []
        if "/" in s:
            if not self._hub.has_folder(s):
                raise ValueError(f"Unknown folder: {s}")
            names = self._hub.collect_items_by_folder(s, rebase_to=s)
        else:
            if not self._hub.has_folder(s):
                prefs = self._hub.find_folder_prefixes(s)
                if not prefs:
                    raise ValueError(f"Unknown folder: {s}")
            prefs = self._hub.find_folder_prefixes(s)
            if len(prefs) > 1:
                raise ValueError(f"Ambiguous folder: {s}")
            pref = prefs[0] if prefs else s
            names = self._hub.collect_items_by_folder(pref, rebase_to=s)
        if not names:
            raise ValueError(f"No items under folder: {s}")
        names = [self._flatten_for_use(n, s) for n in names]
        self._build_into(names, None, context_provider, False)
        t = split_parts(s)
        self._menu.setTitle(t[-1] if t else s)
        return self._menu

    def build_all_roots(self, selection_callback: Optional[Callable[[Any], None]] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        roots: List[str] = []
        seen = set()
        for items in self._hub._menu_items.values():
            for s in items:
                if not isinstance(s, str) or not s or s == "---" or s.startswith(":"):
                    continue
                parts = [p for p in s.split("/") if p]
                if len(parts) < 2:
                    continue
                r = parts[0]
                if r in seen:
                    continue
                seen.add(r)
                roots.append(r)
        if not roots:
            raise ValueError("No top-level menus registered")
        return self.build(roots, selection_callback=selection_callback, context_provider=context_provider, allow_options_with_selection=allow_options_with_selection)

    def popup_all_roots(self, anchor: QtWidgets.QWidget, selection_callback: Callable[[Any], None], context_provider: Optional[Callable[[], Dict[str, Any]]] = None, prepare: Optional[Callable[[QtWidgets.QMenu], None]] = None, allow_options_with_selection: bool = False) -> None:
        menu = self.build_all_roots(selection_callback=selection_callback, context_provider=context_provider, allow_options_with_selection=allow_options_with_selection)
        if callable(prepare):
            try:
                prepare(menu)
            except Exception:
                pass
        pos = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        menu.exec(pos)

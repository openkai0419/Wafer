from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
import json
from decimal import Decimal
from PySide6 import QtCore, QtGui, QtWidgets
from source.lang.manager import TranslatorMixin
from source.common.funcs import uipx
from source.common.profiling import profiler
from .core import CommandMeta, CommandRegistry, COMMAND_MENU_MARKER
from .context import CommandContext
from source.common.errors import raise_error, show_warning
from .payload import CommandPayload
from .state import ActionGroupStateManager, log_error, log_warning
from .menu import split_parts, is_sep_token, sep_path, is_section_token, section_parts
from .maker import MenuMaker, MenuPlan
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
        btn_default = QtWidgets.QPushButton(self.t.tr("リセット"), self)
        btn_default.clicked.connect(self._on_reset_defaults)
        row.addWidget(btn_default)
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
            base = self._initial.get(param.name, param.default)
            v = int(base or 0)
            if param.min_value is not None:
                w.setMinimum(int(param.min_value))
            else:
                w.setMinimum(int(min(0, v)))
            if param.max_value is not None:
                w.setMaximum(int(param.max_value))
            else:
                w.setMaximum(int(self._infer_int_max(v)))
            w.setValue(v)
            w.setSingleStep(self._infer_int_step(v))
            return w
        
        def make_float():
            w = QtWidgets.QDoubleSpinBox()
            base = self._initial.get(param.name, param.default)
            v = float(base or 0.0)
            if param.min_value is not None:
                w.setMinimum(float(param.min_value))
            else:
                w.setMinimum(float(min(0.0, v)))
            if param.max_value is not None:
                w.setMaximum(float(param.max_value))
            else:
                w.setMaximum(float(self._infer_float_max(v)))
            w.setValue(v)
            step, decimals = self._infer_float_step(v)
            w.setDecimals(max(2, decimals))
            w.setSingleStep(step)
            return w
        
        def make_str():
            w = QtWidgets.QLineEdit()
            w.setText(str(self._initial.get(param.name, param.default) or ""))
            return w
        factories = {bool: make_bool, int: make_int, float: make_float}
        f = factories.get(param.type, make_str)
        return f()

    @staticmethod
    def _infer_int_step(v: int) -> int:
        a = abs(int(v))
        if a == 0:
            return 1
        p = 1
        while a % 10 == 0:
            p *= 10
            a //= 10
        return 1 if p <= 1 else max(1, int(p // 2))

    @staticmethod
    def _infer_int_max(v: int) -> int:
        a = abs(int(v))
        if a == 0:
            return 999
        sq = a * a
        digits = len(str(int(sq)))
        return max(999, (10 ** (digits + 1)) - 1)

    @staticmethod
    def _infer_float_step(v: float) -> tuple[float, int]:
        x = float(v)
        if x == 0.0:
            return 1.0, 0
        try:
            d = Decimal(str(round(x, 12))).normalize()
        except Exception:
            return 0.1, 1
        exp = d.as_tuple().exponent
        decimals = max(0, -int(exp))
        if decimals == 0:
            return 0.5, 1
        step = float(Decimal(1).scaleb(-decimals)) / 2.0
        return step, decimals + 1

    @staticmethod
    def _infer_float_max(v: float) -> float:
        a = abs(float(v))
        if a == 0.0:
            return 999.0
        sq = a * a
        digits = len(str(int(sq)))
        return float(max(999, (10 ** (digits + 1)) - 1))

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
        except Exception as e:
            log_error(f"Failed to execute command from dialog: {e}")

    def _on_reset_defaults(self):
        for param in self.command_class.meta.params:
            widget = self.widgets.get(param.name)
            if widget is None:
                continue
            v = param.default
            if isinstance(widget, QtWidgets.QComboBox):
                idx = widget.findData(v)
                if idx >= 0:
                    widget.setCurrentIndex(idx)
            elif isinstance(widget, QtWidgets.QCheckBox):
                widget.setChecked(bool(v))
            elif isinstance(widget, (QtWidgets.QSpinBox, QtWidgets.QDoubleSpinBox)):
                widget.setValue(v if v is not None else 0)
            elif isinstance(widget, QtWidgets.QLineEdit):
                widget.setText(str(v) if v is not None else "")

    def _on_save(self):
        self._did_save = True
        self.accept()


class CommandMenuBuilder(TranslatorMixin):
    _instance: Optional["CommandMenuBuilder"] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if CommandMenuBuilder._initialized:
            return
        self.registry = CommandRegistry()
        self.state_manager = ActionGroupStateManager()
        if not CommandMenuBuilder._observer_registered:
            self.state_manager.add_observer(CommandMenuBuilder._on_state_changed_observer)
            CommandMenuBuilder._observer_registered = True
        CommandMenuBuilder._initialized = True

    _check_states: Dict[str, bool] = {}
    _action_groups: Dict[str, QtGui.QActionGroup] = {}
    _observer_registered: bool = False

    @staticmethod
    def _on_state_changed_observer(group_name: str, command_id: str):
        state_manager = ActionGroupStateManager()
        members = state_manager.get_members(group_name)
        for member in members:
            CommandMenuBuilder._check_states[member] = state_manager.get_check_state(member)
        group = CommandMenuBuilder._action_groups.get(group_name)
        if group:
            for action in group.actions():
                if str(action.data()) == command_id:
                    if not action.isChecked():
                        action.setChecked(True)
    
    def _on_state_changed(self, group_name: str, command_id: str):
        members = self.state_manager.get_members(group_name)
        for member in members:
            self._check_states[member] = self.state_manager.get_check_state(member)
        group = self._action_groups.get(group_name)
        if group:
            for action in group.actions():
                if str(action.data()) == command_id:
                    if not action.isChecked():
                        action.setChecked(True)

    def _build_ctx(self, parent: Optional[QtWidgets.QWidget], cmd_id: str, args: Dict[str, Any]) -> Optional[CommandContext]:
        if parent is None:
            return None
        scope = parent.binding_scope() if hasattr(parent, "binding_scope") and callable(parent.binding_scope) else ""
        ctx = CommandContext.create(parent, scope, source="menu", event=None)
        try:
            if hasattr(parent, "extend_context") and callable(parent.extend_context):
                more = parent.extend_context(ctx, CommandPayload(cmd_id, dict(args or {})), event=None, key=None, source="menu")
                if isinstance(more, dict) and more:
                    ctx.merge(more)
        except Exception as e:
            show_warning(None, f"menu extend_context failed: {cmd_id}", exc=e)
        return ctx

    def _display_override(self, root_menu: QtWidgets.QMenu, cache: Dict[str, QtWidgets.QMenu], parent: QtWidgets.QWidget, target_menu: QtWidgets.QMenu, command_id: str, meta: CommandMeta, display_map: Optional[Dict[str, str]]):
        if display_map and command_id in display_map:
            disp = display_map.get(command_id) or self.t.tr(meta.display)
            dparts = split_parts(disp)
            if len(dparts) > 1:
                target_menu = self._get_or_create_submenu_chain(root_menu, cache, dparts[:-1], parent)
            text_override = dparts[-1] if dparts else self.t.tr(meta.display)
            return target_menu, text_override
        return target_menu, None

    @profiler.profile
    def build(self, parent: QtWidgets.QWidget, command_names: List[str], display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[Any], None]] = None) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        menu.setProperty(COMMAND_MENU_MARKER, True)
        self._install_hotkey_alignment(menu)
        return self.build_into(menu, parent, command_names, display_map, selection_callback)

    @profiler.profile
    def build_into(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, command_names: List[str], display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False, *, seed_ctx: Optional[CommandContext] = None) -> QtWidgets.QMenu:
        menus_cache: Dict[str, QtWidgets.QMenu] = {}
        action_groups: Dict[str, QtGui.QActionGroup] = {}
        group_defaults: Dict[str, tuple[str, CommandMeta]] = {}
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
            if meta.action_group and meta.checkable:
                self.state_manager.register_member(meta.action_group, command_id)
                if meta.default_checked:
                    group_defaults[meta.action_group] = (command_id, meta)
            self._add_entry(target_menu, parent, command_id, meta, bool(meta.has_options) if (allow_options_with_selection or not selection_callback) else False, text_override, selection_callback, allow_options_with_selection, action_groups, group_defaults, seed_ctx=seed_ctx)
        return menu

    def _install_hotkey_alignment(self, menu: QtWidgets.QMenu) -> None:
        if menu is None:
            return
        if bool(menu.property("__hotkey_align_installed__")):
            return
        menu.setProperty("__hotkey_align_installed__", True)
        menu.aboutToShow.connect(lambda m=menu: self._align_hotkeys_in_menu(m))

    def _align_hotkeys_in_menu(self, menu: QtWidgets.QMenu) -> None:
        try:
            rows = menu.findChildren(CommandMenuRow)
        except Exception:
            return
        if not rows:
            return
        labels: List[QtWidgets.QLabel] = []
        for r in rows:
            try:
                r.ensure_initialized()
            except Exception:
                continue
            lbl = getattr(r, "_hotkey_label", None)
            if isinstance(lbl, QtWidgets.QLabel) and lbl.text().strip():
                labels.append(lbl)
        if not labels:
            return
        try:
            maxw = 0
            for lbl in labels:
                fm = lbl.fontMetrics()
                w = int(fm.horizontalAdvance(lbl.text()))
                if w > maxw:
                    maxw = w
            maxw += int(uipx(12))
            for lbl in labels:
                lbl.setFixedWidth(maxw)
            menu.adjustSize()
        except Exception:
            return

    @profiler.profile
    def _add_entry(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, name: str, meta: CommandMeta, with_options: bool, text_override: Optional[str], selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False, action_groups: Optional[Dict[str, QtGui.QActionGroup]] = None, group_defaults: Optional[Dict[str, tuple[str, CommandMeta]]] = None, *, seed_ctx: Optional[CommandContext] = None):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        hotkey = self._resolve_hotkey(parent, name)
        container = self._create_row_widget(parent, text, hotkey, meta.icon or None, with_options, None, (lambda: self._show_options_and_close_menu(name, parent, menu, selection_callback if allow_options_with_selection else None, seed_ctx=seed_ctx)) if with_options else None, menu)
        widget_action.setDefaultWidget(container)
        if meta.checkable and selection_callback is None:
            widget_action.setCheckable(True)
            if meta.action_group:
                checked = self._get_checked_for_group(name, meta.action_group, meta, group_defaults)
            else:
                checked = self._get_checked(name, meta)
            widget_action.setChecked(checked)
            self._update_checkmark(container, checked)
            if meta.action_group:
                if action_groups is not None:
                    if meta.action_group not in action_groups:
                        group = QtGui.QActionGroup(parent)
                        group.setExclusive(True)
                        action_groups[meta.action_group] = group
                        self._action_groups[meta.action_group] = group
                    action_groups[meta.action_group].addAction(widget_action)
                widget_action.toggled.connect(lambda state, n=name, c=container, g=meta.action_group: self._on_radio_toggled(n, c, state, g))
            else:
                widget_action.toggled.connect(lambda state, n=name, c=container: self._on_toggled(n, c, state))
        if selection_callback is None:
            widget_action.triggered.connect(lambda checked=False, n=name, m=meta, p=parent, s=seed_ctx: self._execute_and_close_menu(n, p, menu, checked if getattr(m, "checkable", False) else None, seed_ctx=s))
        else:
            widget_action.triggered.connect(lambda checked=False, n=name: self._select_and_close_menu(n, menu, selection_callback))
        main_area = container.findChild(QtWidgets.QWidget, "rowMain")
        if main_area is not None:
            def _row_click_any(event):
                if event.button() == QtCore.Qt.LeftButton:
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click_any
        menu.addAction(widget_action)

    def _resolve_hotkey(self, parent: QtWidgets.QWidget, command_id: str) -> str:
        try:
            from ..binding.manager import BindingManager
            from ..binding.key.shortcutmanager import ShortcutManager
        except Exception:
            return ""

        if not command_id:
            return ""
        bm = BindingManager.instance()
        bw = bm.find_registered_ancestor(parent) if parent is not None else None
        if bw is None:
            return ""
        try:
            sm = ShortcutManager()
            for k, payload in (sm.get_bindings(bw) or {}).items():
                if isinstance(payload, CommandPayload) and payload.id == command_id and k:
                    return str(k).strip()
            return ""
        except Exception as e:
            show_warning(parent, "resolve hotkey failed", exc=e)
            return ""

    def _select_and_close_menu(self, name: str, menu: QtWidgets.QMenu, callback: Callable[[Any], None]):
        menu.close()
        try:
            payload = CommandPayload(name, {})
            callback(payload)
        except Exception as e:
            log_error(f"Failed to execute selection callback for '{name}': {e}")

    @profiler.profile
    def _get_checked(self, name: str, meta: CommandMeta) -> bool:
        if name in self._check_states:
            return self._check_states[name]
        stored = CommandOptionStore().get(name)
        args = getattr(stored, "args", None)
        if isinstance(args, dict) and "checked" in args:
            return bool(args["checked"])
        return meta.default_checked

    @profiler.profile
    def _get_checked_for_group(self, name: str, group_name: str, meta: CommandMeta, group_defaults: Optional[Dict[str, tuple[str, CommandMeta]]] = None) -> bool:
        current = self.state_manager.get_current(group_name)
        if current:
            return current == name
        if group_defaults and group_name in group_defaults:
            return group_defaults[group_name][0] == name
        return meta.default_checked

    def _on_toggled(self, name: str, container: QtWidgets.QWidget, state: bool):
        self._check_states[name] = state
        self._update_checkmark(container, state)
        store = CommandOptionStore()
        cur = store.get(name)
        opts = getattr(cur, "args", None)
        if not isinstance(opts, dict):
            opts = {}
        opts["checked"] = state
        store.set(name, opts)
        if not store.commit():
            log_warning(f"Failed to save command options: {name}")

    def _on_radio_toggled(self, name: str, container: QtWidgets.QWidget, state: bool, group_name: str):
        self._on_toggled(name, container, state)
        if state:
            self.state_manager.set_current(group_name, name)

    def cycle_action_group(self, group_name: str) -> Optional[str]:
        result = self.state_manager.cycle(group_name)
        if not result:
            return None
        group = self._action_groups.get(group_name)
        if group:
            result_action = next((a for a in group.actions() if str(a.data()) == result), None)
            if result_action:
                result_action.trigger()
        else:
            try:
                ctx = CommandContext.create(None, "*", source="cycle", event=None)
                ctx.put("checked", True)
                self.registry.execute(result, ctx=ctx)
            except Exception as e:
                log_error(f"Failed to execute command: {e}")
        return result

    def get_action_group_current(self, group_name: str) -> Optional[str]:
        result = self.state_manager.get_current(group_name)
        if result:
            return result
        group = self._action_groups.get(group_name)
        if group:
            result_action = next((a for a in group.actions() if a.isChecked()), None)
            if result_action:
                result = str(result_action.data() or "")
                self.state_manager.set_current(group_name, result, save=False)
                return result
        return self.state_manager.find_default(group_name, self.registry)

    def set_action_group_current(self, group_name: str, command_id: str) -> None:
        self.state_manager.set_current(group_name, command_id)
        group = self._action_groups.get(group_name)
        if group:
            for action in group.actions():
                if str(action.data()) == command_id:
                    action.blockSignals(True)
                    action.setChecked(True)
                    action.blockSignals(False)
                    break

    def _update_checkmark(self, container: QtWidgets.QWidget, state: bool):
        lbl = container.findChild(QtWidgets.QLabel, "checkMark")
        if lbl is not None:
            lbl.setText("✓" if state else "")

    @profiler.profile
    def _create_row_widget(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: Optional[str], has_options: bool, on_main_click: Optional[Callable[[], None]], on_options: Optional[Callable[[], None]], menu: QtWidgets.QMenu) -> QtWidgets.QWidget:
        w = CommandMenuRow(parent, text, hotkey, icon, has_options, menu)
        w._on_main_click = on_main_click
        w._on_options_callback = (lambda: self._on_row_options(menu, on_options)) if on_options is not None else None
        if on_main_click is not None:
            main_area = w.findChild(QtWidgets.QWidget, "rowMain")
            if main_area is not None:
                def _row_click(event):
                    if event.button() == QtCore.Qt.LeftButton:
                        on_main_click()
                main_area.mouseReleaseEvent = _row_click
        if w._inited and w._has_options and w._on_options_callback is not None:
            btn = w.findChild(QtWidgets.QToolButton)
            if btn is not None:
                btn.clicked.connect(w._on_options_callback)
        return w

    def _on_row_options(self, menu: QtWidgets.QMenu, on_options: Callable[[], None]):
        menu.close()
        on_options()

    def _execute_and_close_menu(self, name: str, parent: Optional[QtWidgets.QWidget], menu: QtWidgets.QMenu, checked: Optional[bool] = None, *, seed_ctx: Optional[CommandContext] = None):
        menu.close()
        self._execute(name, parent, checked, seed_ctx=seed_ctx)

    def _show_options_and_close_menu(self, command_name: str, parent: QtWidgets.QWidget, menu: QtWidgets.QMenu, selection_callback: Optional[Callable[[Any], None]] = None, *, seed_ctx: Optional[CommandContext] = None):
        menu.close()
        self._show_options(command_name, parent, selection_callback, seed_ctx=seed_ctx)

    @profiler.profile
    def _show_options(self, command_name: str, parent: QtWidgets.QWidget, selection_callback: Optional[Callable[[Any], None]] = None, *, seed_ctx: Optional[CommandContext] = None):
        command_class = self.registry.get_command(command_name)
        if not command_class:
            return
        def _exec_from_dialog(opts: Dict[str, Any]):
            merged = dict(opts)
            ctx = self._build_ctx(parent, command_name, merged)
            if ctx is not None and getattr(command_class.meta, "checkable", False):
                ctx.put("checked", bool(self._get_checked(command_name, command_class.meta)))
            if ctx is None:
                ctx = CommandContext.create(parent, "*", source="menu", event=None, seed=seed_ctx)
            else:
                CommandContext.merge_seed(ctx, seed_ctx)
            self.registry.execute(command_name, ctx=ctx, **merged)
        dialog = CommandOptionsDialog(command_class, parent, execute_callback=_exec_from_dialog, binding_mode=bool(selection_callback))
        if dialog.exec() == QtWidgets.QDialog.Accepted and dialog.did_save():
            options = dialog.get_values()
            if not callable(selection_callback):
                store = CommandOptionStore()
                store.set(command_name, options)
                if not store.commit():
                    log_warning(f"Failed to save command options: {command_name}")
            if callable(selection_callback):
                try:
                    selection_callback(CommandPayload(command_name, options))
                except Exception as e:
                    log_error(f"Failed to call selection callback for '{command_name}': {e}")
        else:
            if not callable(selection_callback):
                return
            return

    @profiler.profile
    def _execute(self, name: str, parent: Optional[QtWidgets.QWidget] = None, checked: Optional[bool] = None, *, seed_ctx: Optional[CommandContext] = None):
        args: Dict[str, Any] = {}
        stored = CommandOptionStore().get(name)
        sargs = getattr(stored, "args", None)
        if isinstance(sargs, dict) and sargs:
            args.update(dict(sargs))
        try:
            if parent is not None:
                ctx = self._build_ctx(parent, name, args)
                if ctx is None:
                    ctx = CommandContext.create(parent, "*", source="menu", event=None, seed=seed_ctx)
                else:
                    CommandContext.merge_seed(ctx, seed_ctx)
                if checked is not None:
                    ctx.put("checked", bool(checked))
                self.registry.execute(name, ctx=ctx, **args)
            else:
                ctx = CommandContext.create(None, "*", source="menu", event=None, seed=seed_ctx)
                if checked is not None:
                    ctx.put("checked", bool(checked))
                self.registry.execute(name, ctx=ctx, **args)
        except Exception as e:
            log_error(f"Failed to execute command '{name}': {e}")
            raise_error(None, str(e), self.t.tr("Error"))

    @profiler.profile
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
            self._install_hotkey_alignment(m)
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
    _shared_style: Optional[str] = None

    @profiler.profile
    def __init__(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: Optional[str], has_options: bool, menu: QtWidgets.QMenu):
        super().__init__(parent)
        self.setObjectName("commandMenuRow")
        self._inited = False
        self._icon = icon
        self._hotkey = hotkey
        self._text = text
        self._has_options = bool(has_options)
        self._menu_ref = menu
        self._on_main_click: Optional[Callable[[], None]] = None
        self._on_options_callback: Optional[Callable[[], None]] = None

        l = QtWidgets.QHBoxLayout(self)
        l.setContentsMargins(uipx(8), uipx(2), uipx(6), uipx(2))
        l.setSpacing(0)

        # Minimal skeleton: main area with check mark and text only.
        self._main = QtWidgets.QWidget(self)
        self._main.setObjectName("rowMain")
        self._main.setCursor(QtCore.Qt.PointingHandCursor)
        self._main.setAttribute(QtCore.Qt.WA_Hover, True)
        self._ml = QtWidgets.QHBoxLayout(self._main)
        self._ml.setContentsMargins(uipx(4), uipx(2), uipx(8), uipx(2))
        self._ml.setSpacing(uipx(6))

        self._chk = QtWidgets.QLabel("", self._main)
        self._chk.setObjectName("checkMark")
        self._chk.setFixedWidth(uipx(1))
        self._chk.setAlignment(QtCore.Qt.AlignCenter)
        self._chk.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._ml.addWidget(self._chk, 0)

        self._tl = QtWidgets.QLabel(self._text, self._main)
        self._tl.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        self._ml.addWidget(self._tl, 1)

        self._inner_spacer = QtWidgets.QWidget(self._main)
        self._inner_spacer.setFixedWidth(0)
        self._inner_spacer.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        self._ml.addWidget(self._inner_spacer, 0)

        l.addWidget(self._main, 1)

        self._options_spacer = QtWidgets.QWidget(self)
        self._options_spacer.setFixedWidth(uipx(22))
        self._options_spacer.setVisible(False)
        l.addWidget(self._options_spacer, 0)

        self._icon_label: Optional[QtWidgets.QLabel] = None
        self._hotkey_label: Optional[QtWidgets.QLabel] = None
        self._options_btn: Optional[QtWidgets.QToolButton] = None

        self._deferred_timer_started = False

    def showEvent(self, ev):
        super().showEvent(ev)
        if not self._inited and not self._deferred_timer_started:
            self._deferred_timer_started = True
            QtCore.QTimer.singleShot(0, self.ensure_initialized)

    def ensure_initialized(self):
        if self._inited:
            return
        if CommandMenuRow._shared_style is None:
            CommandMenuRow._shared_style = (
                "#commandMenuRow #rowMain{border:1px solid transparent;border-radius:4px;background:transparent;}"
                "#commandMenuRow #rowMain:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
                "#commandMenuRow QToolButton{border:1px solid transparent;border-radius:4px;background:transparent;}"
                "#commandMenuRow QToolButton:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}" 
                "#commandMenuRow QLabel{background:transparent;}"
            )
        try:
            self.setStyleSheet(CommandMenuRow._shared_style)
        except Exception as e:
            show_warning(self, "CommandMenuRow.setStyleSheet failed", exc=e)

        gutter_w = self._compute_gutter()
        try:
            self._chk.setFixedWidth(gutter_w)
        except Exception as e:
            show_warning(self, "CommandMenuRow._chk.setFixedWidth failed", exc=e)

        if self._icon and self._icon_label is None:
            try:
                il = QtWidgets.QLabel(self._main)
                qicon = QtGui.QIcon(self._icon) if isinstance(self._icon, str) else self._icon
                sz = uipx(16)
                pm = qicon.pixmap(sz, sz)
                il.setPixmap(pm)
                self._ml.insertWidget(1, il, 0)
                self._icon_label = il
            except Exception as e:
                show_warning(self, "CommandMenuRow icon setup failed", exc=e)

        if self._hotkey and self._hotkey_label is None:
            try:
                raw = str(self._hotkey)
                ss_parsed = QtGui.QKeySequence(raw).toString() if raw else ""
                ss = (ss_parsed or raw).strip()
                if not ss:
                    return
                sl = QtWidgets.QLabel(ss, self._main)
                sl.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
                self._ml.addWidget(sl, 0)
                self._hotkey_label = sl
            except Exception as e:
                show_warning(self, "CommandMenuRow hotkey label setup failed", exc=e)

        if self._has_options and self._options_btn is None:
            try:
                self._ml.removeWidget(self._inner_spacer)
                self._inner_spacer.deleteLater()
                
                top_layout = self.layout()
                idx = None
                for i in range(top_layout.count()):
                    w = top_layout.itemAt(i).widget()
                    if w is self._options_spacer:
                        idx = i
                        break
                if idx is not None:
                    top_layout.removeWidget(self._options_spacer)
                    self._options_spacer.deleteLater()
                    btn = QtWidgets.QToolButton(self)
                    btn.setText("□")
                    btn.setAutoRaise(True)
                    btn.setFixedWidth(uipx(22))
                    btn.setCursor(QtCore.Qt.PointingHandCursor)
                    btn.setFocusPolicy(QtCore.Qt.NoFocus)
                    top_layout.insertWidget(idx, btn, 0)
                    self._options_btn = btn
                    if self._on_options_callback is not None:
                        try:
                            self._options_btn.clicked.connect(self._on_options_callback)
                        except Exception as e:
                            show_warning(self, "CommandMenuRow options callback connect failed", exc=e)
            except Exception as e:
                show_warning(self, "CommandMenuRow options button setup failed", exc=e)

        if self._on_main_click is not None:
            try:
                def _row_click(event):
                    if event.button() == QtCore.Qt.LeftButton:
                        try:
                            self._on_main_click()
                        except Exception as e:
                            show_warning(self, "CommandMenuRow on_main_click failed", exc=e)
                self._main.mouseReleaseEvent = _row_click
            except Exception as e:
                show_warning(self, "CommandMenuRow mouseReleaseEvent hook failed", exc=e)

        self._inited = True

    def _compute_gutter(self) -> int:
        try:
            style = self._menu_ref.style() if self._menu_ref is not None else self.style()
            icon_sz = style.pixelMetric(QtWidgets.QStyle.PM_SmallIconSize, None, self._menu_ref)
            return max(0, min(int(icon_sz), int(uipx(22))))
        except Exception as e:
            show_warning(self, "CommandMenuRow gutter metric lookup failed", exc=e)
            return 22


class MenuBuilder:
    def __init__(self, maker: MenuMaker, parent: Optional[QtWidgets.QWidget] = None, *, seed_ctx: Optional[CommandContext] = None):
        self._menu = QtWidgets.QMenu(parent)
        self._menu.setProperty(COMMAND_MENU_MARKER, True)
        self._ctx_parent = parent
        self._builder = CommandMenuBuilder()
        self._builder._install_hotkey_alignment(self._menu)
        self._seed_ctx = seed_ctx
        self._maker = maker

    @property
    def menu(self) -> QtWidgets.QMenu:
        return self._menu

    def _build_into(self, names: List[str], selection_callback: Optional[Callable[[Any], None]], allow_options_with_selection: bool) -> QtWidgets.QMenu:
        if names:
            parent = self._ctx_parent
            if parent is None:
                pw = getattr(self._menu, "parentWidget", None)
                if callable(pw):
                    try:
                        parent = pw()
                    except Exception as e:
                        show_warning(self._menu, "MenuBuilder parentWidget lookup failed", exc=e)
                        parent = None
            if parent is None:
                parent = self._menu
            self._builder.build_into(self._menu, parent, names, display_map=None, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection, seed_ctx=self._seed_ctx)
        return self._menu

    @profiler.profile
    def build(self, plan: MenuPlan, selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        self._menu.clear()
        if plan is None:
            return self._menu
        return self._build_into(plan.resolve_tokens(), selection_callback, allow_options_with_selection)

    @profiler.profile
    def use(self, folder: str) -> QtWidgets.QMenu:
        plan = self._maker.use(folder)
        return self.build(plan)

    def build_all_roots(self, selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        plan = self._maker.all_roots()
        return self.build(plan, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection)

    def build_names(self, names: List[str], selection_callback: Optional[Callable[[Any], None]] = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        self._menu.clear()
        return self._build_into(list(names or []), selection_callback, allow_options_with_selection)

    def _popup(self, anchor: QtWidgets.QWidget, build_fn: Callable[[], QtWidgets.QMenu], context_provider: Optional[Callable[[], Any]], prepare: Optional[Callable[[QtWidgets.QMenu], None]]) -> None:
        prev_seed = self._seed_ctx
        if callable(context_provider):
            try:
                v = context_provider()
                if isinstance(v, CommandContext):
                    self._seed_ctx = v
                elif isinstance(v, dict):
                    self._seed_ctx = CommandContext.create(None, "*", source="menu.popup", event=None, extras=dict(v))
            except Exception as e:
                show_warning(anchor, "context_provider failed", exc=e)
        menu = build_fn()
        if callable(prepare):
            try:
                prepare(menu)
            except Exception as e:
                show_warning(anchor, "prepare(menu) failed", exc=e)
        pos = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        menu.exec(pos)
        self._seed_ctx = prev_seed

    def popup_names(
        self,
        anchor: QtWidgets.QWidget,
        names: List[str],
        selection_callback: Callable[[Any], None],
        context_provider: Optional[Callable[[], Any]] = None,
        prepare: Optional[Callable[[QtWidgets.QMenu], None]] = None,
        allow_options_with_selection: bool = False,
    ) -> None:
        self._popup(anchor, lambda: self.build_names(names, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection), context_provider, prepare)

    def popup_all_roots(self, anchor: QtWidgets.QWidget, selection_callback: Callable[[Any], None], context_provider: Optional[Callable[[], Any]] = None, prepare: Optional[Callable[[QtWidgets.QMenu], None]] = None, allow_options_with_selection: bool = False) -> None:
        self._popup(anchor, lambda: self.build_all_roots(selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection), context_provider, prepare)

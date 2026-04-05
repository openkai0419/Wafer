from __future__ import annotations
from typing import Any, Callable
from PySide6 import QtCore, QtGui, QtWidgets
from ...lang.manager import TranslatorMixin
from ....utils.profiling import profiler
from .core import CommandMeta, CommandRegistry, COMMAND_MENU_MARKER
from .context import CommandContext
from ....utils.logs import AppLogger
from .payload import CommandPayload
from .state import ActionGroupStateManager, CommandOptionStore
from .menu import split_menu_path, is_sep_token, sep_path, is_section_token, section_parts
from .maker import MenuMaker, MenuPlan
from .menu_item import CommandMenuRow
from .option_dialog import CommandOptionsDialog


class StickyMenu(QtWidgets.QMenu):
    _STICKY_DURATION_MS = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._sticky_action: QtGui.QAction | None = None
        self._sticky_timer = QtCore.QTimer(self)
        self._sticky_timer.setSingleShot(True)
        self._sticky_timer.timeout.connect(self._release_sticky)

    def _release_sticky(self):
        self._sticky_action = None

    def mouseReleaseEvent(self, event):
        action = self.actionAt(event.position().toPoint())
        if action and action.menu():
            if self._sticky_action == action:
                self._sticky_action = None
                self._sticky_timer.stop()
            else:
                self._sticky_action = action
                self._sticky_timer.start(self._STICKY_DURATION_MS)
            return
        self._sticky_action = None
        self._sticky_timer.stop()
        super().mouseReleaseEvent(event)

    def event(self, e):
        if self._sticky_action is not None and e.type() == QtCore.QEvent.MouseMove:
            hover_action = self.actionAt(e.position().toPoint())
            if hover_action is not None and hover_action.menu() is not None and hover_action != self._sticky_action:
                return True
        return super().event(e)

    def hideEvent(self, event):
        self._sticky_action = None
        self._sticky_timer.stop()
        super().hideEvent(event)


class CommandMenuBuilder(TranslatorMixin):
    _instance: "CommandMenuBuilder" | None = None
    _initialized: bool = False

    @classmethod
    def instance(cls) -> "CommandMenuBuilder":
        if cls._instance is None:
            inst = object.__new__(cls)
            inst.__init__()
            cls._instance = inst
        return cls._instance

    def __init__(self):
        if CommandMenuBuilder._initialized:
            return
        self.registry = CommandRegistry.instance()
        self.state_manager = ActionGroupStateManager.instance()
        self._active_seed_ctx: CommandContext | None = None
        if not CommandMenuBuilder._observer_registered:
            self.state_manager.add_observer(CommandMenuBuilder._on_state_changed_observer)
            CommandMenuBuilder._observer_registered = True
        CommandMenuBuilder._initialized = True

    _check_states: dict[str, bool] = {}
    _action_groups: dict[str, QtGui.QActionGroup] = {}
    _observer_registered: bool = False
    _menu_cache: dict[tuple, QtWidgets.QMenu] = {}

    @staticmethod
    def _on_state_changed_observer(group_name: str, command_id: str):
        state_manager = ActionGroupStateManager.instance()
        members = state_manager.get_members(group_name)
        for member in members:
            CommandMenuBuilder._check_states[member] = state_manager.get_check_state(member)
        group = CommandMenuBuilder._action_groups.get(group_name)
        if group:
            for action in group.actions():
                if str(action.data()) == command_id:
                    if not action.isChecked():
                        action.setChecked(True)

    def _build_ctx(self, parent: QtWidgets.QWidget | None, cmd_id: str, args: dict[str, Any]) -> CommandContext | None:
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
            AppLogger.warning(f"menu extend_context failed: {cmd_id}", exc=e)
        return ctx

    def _display_override(self, root_menu: QtWidgets.QMenu, cache: dict[str, QtWidgets.QMenu], parent: QtWidgets.QWidget, target_menu: QtWidgets.QMenu, command_id: str, meta: CommandMeta, display_map: dict[str, str] | None):
        if display_map and command_id in display_map:
            disp = display_map.get(command_id) or self.t.tr(meta.display)
            dparts = split_menu_path(disp)
            if len(dparts) > 1:
                target_menu = self._get_or_create_submenu_chain(root_menu, cache, dparts[:-1], parent)
            text_override = dparts[-1] if dparts else self.t.tr(meta.display)
            return target_menu, text_override
        return target_menu, None

    @profiler.profile
    def build(self, parent: QtWidgets.QWidget, command_names: list[str], display_map: dict[str, str] | None = None, selection_callback: Callable[[Any], None] | None = None) -> QtWidgets.QMenu:
        menu = StickyMenu(parent)
        menu.setProperty(COMMAND_MENU_MARKER, True)
        self._install_hotkey_alignment(menu)
        return self.build_into(menu, parent, command_names, display_map, selection_callback)

    @profiler.profile
    def build_into(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, command_names: list[str], display_map: dict[str, str] | None = None, selection_callback: Callable[[Any], None] | None = None, allow_options_with_selection: bool = False, *, seed_ctx: CommandContext | None = None) -> QtWidgets.QMenu:
        menus_cache: dict[str, QtWidgets.QMenu] = {}
        action_groups: dict[str, QtGui.QActionGroup] = {}
        group_defaults: dict[str, tuple[str, CommandMeta]] = {}
        hotkey_map = self._resolve_hotkeys_batch(parent)
        self._active_seed_ctx = seed_ctx
        checkable_tracker: list[tuple] = []
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
            path_parts = split_menu_path(name)
            command_id = path_parts[-1] if len(path_parts) > 1 else name
            target_menu = menu if len(path_parts) <= 1 else self._get_or_create_submenu_chain(menu, menus_cache, path_parts[:-1], parent)
            command_class = self.registry.get_command(command_id)
            if not command_class:
                AppLogger.warning(f"Skipping unknown command id in menu: {command_id}")
                continue
            meta = command_class.meta
            target_menu, text_override = self._display_override(menu, menus_cache, parent, target_menu, command_id, meta, display_map)
            if meta.action_group and meta.checkable:
                self.state_manager.register_member(meta.action_group, command_id)
                if meta.default_checked:
                    group_defaults[meta.action_group] = (command_id, meta)
            self._add_entry(target_menu, parent, command_id, meta, bool(meta.has_options) if (allow_options_with_selection or not selection_callback) else False, text_override, selection_callback, allow_options_with_selection, action_groups, group_defaults, hotkey_map=hotkey_map, checkable_tracker=checkable_tracker)
        for gname, (default_id, _) in group_defaults.items():
            self.state_manager.initialize_default(gname, default_id)
        menu.setProperty("__checkable_tracker__", checkable_tracker)
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
        labels: list[QtWidgets.QLabel] = []
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
            maxw += CommandMenuRow._ensure_px()["pad"]
            for lbl in labels:
                lbl.setFixedWidth(maxw)
            menu.adjustSize()
        except Exception:
            return

    @profiler.profile
    def _add_entry(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, name: str, meta: CommandMeta, with_options: bool, text_override: str | None, selection_callback: Callable[[Any], None] | None = None, allow_options_with_selection: bool = False, action_groups: dict[str, QtGui.QActionGroup] | None = None, group_defaults: dict[str, tuple[str, CommandMeta]] | None = None, hotkey_map: dict[str, str] | None = None, checkable_tracker: list[tuple] | None = None):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        hotkey = (hotkey_map or {}).get(name, "")
        container = self._create_row_widget(parent, text, hotkey, meta.icon or None, with_options, None, (lambda: self._show_options_and_close_menu(name, parent, menu, selection_callback if allow_options_with_selection else None)) if with_options else None, menu)
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
                if checkable_tracker is not None:
                    checkable_tracker.append((widget_action, container, name, meta, True))
            else:
                widget_action.toggled.connect(lambda state, n=name, c=container: self._on_toggled(n, c, state))
                if checkable_tracker is not None:
                    checkable_tracker.append((widget_action, container, name, meta, False))
        if selection_callback is None:
            widget_action.triggered.connect(lambda checked=False, n=name, m=meta, p=parent: self._execute_and_close_menu(n, p, menu, checked if getattr(m, "checkable", False) else None))
        else:
            widget_action.triggered.connect(lambda checked=False, n=name: self._select_and_close_menu(n, menu, selection_callback))
        main_area = container._main
        if main_area is not None:
            def _row_click_any(event):
                if event.button() == QtCore.Qt.LeftButton:
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click_any
        menu.addAction(widget_action)

    def _resolve_hotkeys_batch(self, parent: QtWidgets.QWidget) -> dict[str, str]:
        try:
            from ..binding.manager import BindingManager
            from ..binding.key.shortcutmanager import ShortcutManager
        except Exception:
            return {}
        if parent is None:
            return {}
        bm = BindingManager.instance()
        bw = bm.find_registered_ancestor(parent)
        if bw is None:
            return {}
        try:
            sm = ShortcutManager()
            result: dict[str, str] = {}
            for k, payload in (sm.get_bindings(bw) or {}).items():
                if isinstance(payload, CommandPayload) and payload.id and k:
                    key_str = str(k).strip()
                    if key_str and payload.id not in result:
                        result[payload.id] = key_str
            return result
        except Exception as e:
            AppLogger.warning("resolve hotkeys batch failed", exc=e)
            return {}

    def _select_and_close_menu(self, name: str, menu: QtWidgets.QMenu, callback: Callable[[Any], None]):
        menu.close()
        try:
            payload = CommandPayload(name, {})
            callback(payload)
        except Exception as e:
            AppLogger.warning(f"Failed to execute selection callback for '{name}': {e}")

    @profiler.profile
    def _get_checked(self, name: str, meta: CommandMeta) -> bool:
        stored = CommandOptionStore.instance().get(name)
        args = getattr(stored, "args", None)
        if isinstance(args, dict) and "checked" in args:
            return bool(args["checked"])
        if name in self._check_states:
            return self._check_states[name]
        return meta.default_checked

    @profiler.profile
    def _get_checked_for_group(self, name: str, group_name: str, meta: CommandMeta, group_defaults: dict[str, tuple[str, CommandMeta]] | None = None) -> bool:
        current = self.state_manager.get_current(group_name)
        if current:
            return current == name
        if group_defaults and group_name in group_defaults:
            return group_defaults[group_name][0] == name
        return meta.default_checked

    def _on_toggled(self, name: str, container: QtWidgets.QWidget, state: bool):
        self._update_checkmark(container, state)
        self.set_checked(name, state)

    def set_checked(self, name: str, state: bool):
        self._check_states[name] = state
        store = CommandOptionStore.instance()
        cur = store.get(name)
        opts = getattr(cur, "args", None)
        if not isinstance(opts, dict):
            opts = {}
        opts["checked"] = state
        store.set(name, opts)
        if not store.commit():
            AppLogger.warning(f"Failed to save command options: {name}")

    def _on_radio_toggled(self, name: str, container: QtWidgets.QWidget, state: bool, group_name: str):
        self._on_toggled(name, container, state)
        if state:
            self.state_manager.set_current(group_name, name)

    def cycle_action_group(self, group_name: str) -> str | None:
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
                AppLogger.warning(f"Failed to execute command: {e}")
        return result

    def get_action_group_current(self, group_name: str) -> str | None:
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

    def set_action_group_current(self, group_name: str, command_id: str, *, save: bool = True) -> None:
        self.state_manager.set_current(group_name, command_id, save=save)
        group = self._action_groups.get(group_name)
        if group:
            for action in group.actions():
                if str(action.data()) == command_id:
                    action.blockSignals(True)
                    action.setChecked(True)
                    action.blockSignals(False)
                    break

    def _update_checkmark(self, container: QtWidgets.QWidget, state: bool):
        lbl = getattr(container, "_chk", None)
        if lbl is None:
            lbl = container.findChild(QtWidgets.QLabel, "checkMark")
        if lbl is not None:
            lbl.setText("✓" if state else "")

    @profiler.profile
    def _create_row_widget(self, parent: QtWidgets.QWidget, text: str, hotkey: str, icon: str | None, has_options: bool, on_main_click: Callable[[], None] | None, on_options: Callable[[], None] | None, menu: QtWidgets.QMenu) -> QtWidgets.QWidget:
        w = CommandMenuRow(parent, text, hotkey, icon, has_options, menu)
        w._on_main_click = on_main_click
        w._on_options_callback = (lambda: self._on_row_options(menu, on_options)) if on_options is not None else None
        if on_main_click is not None:
            main_area = w._main
            if main_area is not None:
                def _row_click(event):
                    if event.button() == QtCore.Qt.LeftButton:
                        on_main_click()
                main_area.mouseReleaseEvent = _row_click
        if w._inited and w._has_options and w._on_options_callback is not None:
            btn = w._options_btn
            if btn is not None:
                btn.clicked.connect(w._on_options_callback)
        return w

    def _on_row_options(self, menu: QtWidgets.QMenu, on_options: Callable[[], None]):
        menu.close()
        on_options()

    def _execute_and_close_menu(self, name: str, parent: QtWidgets.QWidget | None, menu: QtWidgets.QMenu, checked: bool | None = None):
        menu.close()
        self._execute(name, parent, checked, seed_ctx=self._active_seed_ctx)

    def _show_options_and_close_menu(self, command_name: str, parent: QtWidgets.QWidget, menu: QtWidgets.QMenu, selection_callback: Callable[[Any], None] | None = None):
        menu.close()
        self._show_options(command_name, parent, selection_callback, seed_ctx=self._active_seed_ctx)

    @profiler.profile
    def _show_options(self, command_name: str, parent: QtWidgets.QWidget, selection_callback: Callable[[Any], None] | None = None, *, seed_ctx: CommandContext | None = None):
        command_class = self.registry.get_command(command_name)
        if not command_class:
            return
        def _exec_from_dialog(opts: dict[str, Any]):
            merged = dict(opts)
            ctx = self._build_ctx(parent, command_name, merged)
            if ctx is not None and command_class.meta.checkable:
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
                store = CommandOptionStore.instance()
                store.set(command_name, options)
                if not store.commit():
                    AppLogger.warning(f"Failed to save command options: {command_name}")
            if callable(selection_callback):
                try:
                    selection_callback(CommandPayload(command_name, options))
                except Exception as e:
                    AppLogger.warning(f"Failed to call selection callback for '{command_name}': {e}")
        else:
            if not callable(selection_callback):
                return
            return

    @profiler.profile
    def _execute(self, name: str, parent: QtWidgets.QWidget | None = None, checked: bool | None = None, *, seed_ctx: CommandContext | None = None):
        from ..bridge import Command
        args: dict[str, Any] = {}
        if parent is not None:
            ctx = self._build_ctx(parent, name, args)
            if ctx is None:
                ctx = CommandContext.create(parent, "*", source="menu", event=None, seed=seed_ctx)
            else:
                CommandContext.merge_seed(ctx, seed_ctx)
        else:
            ctx = CommandContext.create(None, "*", source="menu", event=None, seed=seed_ctx)
        if checked is not None:
            ctx.put("checked", bool(checked))
        try:
            Command.invoke(name, ctx=ctx, parent=parent)
        except Exception as e:
            AppLogger.warning(f"Failed to execute command '{name}': {e}")

    @profiler.profile
    def _get_or_create_submenu_chain(self, root_menu: QtWidgets.QMenu, cache: dict[str, QtWidgets.QMenu], parts: list[str], parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        cur_path = ""
        current = root_menu
        for part in parts:
            cur_path = (cur_path + "/" + part).lstrip("/")
            if cur_path in cache:
                current = cache[cur_path]
                continue
            m = StickyMenu(self.t.tr(part) or part, parent)
            current.addMenu(m)
            cache[cur_path] = m
            self._install_hotkey_alignment(m)
            current = m
        return current

    def refresh_check_states(self, menu: QtWidgets.QMenu) -> None:
        tracker = menu.property("__checkable_tracker__")
        if not tracker:
            return
        for widget_action, container, name, meta, is_group in tracker:
            if is_group:
                checked = self._get_checked_for_group(name, meta.action_group, meta)
            else:
                checked = self._get_checked(name, meta)
            widget_action.blockSignals(True)
            widget_action.setChecked(checked)
            widget_action.blockSignals(False)
            self._update_checkmark(container, checked)

    def _create_section_action(self, parent: QtWidgets.QWidget, text: str) -> QtWidgets.QAction:
        a = QtWidgets.QWidgetAction(parent)
        w = QtWidgets.QWidget(parent)
        l = QtWidgets.QHBoxLayout(w)
        s = CommandMenuRow._ensure_px()["sec"]
        l.setContentsMargins(int(s * 1.6), int(s / 4), int(s * 1.6), 0)
        lbl = QtWidgets.QLabel(text)
        lbl.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        lbl.setStyleSheet("color: gray; font-size: {}px;".format(s))
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
        l.addWidget(lbl)
        a.setDefaultWidget(w)
        return a


class MenuBuilder:
    def __init__(self, maker: MenuMaker, parent: QtWidgets.QWidget | None = None, *, seed_ctx: CommandContext | None = None):
        self._menu = StickyMenu(parent)
        self._menu.setProperty(COMMAND_MENU_MARKER, True)
        self._ctx_parent = parent
        self._builder = CommandMenuBuilder.instance()
        self._builder._install_hotkey_alignment(self._menu)
        self._seed_ctx = seed_ctx
        self._maker = maker

    @property
    def menu(self) -> QtWidgets.QMenu:
        return self._menu

    def _resolve_parent(self) -> QtWidgets.QWidget:
        parent = self._ctx_parent
        if parent is None:
            pw = getattr(self._menu, "parentWidget", None)
            if callable(pw):
                try:
                    parent = pw()
                except Exception as e:
                    AppLogger.warning("MenuBuilder parentWidget lookup failed", exc=e)
                    parent = None
        if parent is None:
            parent = self._menu
        return parent

    def _build_into(self, names: list[str], selection_callback: Callable[[Any], None] | None, allow_options_with_selection: bool) -> QtWidgets.QMenu:
        if names:
            parent = self._resolve_parent()
            self._builder.build_into(self._menu, parent, names, display_map=None, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection, seed_ctx=self._seed_ctx)
        return self._menu

    @profiler.profile
    def build(self, plan: MenuPlan, selection_callback: Callable[[Any], None] | None = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        if plan is None:
            self._menu.clear()
            return self._menu
        tokens = plan.resolve_tokens()
        parent = self._resolve_parent()
        if selection_callback is not None:
            self._menu = StickyMenu(self._ctx_parent)
            self._menu.setProperty(COMMAND_MENU_MARKER, True)
            self._builder._install_hotkey_alignment(self._menu)
            return self._build_into(tokens, selection_callback, allow_options_with_selection)
        if plan.has_inline:
            self._menu = StickyMenu(self._ctx_parent)
            self._menu.setProperty(COMMAND_MENU_MARKER, True)
            self._builder._install_hotkey_alignment(self._menu)
            return self._build_into(tokens, None, allow_options_with_selection)
        cache_key = (id(parent), tuple(tokens), False, allow_options_with_selection)
        cached = CommandMenuBuilder._menu_cache.get(cache_key)
        if cached is not None:
            self._builder._active_seed_ctx = self._seed_ctx
            self._builder.refresh_check_states(cached)
            self._menu = cached
            return cached
        self._menu = StickyMenu(self._ctx_parent)
        self._menu.setProperty(COMMAND_MENU_MARKER, True)
        self._builder._install_hotkey_alignment(self._menu)
        result = self._build_into(tokens, None, allow_options_with_selection)
        CommandMenuBuilder._menu_cache[cache_key] = result
        return result

    @profiler.profile
    def from_folder(self, folder: str) -> QtWidgets.QMenu:
        plan = self._maker.from_folder(folder)
        return self.build(plan)

    def build_all_roots(self, selection_callback: Callable[[Any], None] | None = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        plan = self._maker.all_roots()
        return self.build(plan, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection)

    def build_names(self, names: list[str], selection_callback: Callable[[Any], None] | None = None, allow_options_with_selection: bool = False) -> QtWidgets.QMenu:
        self._menu.clear()
        return self._build_into(list(names or []), selection_callback, allow_options_with_selection)

    def _popup(self, anchor: QtWidgets.QWidget, build_fn: Callable[[], QtWidgets.QMenu], context_provider: Callable[[], Any] | None, prepare: Callable[[QtWidgets.QMenu], None] | None) -> None:
        prev_seed = self._seed_ctx
        if callable(context_provider):
            try:
                v = context_provider()
                if isinstance(v, CommandContext):
                    self._seed_ctx = v
                elif isinstance(v, dict):
                    self._seed_ctx = CommandContext.create(None, "*", source="menu.popup", event=None, extras=dict(v))
            except Exception as e:
                AppLogger.warning("context_provider failed", exc=e)
        menu = build_fn()
        if callable(prepare):
            try:
                prepare(menu)
            except Exception as e:
                AppLogger.warning("prepare(menu) failed", exc=e)
        pos = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        menu.exec(pos)
        self._seed_ctx = prev_seed

    def popup_names(
        self,
        anchor: QtWidgets.QWidget,
        names: list[str],
        selection_callback: Callable[[Any], None],
        context_provider: Callable[[], Any] | None = None,
        prepare: Callable[[QtWidgets.QMenu], None] | None = None,
        allow_options_with_selection: bool = False,
    ) -> None:
        self._popup(anchor, lambda: self.build_names(names, selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection), context_provider, prepare)

    def popup_all_roots(self, anchor: QtWidgets.QWidget, selection_callback: Callable[[Any], None], context_provider: Callable[[], Any] | None = None, prepare: Callable[[QtWidgets.QMenu], None] | None = None, allow_options_with_selection: bool = False) -> None:
        self._popup(anchor, lambda: self.build_all_roots(selection_callback=selection_callback, allow_options_with_selection=allow_options_with_selection), context_provider, prepare)

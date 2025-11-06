from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from dataclasses import dataclass, field
from PySide6 import QtCore, QtGui, QtWidgets
from source.lang.manager import TranslatorMixin
from source.common.funcs import uipx

@dataclass
class CommandParam:
    name: str
    type: type
    default: Any = None
    description: str = ""
    choices: Optional[List[Any]] = None
    min_value: Optional[Any] = None
    max_value: Optional[Any] = None
    widget_type: str = "auto"

@dataclass
class CommandMeta:
    id: str = ""
    display: str = ""
    params: List[CommandParam] = field(default_factory=list)
    hotkey: str = ""
    icon: str = ""
    undoable: bool = False
    has_options: bool = False
    checkable: bool = False
    default_checked: bool = False

class CommandBase:
    meta: CommandMeta = None
    
    def __init__(self):
        self._undo_data: Optional[Dict[str, Any]] = None
        self._last_kwargs: Optional[Dict[str, Any]] = None
    
    def execute(self, **kwargs) -> Any:
        raise NotImplementedError
    
    def undo(self) -> None:
        if not self.meta.undoable:
            raise RuntimeError(f"Command {self.meta.id} is not undoable")
    
    def get_default_options(self) -> Dict[str, Any]:
        return {p.name: p.default for p in self.meta.params}

    def call_execute(self, **kwargs) -> Any:
        if self.meta and self.meta.params:
            args = _build_args(self.meta, kwargs)
        else:
            args = dict(kwargs)
        self._last_kwargs = dict(args)
        return self.execute(**args)

class CommandRegistry:
    _instance: Optional[CommandRegistry] = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._commands = {}
            cls._instance._history = []
            cls._instance._history_index = -1
        return cls._instance
    
    def register(self, command_class: type[CommandBase]) -> None:
        cid = getattr(command_class.meta, "id", None)
        if not cid:
            raise ValueError("Command id is required")
        if cid in self._commands:
            raise ValueError(f"Duplicate command id: {cid}")
        self._commands[cid] = command_class
    
    def execute(self, command_name: str, **kwargs) -> Any:
        if command_name not in self._commands:
            raise ValueError(f"Command {command_name} not found")
        
        command_class = self._commands[command_name]
        command = command_class()
        if hasattr(command, "call_execute"):
            result = command.call_execute(**kwargs)
        else:
            result = command.execute(**kwargs)
        
        if command.meta.undoable:
            if self._history_index < len(self._history) - 1:
                self._history = self._history[:self._history_index + 1]
            self._history.append(command)
            self._history_index = len(self._history) - 1
        
        return result
    
    def undo(self) -> None:
        if self._history_index < 0:
            return
        self._history[self._history_index].undo()
        self._history_index -= 1
    
    def redo(self) -> None:
        if self._history_index >= len(self._history) - 1:
            return
        self._history_index += 1
        cmd = self._history[self._history_index]
        kwargs = getattr(cmd, "_last_kwargs", None) or {}
        if hasattr(cmd, "call_execute"):
            cmd.call_execute(**kwargs)
        else:
            cmd.execute(**kwargs)
    
    def get_command(self, name: str) -> Optional[type[CommandBase]]:
        return self._commands.get(name)
    
    def get_all_commands(self) -> Dict[str, type[CommandBase]]:
        return self._commands.copy()

def _build_args(meta: CommandMeta, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    r = {}
    for p in meta.params:
        v = kwargs[p.name] if p.name in kwargs else p.default
        r[p.name] = v
    return r

def create_command_from_callable(meta: CommandMeta, func: Callable[..., Any], undo: Optional[Callable[[], Any]] = None) -> type[CommandBase]:
    class _Cmd(CommandBase):
        pass
    _Cmd.meta = meta
    setattr(_Cmd, "execute", func)
    if undo is not None:
        def _undo(self):
            return undo()
        setattr(_Cmd, "undo", _undo)
    return _Cmd

def register_command_defs(defs: List[Dict[str, Any]]):
    r = CommandRegistry()
    for d in defs:
        meta = d["meta"]
        fn = d["func"]
        undo = d.get("undo")
        r.register(create_command_from_callable(meta, fn, undo))

def _split_parts(raw: str) -> List[str]:
    return [p for p in raw.split("/") if p]

def _is_sep_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = _split_parts(s.strip())
    return bool(parts) and parts[-1] == "-"

def _sep_path(s: str) -> List[str]:
    parts = _split_parts(s.strip())
    return parts[:-1] if parts and parts[-1] == "-" else []

def _is_section_token(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    parts = _split_parts(s)
    return bool(parts) and str(parts[-1]).startswith(":")

def _section_parts(s: str) -> List[str]:
    parts = _split_parts(s)
    if not parts:
        return []
    head = parts[:-1]
    label = parts[-1][1:] if parts[-1].startswith(":") else parts[-1]
    return head + [label]

class CommandOptionsDialog(QtWidgets.QDialog, TranslatorMixin):
    def __init__(self, command_class: type[CommandBase], parent=None):
        super().__init__(parent)
        self.command_class = command_class
        self.widgets: Dict[str, QtWidgets.QWidget] = {}
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
        
        button_box = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel
        )
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)
    
    def _create_widget(self, param: CommandParam) -> QtWidgets.QWidget:
        if param.choices:
            combo = QtWidgets.QComboBox()
            for choice in param.choices:
                combo.addItem(str(choice), choice)
            if param.default is not None:
                index = combo.findData(param.default)
                if index >= 0:
                    combo.setCurrentIndex(index)
            return combo
        
        if param.type == bool:
            checkbox = QtWidgets.QCheckBox()
            checkbox.setChecked(bool(param.default))
            return checkbox
        
        if param.type == int:
            spinbox = QtWidgets.QSpinBox()
            if param.min_value is not None:
                spinbox.setMinimum(param.min_value)
            if param.max_value is not None:
                spinbox.setMaximum(param.max_value)
            spinbox.setValue(param.default or 0)
            return spinbox
        
        if param.type == float:
            spinbox = QtWidgets.QDoubleSpinBox()
            if param.min_value is not None:
                spinbox.setMinimum(param.min_value)
            if param.max_value is not None:
                spinbox.setMaximum(param.max_value)
            spinbox.setValue(param.default or 0.0)
            return spinbox
        
        lineedit = QtWidgets.QLineEdit()
        lineedit.setText(str(param.default or ""))
        return lineedit
    
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

    def build(
        self, 
        parent: QtWidgets.QWidget,
        command_names: List[str],
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        display_map: Optional[Dict[str, str]] = None,
    ) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        return self.build_into(menu, parent, command_names, context_provider, display_map)

    def build_into(
        self,
        menu: QtWidgets.QMenu,
        parent: QtWidgets.QWidget,
        command_names: List[str],
        context_provider: Optional[Callable[[], Dict[str, Any]]] = None,
        display_map: Optional[Dict[str, str]] = None,
    ) -> QtWidgets.QMenu:
        menus_cache: Dict[str, QtWidgets.QMenu] = {}
        for name in command_names:
            if _is_sep_token(name):
                parts = _sep_path(str(name))
                if not parts:
                    menu.addSeparator()
                    continue
                target_menu = self._get_or_create_submenu_chain(menu, menus_cache, parts, parent)
                target_menu.addSeparator()
                continue
            
            if _is_section_token(name):
                parts = _section_parts(str(name))
                if not parts:
                    continue
                text = parts[-1]
                target_menu = menu if len(parts) == 1 else self._get_or_create_submenu_chain(menu, menus_cache, parts[:-1], parent)
                target_menu.addAction(self._create_section_action(parent, self.t.tr(text) or text))
                continue
            
            path_parts = [p for p in name.split("/") if p]
            command_id = path_parts[-1] if len(path_parts) > 1 else name
            target_menu = menu if len(path_parts) <= 1 else self._get_or_create_submenu_chain(menu, menus_cache, path_parts[:-1], parent)

            command_class = self.registry.get_command(command_id)
            if not command_class:
                raise ValueError(f"Unknown command id: {command_id}")
            
            meta = command_class.meta
            if display_map and command_id in display_map:
                disp = (display_map.get(command_id) or self.t.tr(meta.display)) or self.t.tr(meta.display)
                dparts = [p for p in disp.split("/") if p]
                if len(dparts) > 1:
                    target_menu = self._get_or_create_submenu_chain(menu, menus_cache, dparts[:-1], parent)
                text_override = dparts[-1] if dparts else self.t.tr(meta.display)
            else:
                text_override = None
            self._add_entry(target_menu, parent, command_id, meta, context_provider, bool(meta.has_options), text_override)
        return menu
    
    def _add_entry(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, name: str, meta: CommandMeta, context_provider: Optional[Callable[[], Dict[str, Any]]], with_options: bool, text_override: Optional[str]):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        container = self._create_row_widget(parent, text, meta.hotkey, meta.icon or None, with_options, None, (lambda: self._show_options_and_close_menu(name, parent, context_provider, menu)) if with_options else None, menu)
        widget_action.setDefaultWidget(container)
        if meta.checkable:
            widget_action.setCheckable(True)
            checked = self._get_checked(name, meta)
            widget_action.setChecked(checked)
            self._update_checkmark(container, checked)
            widget_action.toggled.connect(lambda state, n=name, c=container: self._on_toggled(n, c, state))
        widget_action.triggered.connect(lambda checked=False, n=name, m=meta, p=context_provider: self._execute_and_close_menu(n, self._wrap_provider_with_checked(p, checked, m), menu))
        main_area = container.findChild(QtWidgets.QWidget, "rowMain")
        if main_area is not None:
            def _row_click_any(event):
                if event.button() == QtCore.Qt.LeftButton:
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click_any
        menu.addAction(widget_action)
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
    
    def _create_row_widget(
        self,
        parent: QtWidgets.QWidget,
        text: str,
        hotkey: str,
        icon: Optional[str],
        has_options: bool,
        on_main_click: Optional[Callable[[], None]],
        on_options: Optional[Callable[[], None]],
        menu: QtWidgets.QMenu,
    ) -> QtWidgets.QWidget:
        container = QtWidgets.QWidget(parent)
        container.setObjectName("commandMenuRow")
        layout = QtWidgets.QHBoxLayout(container)
        layout.setContentsMargins(8, 2, 6, 2)
        layout.setSpacing(0)
        container.setStyleSheet(
            "#commandMenuRow #rowMain{border:1px solid transparent;border-radius:4px;background:transparent;}"
            "#commandMenuRow #rowMain:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}"
            "#commandMenuRow QToolButton{border:1px solid transparent;border-radius:4px;background:transparent;}"
            "#commandMenuRow QToolButton:hover{border:1px solid palette(Highlight);background:palette(AlternateBase);}"
            "#commandMenuRow QLabel{background:transparent;}"
        )
        gutter_w = 0
        try:
            style = menu.style() if menu is not None else container.style()
            icon_sz = style.pixelMetric(QtWidgets.QStyle.PM_SmallIconSize, None, menu)
            frame_w = style.pixelMetric(QtWidgets.QStyle.PM_DefaultFrameWidth, None, menu)
            gutter_w = max(0, int(icon_sz + frame_w))
        except Exception:
            gutter_w = 22
        main_area = QtWidgets.QWidget(container)
        main_area.setObjectName("rowMain")
        main_area.setCursor(QtCore.Qt.PointingHandCursor)
        main_area.setAttribute(QtCore.Qt.WA_Hover, True)
        main_area_layout = QtWidgets.QHBoxLayout(main_area)
        main_area_layout.setContentsMargins(4, 2, 8, 2)
        main_area_layout.setSpacing(6)
        check_lbl = QtWidgets.QLabel("", main_area)
        check_lbl.setObjectName("checkMark")
        check_lbl.setFixedWidth(gutter_w)
        check_lbl.setAlignment(QtCore.Qt.AlignCenter)
        check_lbl.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents, True)
        main_area_layout.addWidget(check_lbl, 0)
        if icon:
            icon_label = QtWidgets.QLabel(main_area)
            qicon = QtGui.QIcon(icon) if isinstance(icon, str) else icon
            pm = qicon.pixmap(16, 16)
            icon_label.setPixmap(pm)
            main_area_layout.addWidget(icon_label, 0)
        text_label = QtWidgets.QLabel(text, main_area)
        text_label.setAlignment(QtCore.Qt.AlignVCenter | QtCore.Qt.AlignLeft)
        main_area_layout.addWidget(text_label, 1)
        shortcut_str = QtGui.QKeySequence(hotkey).toString() if hotkey else ""
        shortcut_label = QtWidgets.QLabel(shortcut_str, main_area)
        shortcut_label.setAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        shortcut_label.setMinimumWidth(60 if hotkey else 0)
        main_area_layout.addWidget(shortcut_label, 0)
        if on_main_click is not None:
            def _row_click(event):
                if event.button() == QtCore.Qt.LeftButton:
                    on_main_click()
            main_area.mouseReleaseEvent = _row_click
        layout.addWidget(main_area, 1)
        if has_options:
            opt_btn = QtWidgets.QToolButton(container)
            opt_btn.setText("□")
            opt_btn.setAutoRaise(True)
            opt_btn.setFixedWidth(22)
            opt_btn.setCursor(QtCore.Qt.PointingHandCursor)
            opt_btn.setFocusPolicy(QtCore.Qt.NoFocus)
            if on_options:
                opt_btn.clicked.connect(lambda: self._on_row_options(menu, on_options))
            layout.addWidget(opt_btn, 0)
        else:
            spacer = QtWidgets.QWidget(container)
            spacer.setFixedWidth(22)
            spacer.setVisible(False)
            layout.addWidget(spacer, 0)
        return container
    
    def _on_row_options(self, menu: QtWidgets.QMenu, on_options: Callable[[], None]):
        menu.close()
        on_options()
    
    def _execute_and_close_menu(self, name: str, provider: Optional[Callable[[], Dict[str, Any]]], menu: QtWidgets.QMenu):
        menu.close()
        self._execute(name, provider)
    
    def _show_options_and_close_menu(
        self,
        command_name: str,
        parent: QtWidgets.QWidget,
        context_provider: Optional[Callable[[], Dict[str, Any]]],
        menu: QtWidgets.QMenu
    ):
        menu.close()
        self._show_options(command_name, parent, context_provider)
    
    def _show_options(
        self,
        command_name: str,
        parent: QtWidgets.QWidget,
        context_provider: Optional[Callable[[], Dict[str, Any]]]
    ):
        command_class = self.registry.get_command(command_name)
        if not command_class:
            return
        
        dialog = CommandOptionsDialog(command_class, parent)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            options = dialog.get_values()
            context = context_provider() if context_provider else {}
            options.update(context)
            if getattr(command_class.meta, 'checkable', False):
                options['checked'] = bool(self._get_checked(command_name, command_class.meta))
            self._execute(command_name, lambda: options)
    
    def _execute(self, name: str, provider: Optional[Callable[[], Dict[str, Any]]]):
        kwargs = provider() if provider else {}
        try:
            self.registry.execute(name, **kwargs)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, self.t.tr("Error"), str(e))

    def _get_or_create_submenu_chain(
        self,
        root_menu: QtWidgets.QMenu,
        cache: Dict[str, QtWidgets.QMenu],
        parts: List[str],
        parent: QtWidgets.QWidget,
    ) -> QtWidgets.QMenu:
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
        lbl.setStyleSheet('color: gray; font-size: {}px;'.format(s))
        lbl.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Maximum)
        l.addWidget(lbl)
        a.setDefaultWidget(w)
        return a

class RegistryBackedMenu:
    _flags: Dict[type, bool] = {}
    _items: Dict[type, List[str]] = {}
    _cmd_paths: Dict[type, Dict[str, str]] = {}

    def __init__(self):
        self.ensure_registered()

    def ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = self.create_definitions()
        base = getattr(self, "path_prefix", None)
        bparts = _split_parts(base) if isinstance(base, str) and base else []
        defs: List[Dict[str, Any]] = []
        items: List[str] = []
        cmd_paths: Dict[str, str] = {}
        def _prefixed_path(p: str) -> str:
            pparts = _split_parts(p)
            if not bparts:
                return "/".join(pparts)
            if pparts[:len(bparts)] == bparts:
                return "/".join(pparts)
            return "/".join(bparts + pparts)
        def _prefixed_item_token(s: str) -> str:
            if not bparts:
                return s
            if _is_sep_token(s):
                sparts = _sep_path(s)
                return "/".join(bparts + sparts + ["-"])
            if _is_section_token(s):
                sparts = _section_parts(s)
                if not sparts:
                    return s
                head, label = sparts[:-1], sparts[-1]
                if head[:len(bparts)] == bparts:
                    return "/".join(head + [":" + label])
                return "/".join(bparts + head + [":" + label])
            # command path in items
            return _prefixed_path(s)
        if isinstance(res, tuple) and len(res) == 2:
            raw_defs, raw_items = res  # type: ignore
            # normalize defs: require path and derive id from path, apply base prefix
            new_defs: List[Dict[str, Any]] = []
            for e in raw_defs:
                if not isinstance(e, dict) or ("meta" not in e):
                    raise ValueError("Definition must be a dict with 'meta' and 'path'")
                meta = e["meta"]
                full_path = e.get("path")
                if not full_path:
                    raise ValueError("Command 'path' is required and id is derived from its last segment")
                full_path = _prefixed_path(str(full_path))
                parts = _split_parts(full_path)
                if not parts or parts[-1] == "-" or str(parts[-1]).startswith(":"):
                    raise ValueError(f"Invalid command path: {full_path}")
                cid = parts[-1]
                if hasattr(meta, "id"):
                    setattr(meta, "id", cid)
                e["path"] = "/".join(parts)
                new_defs.append(e)
            defs = new_defs
            # normalize items: apply base prefix to tokens and paths
            adj_items: List[str] = []
            for s in raw_items:
                if isinstance(s, str):
                    adj_items.append(_prefixed_item_token(s))
            items = adj_items
            # derive ids from paths declared in defs
            for s in items:
                if isinstance(s, str) and s and not _is_section_token(s) and not _is_sep_token(s):
                    parts = [p for p in s.split("/") if p]
                    if parts:
                        cid = parts[-1]
                        if cid in cmd_paths:
                            raise ValueError(f"Duplicate command id in {t.__name__}: {cid}")
                        cmd_paths[cid] = s
        elif isinstance(res, list):
            for e in res:  # type: ignore
                if isinstance(e, str):
                    items.append(_prefixed_item_token(e))
                elif isinstance(e, dict) and ("meta" in e):
                    meta = e["meta"]
                    full_path = e.get("path")
                    if not full_path:
                        raise ValueError("Command 'path' is required and id is derived from its last segment")
                    full_path = _prefixed_path(str(full_path))
                    parts = _split_parts(full_path)
                    if not parts or parts[-1] == "-" or str(parts[-1]).startswith(":"):
                        raise ValueError(f"Invalid command path: {full_path}")
                    cid = parts[-1]
                    if hasattr(meta, "id"):
                        setattr(meta, "id", cid)
                    e["path"] = "/".join(parts)
                    defs.append(e)
                    items.append(e["path"])
                    if cid:
                        scid = str(cid)
                        if scid in cmd_paths:
                            raise ValueError(f"Duplicate command id in {t.__name__}: {scid}")
                        cmd_paths[scid] = e["path"]
        elif res:
            raw_defs = res  # type: ignore
            new_defs: List[Dict[str, Any]] = []
            for d in raw_defs:
                if not isinstance(d, dict) or "meta" not in d:
                    raise ValueError("Definition must be a dict with 'meta' and 'path'")
                meta = d["meta"]
                full_path = d.get("path")
                if not full_path:
                    raise ValueError("Command 'path' is required and id is derived from its last segment")
                full_path = _prefixed_path(str(full_path))
                parts = _split_parts(full_path)
                if not parts or parts[-1] == "-" or str(parts[-1]).startswith(":"):
                    raise ValueError(f"Invalid command path: {full_path}")
                cid = parts[-1]
                if hasattr(meta, "id"):
                    setattr(meta, "id", cid)
                full_path = "/".join(parts)
                items.append(full_path)
                scid = str(cid)
                if scid in cmd_paths:
                    raise ValueError(f"Duplicate command id in {t.__name__}: {scid}")
                cmd_paths[scid] = full_path
                d["path"] = full_path
                new_defs.append(d)
            defs = new_defs
        if defs:
            register_command_defs(defs)
        if items:
            self._items[t] = items
        if cmd_paths:
            self._cmd_paths[t] = cmd_paths
        try:
            MenuHub().register_paths(t, cmd_paths, items)
        except Exception:
            pass
        self._flags[t] = True

    def create_definitions(self) -> Any:
        return []

    

class MenuHub:
    _instance: Optional["MenuHub"] = None
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._all_paths = {}
            cls._instance._by_menu = {}
            cls._instance._menu_items = {}
        return cls._instance
    def register_paths(self, menu_cls: type, cmd_paths: Dict[str, str], items: Optional[List[str]] = None):
        if cmd_paths:
            self._by_menu[menu_cls] = dict(cmd_paths)
            for k, v in cmd_paths.items():
                if k in self._all_paths and self._all_paths[k] != v:
                    raise ValueError(f"Command id already registered: {k}")
                self._all_paths[k] = v
        if items is not None:
            self._menu_items[menu_cls] = list(items)
    
    def get_path_by_command_id(self, command_id: str) -> str:
        return self._all_paths.get(command_id, "")

    

    def has_folder(self, folder: str) -> bool:
        f = folder.strip("/")
        if not f:
            return False
        for p in self._all_paths.values():
            parts = _split_parts(p)
            if len(parts) <= 1:
                continue
            if f in parts[:-1]:
                return True
        return False

    def find_folder_prefixes(self, name: str) -> List[str]:
        n = name.strip("/")
        if not n:
            return []
        seen: Dict[str, None] = {}
        out: List[str] = []
        for p in self._all_paths.values():
            parts = _split_parts(p)
            if len(parts) <= 1:
                continue
            for i in range(len(parts) - 1):
                if parts[i] == n:
                    pref = "/".join(parts[: i + 1])
                    if pref not in seen:
                        seen[pref] = None
                        out.append(pref)
        return out

    def collect_items_by_folder(self, folder: str, rebase_to: Optional[str] = None) -> List[str]:
        f = folder.strip("/")
        blocks: List[List[str]] = []
        for cls, items in self._menu_items.items():
            paths_map = self._by_menu.get(cls, {})
            cur: List[str] = []
            def _flush():
                nonlocal cur
                if cur:
                    blocks.append(cur)
                    cur = []
            for s in items:
                if _is_sep_token(s) and not _sep_path(str(s)):
                    _flush()
                    continue
                cur.append(s)
            _flush()
        # filter blocks that contain at least one command under folder f
        fparts = _split_parts(f)
        filtered: List[List[str]] = []
        for b in blocks:
            has = False
            for s in b:
                if not isinstance(s, str) or not s or _is_sep_token(s) or _is_section_token(s):
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = ""
                    for maps in self._by_menu.values():
                        if s in maps:
                            pfull = maps[s]
                            break
                if pfull and _split_parts(pfull)[:len(fparts)] == fparts:
                    has = True
                    break
            if has:
                filtered.append(b)
        out: List[str] = []
        pre = rebase_to.strip("/") if rebase_to else f
        first = True
        for b in filtered:
            if not first:
                out.append(f"{pre}/-")
            first = False
            for s in b:
                if not isinstance(s, str) or not s:
                    continue
                if _is_sep_token(s):
                    src = _sep_path(str(s))
                    if not src:
                        out.append(f"{pre}/-")
                        continue
                    if src[:len(fparts)] != fparts:
                        continue
                    rel = src[len(fparts):]
                    out.append("/".join([pre] + rel + ["-"]))
                    continue
                if _is_section_token(s):
                    parts = _section_parts(s)
                    if not parts:
                        continue
                    head = parts[:-1]
                    label = parts[-1]
                    if head[:len(fparts)] != fparts:
                        continue
                    rel = head[len(fparts):]
                    out.append("/".join([pre] + rel + [":" + label]))
                    continue
                if "/" in s:
                    pfull = s
                else:
                    pfull = ""
                    for maps in self._by_menu.values():
                        if s in maps:
                            pfull = maps[s]
                            break
                if pfull and pfull.startswith(f + "/"):
                    rel = pfull[len(f) + 1:]
                    out.append(f"{pre}/{rel}".lstrip("/"))
        return out


class MenuBuilder:
    def __init__(self, parent: Optional[QtWidgets.QWidget] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None):
        self._menu = QtWidgets.QMenu(parent)
        self._builder = CommandMenuBuilder()
        self._hub = MenuHub()
        self._ctx = context_provider
    @property
    def menu(self) -> QtWidgets.QMenu:
        return self._menu
    def build(self, items: List[str]) -> QtWidgets.QMenu:
        self._menu.clear()
        all_names: List[str] = []
        seen: set[str] = set()
        for it in items:
            if not it:
                continue
            if _is_sep_token(it) or _is_section_token(it):
                all_names.append(it)
                continue
            
            if "/" in it and (_is_sep_token(it) or _is_section_token(it)):
                all_names.append(it)
                continue
            if "/" in it:
                parts = _split_parts(it)
                if len(parts) >= 2:
                    orig_folder = parts[-1]
                    if self._hub.has_folder(orig_folder):
                        prefixes = self._hub.find_folder_prefixes(orig_folder)
                        if not prefixes:
                            raise ValueError(f"Unknown folder: {orig_folder}")
                        if len(prefixes) > 1:
                            raise ValueError(f"Ambiguous folder: {orig_folder}")
                        names = self._hub.collect_items_by_folder(prefixes[0], rebase_to=it)
                        for n in names:
                            if not (_is_sep_token(n) or _is_section_token(n)):
                                if n in seen:
                                    raise ValueError(f"Duplicate item after rebase: {n}")
                                seen.add(n)
                        all_names.extend(names)
                        continue
                if self._hub.has_folder(it):
                    names = self._hub.collect_items_by_folder(it, rebase_to=it)
                    if not names:
                        raise ValueError(f"Unknown folder: {it}")
                    for n in names:
                        if not (_is_sep_token(n) or _is_section_token(n)):
                            if n in seen:
                                raise ValueError(f"Duplicate item after rebase: {n}")
                            seen.add(n)
                    all_names.extend(names)
                    continue
                path_cid = _split_parts(it)[-1]
                if not self._hub.get_path_by_command_id(path_cid):
                    raise ValueError(f"Unknown command path or folder: {it}")
                if it in seen:
                    raise ValueError(f"Duplicate item: {it}")
                seen.add(it)
                all_names.append(it)
                continue
            p = self._hub.get_path_by_command_id(it)
            if p:
                cid = it
                if cid in seen:
                    raise ValueError(f"Duplicate item: {cid}")
                seen.add(cid)
                all_names.append(cid)
            else:
                prefixes = self._hub.find_folder_prefixes(it) if self._hub.has_folder(it) else []
                if len(prefixes) > 1:
                    raise ValueError(f"Ambiguous folder: {it}")
                if len(prefixes) == 1:
                    names = self._hub.collect_items_by_folder(prefixes[0], rebase_to=it)
                else:
                    names = self._hub.collect_items_by_folder(it, rebase_to=it)
                if not names:
                    raise ValueError(f"Unknown command or folder id: {it}")
                for n in names:
                    if not (_is_sep_token(n) or _is_section_token(n)):
                        if n in seen:
                            raise ValueError(f"Duplicate item after rebase: {n}")
                        seen.add(n)
                all_names.extend(names)
        if all_names:
            self._builder.build_into(self._menu, self._menu, all_names, context_provider=self._ctx, display_map=None)
        return self._menu
    def build_all_roots(self) -> QtWidgets.QMenu:
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
        return self.build(roots)
from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional, TYPE_CHECKING
from dataclasses import dataclass, field
from PySide6 import QtCore, QtGui, QtWidgets
from source.lang.manager import TranslatorMixin
from source.common.funcs import uipx
from source.common.profiling import logger, profiler

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
    id: str
    display: str
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
    
    def execute(self, **kwargs) -> Any:
        raise NotImplementedError
    
    def undo(self) -> None:
        if not self.meta.undoable:
            raise RuntimeError(f"Command {self.meta.id} is not undoable")
    
    def get_default_options(self) -> Dict[str, Any]:
        return {p.name: p.default for p in self.meta.params}

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
        self._commands[command_class.meta.id] = command_class
    
    def execute(self, command_name: str, **kwargs) -> Any:
        if command_name not in self._commands:
            raise ValueError(f"Command {command_name} not found")
        
        command_class = self._commands[command_name]
        command = command_class()
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
        self._history[self._history_index].execute()
    
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
    def _exec(self, **kwargs):
        return func(**_build_args(self.meta, kwargs))
    setattr(_Cmd, "execute", _exec)
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
            if name == "---":
                menu.addSeparator()
                continue
            
            if name.startswith(":"):
                raw = name[1:].strip()
                parts = [p for p in raw.split("/") if p]
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
                continue
            
            meta = command_class.meta
            if display_map and command_id in display_map:
                disp = (display_map.get(command_id) or self.t.tr(meta.display)) or self.t.tr(meta.display)
                dparts = [p for p in disp.split("/") if p]
                if len(dparts) > 1:
                    target_menu = self._get_or_create_submenu_chain(menu, menus_cache, dparts[:-1], parent)
                text_override = dparts[-1] if dparts else self.t.tr(meta.display)
            else:
                text_override = None
            if meta.has_options:
                self._add_action_with_options(target_menu, parent, command_id, meta, context_provider, text_override=text_override)
            else:
                self._add_action(target_menu, parent, command_id, meta, context_provider, text_override=text_override)
        return menu
    
    

    def _add_action(
        self,
        menu: QtWidgets.QMenu,
        parent: QtWidgets.QWidget,
        name: str,
        meta: CommandMeta,
        context_provider: Optional[Callable[[], Dict[str, Any]]],
        text_override: Optional[str] = None,
    ):
        text = text_override or self.t.tr(meta.display)
        on_trigger = lambda n=name: self._execute(n, context_provider)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        container = self._create_row_widget(parent, text, meta.hotkey, meta.icon or None, False, None, None, menu)
        widget_action.setDefaultWidget(container)
        if meta.checkable:
            widget_action.setCheckable(True)
            checked = self._get_checked(name, meta)
            widget_action.setChecked(checked)
            self._update_checkmark(container, checked)
            widget_action.toggled.connect(lambda state, n=name, c=container: self._on_toggled(n, c, state))
        widget_action.triggered.connect(lambda checked=False, n=name, m=meta, p=context_provider: self._execute(n, self._wrap_provider_with_checked(p, checked, m)))
        main_area = container.findChild(QtWidgets.QWidget, "rowMain")
        if main_area is not None:
            def _row_click(event):
                if event.button() == QtCore.Qt.LeftButton:
                    menu.close()
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click
        menu.addAction(widget_action)
    
    def _add_action_with_options(
        self,
        menu: QtWidgets.QMenu,
        parent: QtWidgets.QWidget,
        name: str,
        meta: CommandMeta,
        context_provider: Optional[Callable[[], Dict[str, Any]]],
        text_override: Optional[str] = None,
    ):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        container = self._create_row_widget(
            parent,
            text,
            meta.hotkey,
            meta.icon or None,
            True,
            None,
            lambda: self._show_options_and_close_menu(name, parent, context_provider, menu),
            menu,
        )
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
            def _row_click_opt(event):
                if event.button() == QtCore.Qt.LeftButton:
                    widget_action.trigger()
            main_area.mouseReleaseEvent = _row_click_opt
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


class MenuProviderBase:
    def build_menu(self, parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        raise NotImplementedError

class RegistryBackedMenu(MenuProviderBase):
    _flags: Dict[type, bool] = {}
    _items: Dict[type, List[str]] = {}
    DISPLAY: str = ""

    def __init__(self, command_names: Optional[List[str]] = None, **kwargs):
        self._builder = CommandMenuBuilder()
        self._context_provider = kwargs.get("context_provider")
        dm = kwargs.get("display_map")
        self._display_map = dict(dm) if isinstance(dm, dict) else None
        self._command_names: Optional[List[str]] = list(command_names) if command_names is not None else None
        self.ensure_registered()
        if self._command_names is None:
            self._command_names = list(self._items.get(type(self), []))

    def ensure_registered(self):
        t = type(self)
        if self._flags.get(t, False):
            return
        res = self.create_definitions()
        defs: List[Dict[str, Any]] = []
        items: List[str] = []
        if isinstance(res, tuple) and len(res) == 2:
            defs, items = res  # type: ignore
        elif isinstance(res, list):
            for e in res:  # type: ignore
                if isinstance(e, str):
                    items.append(e)
                elif isinstance(e, dict) and ("meta" in e):
                    defs.append(e)
                    meta = e["meta"]
                    cid = getattr(meta, "id", None) or (meta.get("id") if isinstance(meta, dict) else None)
                    mp = e.get("menu_path")
                    items.append(f"{mp}/{cid}".lstrip("/") if mp else cid)
        elif res:
            defs = res  # type: ignore
            items = [getattr(d["meta"], "id") for d in defs if isinstance(d, dict) and "meta" in d]
        if defs:
            register_command_defs(defs)
        if items:
            self._items[t] = items
        self._flags[t] = True

    def create_definitions(self) -> Any:
        return []

    def build_menu(self, parent: QtWidgets.QWidget) -> QtWidgets.QMenu:
        return self._builder.build(parent, self._command_names or [], context_provider=self._context_provider, display_map=self._display_map)

    def build_into(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget):
        self._builder.build_into(menu, parent, self._command_names or [], context_provider=self._context_provider, display_map=self._display_map)

    def build_submenu(self, parent: QtWidgets.QWidget, title: Optional[str] = None) -> QtWidgets.QMenu:
        t = title if title is not None else getattr(type(self), "DISPLAY", "")
        sm = QtWidgets.QMenu(t, parent)
        self.build_into(sm, parent)
        return sm


class CommandMenuSection(MenuProviderBase):
    pass


class CompositeMenuBuilder:
    pass
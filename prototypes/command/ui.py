from __future__ import annotations
from typing import Any, Callable, Dict, List, Optional
from PySide6 import QtCore, QtGui, QtWidgets
from source.lang.manager import TranslatorMixin
from source.common.funcs import uipx
from .core import CommandMeta, CommandRegistry
from .menu import (
    split_parts,
    is_sep_token,
    sep_path,
    is_section_token,
    section_parts,
    chain_providers,
    MenuHub,
)


class CommandOptionsDialog(QtWidgets.QDialog, TranslatorMixin):
    def __init__(self, command_class: type, parent=None):
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
        button_box = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def _create_widget(self, param) -> QtWidgets.QWidget:
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

    def build(self, parent: QtWidgets.QWidget, command_names: List[str], context_provider: Optional[Callable[[], Dict[str, Any]]] = None, display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[str], None]] = None) -> QtWidgets.QMenu:
        menu = QtWidgets.QMenu(parent)
        return self.build_into(menu, parent, command_names, context_provider, display_map, selection_callback)

    def build_into(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, command_names: List[str], context_provider: Optional[Callable[[], Dict[str, Any]]] = None, display_map: Optional[Dict[str, str]] = None, selection_callback: Optional[Callable[[str], None]] = None) -> QtWidgets.QMenu:
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
            self._add_entry(target_menu, parent, command_id, meta, context_provider, bool(meta.has_options) if not selection_callback else False, text_override, selection_callback)
        return menu

    def _add_entry(self, menu: QtWidgets.QMenu, parent: QtWidgets.QWidget, name: str, meta: CommandMeta, context_provider: Optional[Callable[[], Dict[str, Any]]], with_options: bool, text_override: Optional[str], selection_callback: Optional[Callable[[str], None]] = None):
        text = text_override or self.t.tr(meta.display)
        widget_action = QtWidgets.QWidgetAction(parent)
        widget_action.setData(name)
        container = self._create_row_widget(parent, text, meta.hotkey, meta.icon or None, with_options, None, (lambda: self._show_options_and_close_menu(name, parent, context_provider, menu)) if with_options else None, menu)
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

    def _select_and_close_menu(self, name: str, menu: QtWidgets.QMenu, callback: Callable[[str], None]):
        menu.close()
        try:
            callback(name)
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

    def _show_options_and_close_menu(self, command_name: str, parent: QtWidgets.QWidget, context_provider: Optional[Callable[[], Dict[str, Any]]], menu: QtWidgets.QMenu):
        menu.close()
        self._show_options(command_name, parent, context_provider)

    def _show_options(self, command_name: str, parent: QtWidgets.QWidget, context_provider: Optional[Callable[[], Dict[str, Any]]]):
        command_class = self.registry.get_command(command_name)
        if not command_class:
            return
        dialog = CommandOptionsDialog(command_class, parent)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            options = dialog.get_values()
            context = context_provider() if context_provider else {}
            options.update(context)
            if getattr(command_class.meta, "checkable", False):
                options["checked"] = bool(self._get_checked(command_name, command_class.meta))
            self._execute(command_name, lambda: options)

    def _execute(self, name: str, provider: Optional[Callable[[], Dict[str, Any]]]):
        kwargs = provider() if provider else {}
        try:
            self.registry.execute(name, **kwargs)
        except Exception as e:
            QtWidgets.QMessageBox.critical(None, self.t.tr("Error"), str(e))

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

    def build(self, items: List[str], selection_callback: Optional[Callable[[str], None]] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> QtWidgets.QMenu:
        self._menu.clear()
        all_names: List[str] = []
        seen: set[str] = set()
        for it in items:
            if not it:
                continue
            if is_sep_token(it) or is_section_token(it):
                all_names.append(it)
                continue
            if "/" in it and (is_sep_token(it) or is_section_token(it)):
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
                        names = self._hub.collect_items_by_folder(prefixes[0], rebase_to=it)
                        for n in names:
                            if not (is_sep_token(n) or is_section_token(n)):
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
                        if not (is_sep_token(n) or is_section_token(n)):
                            if n in seen:
                                raise ValueError(f"Duplicate item after rebase: {n}")
                            seen.add(n)
                    all_names.extend(names)
                    continue
                path_cid = split_parts(it)[-1]
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
                    if not (is_sep_token(n) or is_section_token(n)):
                        if n in seen:
                            raise ValueError(f"Duplicate item after rebase: {n}")
                            seen.add(n)
                all_names.extend(names)
        if all_names:
            ctx = chain_providers(self._ctx, context_provider)
            self._builder.build_into(self._menu, self._menu, all_names, context_provider=ctx, display_map=None, selection_callback=selection_callback)
        return self._menu

    def build_all_roots(self, selection_callback: Optional[Callable[[str], None]] = None, context_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> QtWidgets.QMenu:
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
        return self.build(roots, selection_callback=selection_callback, context_provider=context_provider)

    def popup_all_roots(self, anchor: QtWidgets.QWidget, selection_callback: Callable[[str], None], context_provider: Optional[Callable[[], Dict[str, Any]]] = None) -> None:
        menu = self.build_all_roots(selection_callback=selection_callback, context_provider=context_provider)
        pos = anchor.mapToGlobal(QtCore.QPoint(0, anchor.height()))
        menu.exec(pos)

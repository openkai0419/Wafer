from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....core.db.query import FileSearchEngine
from ....plugin.query.composer import SearchComposer
from ....core.lang.manager import t
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.icon_engine import themed_icon
from ....core.qt.thread import utility_pool
from ....core.commands.bridge import ActionKit, Menu
from ....plugin.query.handler import filter_registry, sort_registry
from ....plugin.query.base import KeyStore
from ....builtins.filters import TextFilter, DirectoryFilter, ContainedFilesFilter


class FilterRow(QtWidgets.QWidget):
    changed = QtCore.Signal()
    remove_requested = QtCore.Signal(object)
    context_requested = QtCore.Signal(object, QtCore.QPoint)
    param_selection_requested = QtCore.Signal(object, object)

    def __init__(self, filter_cls, show_op=True, key_store=None, parent=None):
        super().__init__(parent)
        self._filter_cls = None
        self._param_widget = None
        self._key_store = key_store
        self._has_op = show_op
        self._enabled = True
        self._build_ui(show_op)
        self._set_filter_type(filter_cls)

    def _build_ui(self, show_op: bool):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(2))

        self.op_combo = QtWidgets.QComboBox()
        self.op_combo.addItem("AND", "AND")
        self.op_combo.addItem("OR", "OR")
        self.op_combo.setSizeAdjustPolicy(QtWidgets.QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.op_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        self.op_combo.setVisible(show_op)
        layout.addWidget(self.op_combo)

        self._widget_placeholder = QtWidgets.QWidget()
        layout.addWidget(self._widget_placeholder, 1)

        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setIcon(themed_icon("cross"))
        self.remove_button.setFixedSize(dpix(24), dpix(24))
        self.remove_button.setContextMenuPolicy(QtCore.Qt.CustomContextMenu)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        self.remove_button.customContextMenuRequested.connect(self._on_context_requested)
        layout.addWidget(self.remove_button)

    def _set_filter_type(self, cls):
        self._filter_cls = cls
        if self._param_widget:
            self._param_widget.setParent(None)
            self._param_widget.deleteLater()
            self._param_widget = None
        widget = cls.create_widget(self)
        if widget:
            self._param_widget = widget
            if hasattr(widget, "changed"):
                widget.changed.connect(self.changed)
            if hasattr(widget, "selection_requested"):
                widget.selection_requested.connect(lambda _source=None, w=widget: self.param_selection_requested.emit(self, w))
            if self._key_store:
                cls.bind_key_store(widget, self._key_store)
            self.layout().replaceWidget(self._widget_placeholder, widget)
            self._widget_placeholder.setParent(None)
            self._widget_placeholder = widget
        else:
            placeholder = QtWidgets.QWidget()
            self.layout().replaceWidget(self._widget_placeholder, placeholder)
            self._widget_placeholder.setParent(None)
            self._widget_placeholder = placeholder
        self._apply_enabled_visual()

    @property
    def filter_cls(self):
        return self._filter_cls

    @property
    def operator(self) -> str:
        return self.op_combo.currentData() or "AND"

    def read_entry(self) -> tuple | None:
        if not self._filter_cls or not self._enabled:
            return None
        params = self._filter_cls.read_params(self._param_widget) if self._param_widget else {}
        return (self._filter_cls, params, self.op_combo.currentData() if self._has_op else None)

    def read_params(self) -> dict:
        if not self._filter_cls or not self._param_widget:
            return {}
        return self._filter_cls.read_params(self._param_widget)

    def read_op(self) -> str | None:
        return self.op_combo.currentData() if self._has_op else None

    def is_enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if self._enabled == enabled:
            return
        self._enabled = enabled
        self._apply_enabled_visual()

    def _apply_enabled_visual(self):
        if self._param_widget:
            self._param_widget.setEnabled(self._enabled)
        self.op_combo.setEnabled(self._enabled)
        state = t("Enabled") if self._enabled else t("Disabled")
        self.remove_button.setToolTip(t("Remove filter") + "\n" + t("Right-click for row options") + f"\n{state}")

    def _on_context_requested(self, pos: QtCore.QPoint):
        self.context_requested.emit(self, self.remove_button.mapToGlobal(pos))

    def write_entry(self, filter_name: str, params: dict, op: str | None = None):
        cls = filter_registry.get(filter_name)
        if not cls or cls is not self._filter_cls:
            return
        if op and self._has_op:
            idx = self.op_combo.findData(op)
            if idx >= 0:
                self.op_combo.setCurrentIndex(idx)
        if self._param_widget and params:
            cls.write_params(self._param_widget, params)

    def set_op_visible(self, visible: bool):
        self._has_op = visible
        self.op_combo.setVisible(visible)

    def set_removable(self, removable: bool):
        self.remove_button.setVisible(removable)

    def get_param_widget(self):
        return self._param_widget


class SearchContainer(QtWidgets.QWidget):
    filter_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher(utility_pool)
        self._key_cancel = CancelSlot()
        self._key_store = KeyStore(self)
        self._last_paths = object()
        self._rows: list[FilterRow] = []
        self._sort_name = "none"
        self._ascending = False
        self._tools_host = None
        self._build_ui()
        self._add_row(TextFilter, emit=False)
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(dpix(2))

        self._filter_stack = QtWidgets.QVBoxLayout()
        self._filter_stack.setContentsMargins(0, 0, 0, 0)
        self._filter_stack.setSpacing(dpix(2))
        root.addLayout(self._filter_stack)

        self._sort_button = self._build_sort_button()
        self._add_button = self._build_add_button()

        self._empty_row = QtWidgets.QWidget(self)
        el = QtWidgets.QHBoxLayout(self._empty_row)
        el.setContentsMargins(0, 0, 0, 0)
        el.setSpacing(dpix(2))
        self._empty_row.hide()
        root.addWidget(self._empty_row)

    def _build_sort_button(self) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setIcon(themed_icon("sort"))
        btn.setFixedSize(dpix(28), dpix(24))
        btn.clicked.connect(self._show_sort_menu)
        return btn

    def _build_add_button(self) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setIcon(themed_icon("plus"))
        btn.setFixedHeight(dpix(24))
        btn.setMinimumWidth(dpix(28))
        btn.clicked.connect(self._on_add_clicked)
        return btn

    def _show_sort_menu(self):
        self._build_sort_menu().exec(self._sort_button.mapToGlobal(QtCore.QPoint(0, self._sort_button.height())))

    def _build_sort_menu(self) -> QtWidgets.QMenu:
        spec = Menu.session(self).menu(self._sort_menu_items())
        menu = spec.build() if spec is not None else None
        return menu if menu is not None else QtWidgets.QMenu(self)

    def _sort_menu_items(self) -> list:
        uid = f"{id(self):x}"
        items = [":Sort"]
        items.extend(
            ActionKit.Action(
                path=f"inline.search.{uid}.sort.{cls.NAME}",
                display=cls.NAME.capitalize(),
                checkable=True,
                default_checked=self._sort_name == cls.NAME,
                checked_resolver=lambda name=cls.NAME: self._sort_name == name,
                func=lambda ctx, name=cls.NAME: self._set_sort_name(name),
            )
            for cls in sort_registry.list_all()
        )
        items.extend(
            [
                "-",
                ":Order",
                ActionKit.Action(
                    path=f"inline.search.{uid}.order.ascending",
                    display="Ascending",
                    checkable=True,
                    default_checked=self._ascending,
                    checked_resolver=lambda: self._ascending,
                    func=lambda ctx: self._set_sort_order(True),
                ),
                ActionKit.Action(
                    path=f"inline.search.{uid}.order.descending",
                    display="Descending",
                    checkable=True,
                    default_checked=not self._ascending,
                    checked_resolver=lambda: not self._ascending,
                    func=lambda ctx: self._set_sort_order(False),
                ),
            ]
        )
        return items

    def _set_sort_name(self, sort_name: str):
        self._sort_name = sort_name
        self.filter_changed.emit()

    def _set_sort_order(self, ascending: bool):
        self._ascending = ascending
        self.filter_changed.emit()

    def _on_add_clicked(self):
        available = self._available_filter_classes()
        if len(available) <= 1:
            self._add_row(available[0] if available else TextFilter)
            return
        uid = f"{id(self):x}"
        items = [
            ":Add Filter",
            *[
                ActionKit.Action(
                    path=f"inline.search.{uid}.add.{cls.NAME}",
                    display=cls.DISPLAY_NAME or cls.NAME,
                    func=lambda ctx, c=cls: self._add_row(c),
                )
                for cls in available
            ],
        ]
        spec = Menu.session(self).menu(items)
        if spec is not None:
            spec.exec(self._add_button.mapToGlobal(QtCore.QPoint(0, self._add_button.height())))

    def _available_filter_classes(self) -> list[type]:
        return [c for c in filter_registry.list_all() if c is not DirectoryFilter and not getattr(c, "INTERNAL_FILTER", False)]

    def _collect_inherited_params(self, end_index: int | None = None) -> dict:
        merged = {}
        rows = self._rows if end_index is None else self._rows[: max(0, end_index)]
        for row in rows:
            if row.filter_cls and row.get_param_widget():
                params = row.filter_cls.read_params(row.get_param_widget())
                merged.update(row.filter_cls.inheritable_params(params))
        return merged

    def _add_row(self, filter_cls, emit=True):
        self._insert_row(len(self._rows), filter_cls, emit=emit)

    def _insert_row(self, index: int, filter_cls, emit=True):
        index = max(0, min(index, len(self._rows)))
        inherited = self._collect_inherited_params(index)
        row = FilterRow(filter_cls, show_op=index > 0, key_store=self._key_store, parent=self)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_remove_row)
        row.context_requested.connect(self._show_row_menu)
        row.param_selection_requested.connect(self._on_param_selection_requested)
        if inherited and row.get_param_widget():
            filter_cls.write_params(row.get_param_widget(), inherited)
        self._rows.insert(index, row)
        self._filter_stack.insertWidget(index, row)
        self._update_op_visibility()
        self._update_tool_placement()
        if emit:
            self.filter_changed.emit()

    def _on_remove_row(self, row):
        if row not in self._rows:
            return
        if self._tools_host is row:
            self._detach_tools()
        self._rows.remove(row)
        self._filter_stack.removeWidget(row)
        row.setParent(None)
        row.deleteLater()
        self._update_op_visibility()
        self._update_tool_placement()
        self.filter_changed.emit()

    def _on_row_changed(self):
        self.filter_changed.emit()

    def _on_param_selection_requested(self, active_row: FilterRow, active_widget: QtWidgets.QWidget):
        for row in self._rows:
            widget = row.get_param_widget()
            if row is active_row or widget is active_widget or not hasattr(widget, "clear_selection"):
                continue
            widget.clear_selection()

    def selected_param_widget(self, filter_name: str | None = None) -> QtWidgets.QWidget | None:
        for row in self._rows:
            if filter_name is not None and getattr(row.filter_cls, "NAME", None) != filter_name:
                continue
            widget = row.get_param_widget()
            if widget is not None and hasattr(widget, "has_selection") and widget.has_selection():
                return widget
        return None

    def _show_row_menu(self, row: FilterRow, global_pos: QtCore.QPoint):
        self._build_row_menu(row).exec(global_pos)

    def _build_row_menu(self, row: FilterRow) -> QtWidgets.QMenu:
        index = self._rows.index(row) if row in self._rows else -1
        uid = f"{id(self):x}.{id(row):x}"
        items = [
            ":Filter Menu",
            ActionKit.Action(
                path=f"inline.filter.{uid}.enabled",
                display="Enabled",
                checkable=True,
                default_checked=row.is_enabled(),
                checked_resolver=lambda r=row: r.is_enabled(),
                func=lambda ctx, r=row: self._set_row_enabled(r, bool(ctx.get("checked"))),
            ),
            "-",
        ]
        items.extend(
            ActionKit.Action(
                path=f"Add filter after this/inline.filter.{uid}.add.{cls.NAME}",
                display=cls.DISPLAY_NAME or cls.NAME,
                func=lambda ctx, r=row, c=cls: self._add_row_after(r, c),
            )
            for cls in self._available_filter_classes()
        )
        items.append("-")
        if index > 0:
            items.extend(
                [
                    ActionKit.Action(path=f"inline.filter.{uid}.move_up", display="Move up", func=lambda ctx, r=row: self._move_row_by(r, -1)),
                    ActionKit.Action(path=f"inline.filter.{uid}.move_top", display="Move to top", func=lambda ctx, r=row: self._move_row(r, 0)),
                ]
            )
        if 0 <= index < len(self._rows) - 1:
            items.extend(
                [
                    ActionKit.Action(path=f"inline.filter.{uid}.move_down", display="Move down", func=lambda ctx, r=row: self._move_row_by(r, 1)),
                    ActionKit.Action(path=f"inline.filter.{uid}.move_bottom", display="Move to bottom", func=lambda ctx, r=row: self._move_row(r, len(self._rows) - 1)),
                ]
            )
        items.extend(
            [
                "-",
                ActionKit.Action(path=f"inline.filter.{uid}.delete", display="Delete filter", func=lambda ctx, r=row: self._on_remove_row(r)),
            ]
        )
        spec = Menu.session(self).menu(items)
        menu = spec.build() if spec is not None else None
        return menu if menu is not None else QtWidgets.QMenu(self)

    def _set_row_enabled(self, row: FilterRow, enabled: bool):
        if row not in self._rows:
            return
        row.set_enabled(enabled)
        self.filter_changed.emit()

    def _toggle_row_enabled(self, row: FilterRow):
        self._set_row_enabled(row, not row.is_enabled())

    def _add_row_after(self, row: FilterRow, filter_cls):
        if row not in self._rows:
            return
        self._insert_row(self._rows.index(row) + 1, filter_cls)

    def _move_row(self, row: FilterRow, new_index: int, emit=True):
        if row not in self._rows:
            return
        old_index = self._rows.index(row)
        new_index = max(0, min(new_index, len(self._rows) - 1))
        if old_index == new_index:
            return
        if self._tools_host is row:
            self._detach_tools()
        self._filter_stack.removeWidget(row)
        self._rows.pop(old_index)
        self._rows.insert(new_index, row)
        self._filter_stack.insertWidget(new_index, row)
        self._update_op_visibility()
        self._update_tool_placement()
        if emit:
            self.filter_changed.emit()

    def _move_row_by(self, row: FilterRow, offset: int):
        if row not in self._rows:
            return
        self._move_row(row, self._rows.index(row) + offset)

    def _update_op_visibility(self):
        for i, row in enumerate(self._rows):
            row.set_op_visible(i > 0)

    def _detach_tools(self):
        for btn in (self._sort_button, self._add_button):
            parent = btn.parentWidget()
            if parent and parent is not self:
                layout = parent.layout()
                if layout:
                    layout.removeWidget(btn)
                btn.setParent(self)
                btn.hide()
        self._tools_host = None

    def _update_tool_placement(self):
        target = self._rows[-1] if self._rows else None
        if target is not None and target is self._tools_host:
            return
        self._detach_tools()
        if target:
            idx = target.layout().indexOf(target.remove_button)
            target.layout().insertWidget(idx, self._sort_button)
            target.layout().insertWidget(idx + 1, self._add_button)
            self._sort_button.show()
            self._add_button.show()
            self._add_button.setSizePolicy(QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            self._empty_row.hide()
            self._tools_host = target
        else:
            el = self._empty_row.layout()
            el.addWidget(self._sort_button)
            el.addWidget(self._add_button, 1)
            self._sort_button.show()
            self._add_button.show()
            self._add_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self._empty_row.show()
            self._tools_host = None

    def build_filter_entries(self, directories=None, include_subfolders=True, include_contained_files=True) -> list:
        entries = []
        for row in self._rows:
            entry = row.read_entry()
            if entry is None:
                continue
            entries.append(entry)
        if directories:
            dir_params = {
                "directories": directories,
                "include_subfolders": include_subfolders,
            }
            entries.append((DirectoryFilter, dir_params, None))
        if not include_contained_files:
            entries.append((ContainedFilesFilter, {"include": False}, None))
        return entries

    def get_sort(self) -> tuple[str, bool]:
        return self._sort_name, self._ascending

    def set_sort(self, sort_by: str, ascending: bool):
        self._sort_name = sort_by
        self._ascending = ascending
        self._sync_sort_menu()

    def _sync_sort_menu(self):
        return

    def invalidate_key_cache(self):
        self._last_paths = object()

    @profiler.profile
    def run_folder_worker(self, dbname, paths, on_complete=None):
        key = tuple(paths) if paths else None
        if self._last_paths == key:
            if on_complete:
                on_complete()
            return
        self._last_paths = key
        cancel = self._key_cancel.renew()

        def task():
            engine = FileSearchEngine(dbname)
            composer = SearchComposer()
            entries = []
            if paths:
                entries.append((DirectoryFilter, {"directories": paths}, None))
            results = composer.list_all_keys(engine, entries, sort_by_freq=True)
            if cancel.is_cancelled():
                return

            def apply():
                self._key_store.set_data(results)
                if on_complete:
                    on_complete()

            self._dispatcher.invoke(apply)

        self._dispatcher.post(task, priority=6, cancel=cancel)

    def get_primary_row(self) -> FilterRow | None:
        return self._rows[0] if self._rows else None

    def get_bars(self) -> list[dict]:
        """Return current bars as plain dicts (filter, params, op, enabled)."""
        bars = []
        for row in self._rows:
            cls = row.filter_cls
            if not cls:
                continue
            bars.append(
                {
                    "filter": cls.NAME,
                    "params": row.read_params(),
                    "op": row.read_op(),
                    "enabled": row.is_enabled(),
                }
            )
        return bars

    def save_state(self) -> dict:
        return {
            "bars": self.get_bars(),
            "sort_by": self._sort_name,
            "ascending": self._ascending,
        }

    def apply_bars(self, bars: list[dict], mode: str = "replace"):
        """Apply a bar preset. mode='replace' clears existing bars first; mode='append' adds them."""
        if mode not in ("replace", "append"):
            raise ValueError(f"invalid mode: {mode!r}")
        if mode == "replace":
            self._detach_tools()
            for row in list(self._rows):
                self._filter_stack.removeWidget(row)
                row.setParent(None)
                row.deleteLater()
            self._rows.clear()
        for rd in bars or []:
            filter_cls = filter_registry.get(rd.get("filter", "text"))
            if not filter_cls:
                continue
            is_first = len(self._rows) == 0
            row = FilterRow(
                filter_cls=filter_cls,
                show_op=not is_first,
                key_store=self._key_store,
                parent=self,
            )
            row.changed.connect(self._on_row_changed)
            row.remove_requested.connect(self._on_remove_row)
            row.context_requested.connect(self._show_row_menu)
            row.param_selection_requested.connect(self._on_param_selection_requested)
            if rd.get("params") and row.get_param_widget():
                row.filter_cls.write_params(row.get_param_widget(), rd["params"])
            if not is_first and rd.get("op"):
                idx = row.op_combo.findData(rd["op"])
                if idx >= 0:
                    row.op_combo.setCurrentIndex(idx)
            row.set_enabled(rd.get("enabled", True))
            self._rows.append(row)
            self._filter_stack.addWidget(row)
        self._update_op_visibility()
        self._update_tool_placement()
        self.filter_changed.emit()

    def restore_state(self, state: dict):
        sort_by = state.get("sort_by", "none")
        ascending = state.get("ascending", False)
        self.set_sort(sort_by, ascending)
        bars = state.get("bars")
        if bars:
            self.apply_bars(bars, mode="replace")

    def on_move_event(self):
        for row in self._rows:
            w = row.get_param_widget()
            if w and hasattr(w, "move_popup"):
                w.move_popup()

    def get_values(self) -> dict:
        primary = self.get_primary_row()
        if not primary:
            return {}
        params = primary.filter_cls.read_params(primary.get_param_widget()) if primary.get_param_widget() else {}
        params["sort_by"] = self._sort_name
        params["ascending"] = self._ascending
        return params

    def set_sort_by(self, key: str):
        self._sort_name = key
        self._sync_sort_menu()

    def set_ascending(self, ascending: bool):
        self._ascending = ascending
        self._sync_sort_menu()

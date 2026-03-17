from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets

from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
from ....core.db.query import FileSearchEngine
from ....plugin.query.composer import SearchComposer
from ....core.lang.manager import TranslatorMixin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.icon_engine import themed_icon
from ....core.qt.thread import utility_pool
from ....plugin.query.handler import filter_registry, sort_registry
from ....plugin.query.base import KeyStore
from ....builtins.filters import TextFilter, DirectoryFilter


class FilterRow(QtWidgets.QWidget):
    changed = QtCore.Signal()
    remove_requested = QtCore.Signal(object)

    def __init__(self, filter_cls, show_op=True, key_store=None, parent=None):
        super().__init__(parent)
        self._filter_cls = None
        self._param_widget = None
        self._key_store = key_store
        self._has_op = show_op
        self._build_ui(show_op)
        self._set_filter_type(filter_cls)

    def _build_ui(self, show_op: bool):
        layout = QtWidgets.QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))

        self.op_combo = QtWidgets.QComboBox()
        self.op_combo.addItem('AND', 'AND')
        self.op_combo.addItem('OR', 'OR')
        self.op_combo.setFixedWidth(dpix(56))
        self.op_combo.currentIndexChanged.connect(lambda: self.changed.emit())
        self.op_combo.setVisible(show_op)
        layout.addWidget(self.op_combo)

        self._widget_placeholder = QtWidgets.QWidget()
        layout.addWidget(self._widget_placeholder, 1)

        self.remove_button = QtWidgets.QToolButton()
        self.remove_button.setIcon(themed_icon('cross'))
        self.remove_button.setFixedSize(dpix(24), dpix(24))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
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
            if hasattr(widget, 'changed'):
                widget.changed.connect(self.changed)
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

    @property
    def filter_cls(self):
        return self._filter_cls

    @property
    def operator(self) -> str:
        return self.op_combo.currentData() or 'AND'

    def read_entry(self) -> tuple | None:
        if not self._filter_cls:
            return None
        params = self._filter_cls.read_params(self._param_widget) if self._param_widget else {}
        return (self._filter_cls, params, self.op_combo.currentData() if self._has_op else None)

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


class SearchContainer(QtWidgets.QWidget, TranslatorMixin):
    filter_changed = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._dispatcher = Dispatcher(utility_pool)
        self._key_cancel = CancelSlot()
        self._key_store = KeyStore(self)
        self._last_paths = object()
        self._rows: list[FilterRow] = []
        self._sort_name = 'path'
        self._ascending = False
        self._tools_host = None
        self._build_ui()
        self._add_row(TextFilter, emit=False)

    def update_translation(self):
        for action in self._order_group.actions():
            if action.data() is True:
                action.setText(self.t.tr('Ascending'))
            else:
                action.setText(self.t.tr('Descending'))

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
        el.setSpacing(dpix(4))
        self._empty_row.hide()
        root.addWidget(self._empty_row)

    def _build_sort_button(self) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        btn.setIcon(themed_icon('sort'))
        btn.setFixedSize(dpix(28), dpix(24))

        menu = QtWidgets.QMenu(btn)

        self._sort_group = QtGui.QActionGroup(menu)
        self._sort_group.setExclusive(True)
        for cls in sort_registry.list_all():
            action = menu.addAction(cls.NAME.capitalize())
            action.setData(cls.NAME)
            action.setCheckable(True)
            if cls.NAME == self._sort_name:
                action.setChecked(True)
            self._sort_group.addAction(action)

        menu.addSeparator()

        self._order_group = QtGui.QActionGroup(menu)
        self._order_group.setExclusive(True)
        asc_action = menu.addAction(self.t.tr('Ascending'))
        asc_action.setData(True)
        asc_action.setCheckable(True)
        self._order_group.addAction(asc_action)
        desc_action = menu.addAction(self.t.tr('Descending'))
        desc_action.setData(False)
        desc_action.setCheckable(True)
        desc_action.setChecked(True)
        self._order_group.addAction(desc_action)

        self._sort_group.triggered.connect(self._on_sort_action)
        self._order_group.triggered.connect(self._on_order_action)

        btn.setMenu(menu)
        return btn

    def _build_add_button(self) -> QtWidgets.QToolButton:
        btn = QtWidgets.QToolButton(self)
        btn.setIcon(themed_icon('plus'))
        btn.setFixedHeight(dpix(24))
        btn.setMinimumWidth(dpix(28))
        btn.clicked.connect(self._on_add_clicked)
        return btn

    def _on_sort_action(self, action):
        self._sort_name = action.data()
        self.filter_changed.emit()

    def _on_order_action(self, action):
        self._ascending = action.data()
        self.filter_changed.emit()

    def _on_add_clicked(self):
        available = [c for c in filter_registry.list_all() if c is not DirectoryFilter]
        if len(available) <= 1:
            self._add_row(available[0] if available else TextFilter)
            return
        menu = QtWidgets.QMenu(self._add_button)
        for cls in available:
            label = cls.DISPLAY_NAME or cls.NAME
            action = menu.addAction(label)
            action.triggered.connect(lambda checked=False, c=cls: self._add_row(c))
        menu.exec(self._add_button.mapToGlobal(
            QtCore.QPoint(0, self._add_button.height())))

    def _collect_inherited_params(self) -> dict:
        merged = {}
        for row in self._rows:
            if row.filter_cls and row.get_param_widget():
                params = row.filter_cls.read_params(row.get_param_widget())
                merged.update(row.filter_cls.inheritable_params(params))
        return merged

    def _add_row(self, filter_cls, emit=True):
        inherited = self._collect_inherited_params()
        is_first = len(self._rows) == 0
        row = FilterRow(filter_cls, show_op=not is_first, key_store=self._key_store, parent=self)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_remove_row)
        if inherited and row.get_param_widget():
            filter_cls.write_params(row.get_param_widget(), inherited)
        self._rows.append(row)
        self._filter_stack.addWidget(row)
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
            self._add_button.setSizePolicy(
                QtWidgets.QSizePolicy.Fixed, QtWidgets.QSizePolicy.Fixed)
            self._empty_row.hide()
            self._tools_host = target
        else:
            el = self._empty_row.layout()
            el.addWidget(self._sort_button)
            el.addWidget(self._add_button, 1)
            self._sort_button.show()
            self._add_button.show()
            self._add_button.setSizePolicy(
                QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
            self._empty_row.show()
            self._tools_host = None

    def build_filter_entries(self, directories=None, include_subfolders=True) -> list:
        entries = []
        for row in self._rows:
            entry = row.read_entry()
            if entry is None:
                continue
            entries.append(entry)
        if directories:
            dir_params = {
                'directories': directories,
                'include_subfolders': include_subfolders,
            }
            entries.append((DirectoryFilter, dir_params, None))
        return entries

    def get_sort(self) -> tuple[str, bool]:
        return self._sort_name, self._ascending

    def set_sort(self, sort_by: str, ascending: bool):
        self._sort_name = sort_by
        self._ascending = ascending
        self._sync_sort_menu()

    def _sync_sort_menu(self):
        for action in self._sort_group.actions():
            action.setChecked(action.data() == self._sort_name)
        for action in self._order_group.actions():
            action.setChecked(action.data() == self._ascending)

    def invalidate_key_cache(self):
        self._last_paths = object()

    @profiler.profile
    def run_folder_worker(self, dbname, paths):
        key = tuple(paths) if paths else None
        if self._last_paths == key:
            return
        self._last_paths = key
        cancel = self._key_cancel.renew()

        def task():
            engine = FileSearchEngine(dbname)
            composer = SearchComposer()
            entries = []
            if paths:
                entries.append((DirectoryFilter, {'directories': paths}, None))
            results = composer.list_all_keys(engine, entries, sort_by_freq=True)
            if cancel.is_cancelled():
                return
            self._dispatcher.invoke(lambda: self._key_store.set_data(results))

        self._dispatcher.post(task, priority=6, cancel=cancel)

    def get_primary_row(self) -> FilterRow | None:
        return self._rows[0] if self._rows else None

    def save_state(self) -> dict:
        rows_data = []
        for row in self._rows:
            entry = row.read_entry()
            if entry is None:
                continue
            cls, params, op = entry
            rows_data.append({
                'filter': cls.NAME,
                'params': params,
                'op': op,
            })
        return {
            'rows': rows_data,
            'sort_by': self._sort_name,
            'ascending': self._ascending,
        }

    def restore_state(self, state: dict):
        sort_by = state.get('sort_by', 'path')
        ascending = state.get('ascending', True)
        self.set_sort(sort_by, ascending)

        rows_data = state.get('rows', [])
        if not rows_data:
            return
        self._detach_tools()
        for row in list(self._rows):
            self._filter_stack.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for i, rd in enumerate(rows_data):
            is_first = (i == 0)
            filter_cls = filter_registry.get(rd.get('filter', 'text'))
            if not filter_cls:
                continue
            row = FilterRow(
                filter_cls=filter_cls,
                show_op=not is_first,
                key_store=self._key_store,
                parent=self,
            )
            row.changed.connect(self._on_row_changed)
            row.remove_requested.connect(self._on_remove_row)
            if rd.get('params') and row.get_param_widget():
                row.filter_cls.write_params(row.get_param_widget(), rd['params'])
            if not is_first and rd.get('op'):
                idx = row.op_combo.findData(rd['op'])
                if idx >= 0:
                    row.op_combo.setCurrentIndex(idx)
            self._rows.append(row)
            self._filter_stack.addWidget(row)

        self._update_tool_placement()

    def on_move_event(self):
        for row in self._rows:
            w = row.get_param_widget()
            if w and hasattr(w, 'move_popup'):
                w.move_popup()

    def get_values(self) -> dict:
        primary = self.get_primary_row()
        if not primary:
            return {}
        params = primary.filter_cls.read_params(primary.get_param_widget()) if primary.get_param_widget() else {}
        params['sort_by'] = self._sort_name
        params['ascending'] = self._ascending
        return params

    def set_search_text(self, text: str):
        primary = self.get_primary_row()
        if primary and primary.get_param_widget():
            w = primary.get_param_widget()
            if hasattr(w, 'search_bar'):
                w.search_bar.setText(text)

    def set_sort_by(self, key: str):
        self._sort_name = key
        self._sync_sort_menu()

    def set_ascending(self, ascending: bool):
        self._ascending = ascending
        self._sync_sort_menu()

    def set_query_mode(self, mode: str):
        primary = self.get_primary_row()
        if primary and primary.get_param_widget():
            primary.filter_cls.write_params(primary.get_param_widget(), {'query_mode': mode})

    def set_keyword_mode(self, mode: str):
        primary = self.get_primary_row()
        if primary and primary.get_param_widget():
            primary.filter_cls.write_params(primary.get_param_widget(), {'keyword_mode': mode})

    def set_keyword_delimiter(self, text: str):
        primary = self.get_primary_row()
        if primary and primary.get_param_widget():
            primary.filter_cls.write_params(primary.get_param_widget(), {'keyword_separator': text})

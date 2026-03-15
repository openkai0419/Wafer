from __future__ import annotations

from PySide6 import QtCore, QtWidgets

from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....utils.logs import AppLogger
from ....core.db.query import FileSearchEngine
from ....plugin.query.composer import SearchComposer
from ....core.lang.manager import TranslatorMixin
from ....core.qt.dispatcher import Dispatcher, CancelSlot
from ....core.qt.thread import utility_pool
from ....plugin.query.handler import filter_registry, sort_registry
from ....plugin.query.base import KeyStore
from ....plugin.query.builtin import TextFilter, DirectoryFilter


class FilterRow(QtWidgets.QWidget):
    changed = QtCore.Signal()
    remove_requested = QtCore.Signal(object)

    def __init__(self, filter_cls=None, show_op=True, key_store=None, parent=None):
        super().__init__(parent)
        self._filter_cls = None
        self._param_widget = None
        self._key_store = key_store
        self._has_op = show_op
        self._build_ui(show_op)
        if filter_cls:
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

        self.type_combo = QtWidgets.QComboBox()
        self._populate_type_combo()
        self.type_combo.setFixedWidth(dpix(80))
        self.type_combo.currentIndexChanged.connect(self._on_type_changed)
        layout.addWidget(self.type_combo)

        self._widget_placeholder = QtWidgets.QWidget()
        layout.addWidget(self._widget_placeholder, 1)

        self.remove_button = QtWidgets.QPushButton('\u00D7')
        self.remove_button.setFixedSize(dpix(24), dpix(24))
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_button)

    def _populate_type_combo(self):
        for cls in filter_registry.list_all():
            if cls is DirectoryFilter:
                continue
            label = cls.DISPLAY_NAME or cls.NAME
            self.type_combo.addItem(label, cls.NAME)

    def _on_type_changed(self):
        name = self.type_combo.currentData()
        cls = filter_registry.get(name)
        if cls and cls is not self._filter_cls:
            self._set_filter_type(cls)
            self.changed.emit()

    def _set_filter_type(self, cls):
        self._filter_cls = cls
        idx = self.type_combo.findData(cls.NAME)
        if idx >= 0 and self.type_combo.currentIndex() != idx:
            self.type_combo.blockSignals(True)
            self.type_combo.setCurrentIndex(idx)
            self.type_combo.blockSignals(False)
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
        if not cls:
            return
        self._set_filter_type(cls)
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
        self._build_ui()
        self._add_default_row()

    def update_translation(self):
        self.add_button.setText(self.t.tr('+ Filter'))

    def _build_ui(self):
        root = QtWidgets.QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(dpix(4))

        self._filter_stack = QtWidgets.QVBoxLayout()
        self._filter_stack.setContentsMargins(0, 0, 0, 0)
        self._filter_stack.setSpacing(dpix(2))
        root.addLayout(self._filter_stack)

        self._tool_row = self._build_tool_row()
        root.addLayout(self._tool_row)

    def _build_tool_row(self) -> QtWidgets.QHBoxLayout:
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(dpix(4))

        self.sort_combo = QtWidgets.QComboBox()
        for cls in sort_registry.list_all():
            self.sort_combo.addItem(cls.NAME.capitalize(), cls.NAME)
        self.sort_combo.currentIndexChanged.connect(lambda: self.filter_changed.emit())
        layout.addWidget(self.sort_combo)

        self.order_combo = QtWidgets.QComboBox()
        self.order_combo.addItem(self.t.tr('Ascending'), True)
        self.order_combo.addItem(self.t.tr('Descending'), False)
        self.order_combo.setCurrentIndex(1)
        self.order_combo.currentIndexChanged.connect(lambda: self.filter_changed.emit())
        layout.addWidget(self.order_combo)

        layout.addStretch(1)

        self.add_button = QtWidgets.QPushButton(self.t.tr('+ Filter'))
        self.add_button.setFixedHeight(dpix(24))
        self.add_button.clicked.connect(self._on_add_filter)
        layout.addWidget(self.add_button)

        return layout

    def _add_default_row(self):
        row = FilterRow(TextFilter, show_op=False, key_store=self._key_store, parent=self)
        row.set_removable(False)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_remove_row)
        self._rows.append(row)
        self._filter_stack.addWidget(row)

    def _on_add_filter(self):
        row = FilterRow(TextFilter, show_op=True, key_store=self._key_store, parent=self)
        row.set_removable(True)
        row.changed.connect(self._on_row_changed)
        row.remove_requested.connect(self._on_remove_row)
        self._rows.append(row)
        self._filter_stack.addWidget(row)
        self.filter_changed.emit()

    def _on_remove_row(self, row):
        if row in self._rows:
            self._rows.remove(row)
            self._filter_stack.removeWidget(row)
            row.setParent(None)
            row.deleteLater()
            self.filter_changed.emit()

    def _on_row_changed(self):
        self.filter_changed.emit()

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
        sort_name = self.sort_combo.currentData() or 'path'
        ascending = self.order_combo.currentData()
        if ascending is None:
            ascending = True
        return sort_name, ascending

    def set_sort(self, sort_by: str, ascending: bool):
        idx = self.sort_combo.findData(sort_by)
        if idx >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(idx)
            self.sort_combo.blockSignals(False)
        asc_idx = self.order_combo.findData(ascending)
        if asc_idx >= 0:
            self.order_combo.blockSignals(True)
            self.order_combo.setCurrentIndex(asc_idx)
            self.order_combo.blockSignals(False)

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
        for i, row in enumerate(self._rows):
            entry = row.read_entry()
            if entry is None:
                continue
            cls, params, op = entry
            rows_data.append({
                'filter': cls.NAME,
                'params': params,
                'op': op,
            })
        sort_by, ascending = self.get_sort()
        return {
            'rows': rows_data,
            'sort_by': sort_by,
            'ascending': ascending,
        }

    def restore_state(self, state: dict):
        rows_data = state.get('rows', [])
        if not rows_data:
            return
        for row in list(self._rows):
            row.setParent(None)
            row.deleteLater()
        self._rows.clear()

        for i, rd in enumerate(rows_data):
            is_first = (i == 0)
            row = FilterRow(
                filter_cls=filter_registry.get(rd.get('filter', 'text')),
                show_op=not is_first,
                key_store=self._key_store,
                parent=self,
            )
            row.set_removable(not is_first)
            row.changed.connect(self._on_row_changed)
            row.remove_requested.connect(self._on_remove_row)
            if rd.get('params'):
                row.filter_cls.write_params(row.get_param_widget(), rd['params'])
            if not is_first and rd.get('op'):
                idx = row.op_combo.findData(rd['op'])
                if idx >= 0:
                    row.op_combo.setCurrentIndex(idx)
            self._rows.append(row)
            self._filter_stack.addWidget(row)

        sort_by = state.get('sort_by', 'path')
        ascending = state.get('ascending', True)
        self.set_sort(sort_by, ascending)

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
        sort_by, ascending = self.get_sort()
        params['sort_by'] = sort_by
        params['ascending'] = ascending
        return params

    def set_search_text(self, text: str):
        primary = self.get_primary_row()
        if primary and primary.get_param_widget():
            w = primary.get_param_widget()
            if hasattr(w, 'search_bar'):
                w.search_bar.setText(text)

    def set_sort_by(self, key: str):
        idx = self.sort_combo.findData(key)
        if idx >= 0:
            self.sort_combo.blockSignals(True)
            self.sort_combo.setCurrentIndex(idx)
            self.sort_combo.blockSignals(False)

    def set_ascending(self, ascending: bool):
        idx = self.order_combo.findData(ascending)
        if idx >= 0:
            self.order_combo.blockSignals(True)
            self.order_combo.setCurrentIndex(idx)
            self.order_combo.blockSignals(False)

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

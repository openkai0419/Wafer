from PySide6 import QtCore, QtGui, QtWidgets
from source.utils.formatting import display_prefixed_key
from source.utils.profiling import profiler
from source.utils.logs import AppLogger
from source.core.db.query import FileSearchEngine, SearchQuery
from source.core.lang.manager import TranslatorMixin
from source.core.qt.thread import thread_pool
from ..viewer_settings import app_settings

class FilterKeySignals(QtCore.QObject):
    finished = QtCore.Signal(list)

class FilterKeyUpdateWorker(QtCore.QRunnable):

    def __init__(self, db_name, selected_path):
        super().__init__()
        self.signals = FilterKeySignals()
        self.engine = FileSearchEngine(db_name)
        self.selected_path = selected_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.Slot()
    def run(self):
        if self._cancelled:
            return
        query = SearchQuery(directories=self.selected_path)
        results = self.engine.list_all_keys(query, sort_by_freq=True)
        if not self._cancelled:
            self.signals.finished.emit(results)

class CheckableCombo(QtWidgets.QToolButton, TranslatorMixin):
    action_changed = QtCore.Signal()

    def __init__(self, items=None, parent=None):
        super().__init__(parent)
        self.setText(self.t.tr(' Filter '))
        self.setPopupMode(QtWidgets.QToolButton.InstantPopup)
        self.menu = QtWidgets.QMenu(self)
        self.actions = []
        self.default_key = '__filepath__'
        self.previous_key = app_settings.get('query/keys', [self.default_key])
        if items:
            for name, data in items:
                self.add_item(name, data)
        self.setMenu(self.menu)

    def add_item(self, label, data):
        action = QtGui.QAction(label, self)
        action.setData(data)
        action.setCheckable(True)
        if data in self.previous_key:
            action.setChecked(True)
        action.toggled.connect(self.on_key_changed)
        self.menu.addAction(action)
        self.actions.append(action)

    @QtCore.Slot(list)
    def remake(self, datas):
        self.setUpdatesEnabled(False)
        self.menu.clear()
        self.actions.clear()
        for key, count in datas:
            self.add_item(f'{display_prefixed_key(key)} ({count})', key)
        if not self.checked_items():
            for a in self.actions:
                if a.data() == self.default_key:
                    a.setChecked(True)
                    break
        self.setUpdatesEnabled(True)

    def on_key_changed(self):
        self.previous_key = self.checked_items()
        app_settings.set('query/keys', self.previous_key)
        self.action_changed.emit()

    def checked_items(self):
        return [a.data() for a in self.actions if a.isChecked()]

class SearchOptionPopup(QtWidgets.QDialog, TranslatorMixin):
    settingchanged = QtCore.Signal()

    def __init__(self, pos_parent, parent=None):
        super().__init__(parent)
        self.pos_parent = pos_parent
        self.setWindowTitle(self.t.tr('Search Options'))
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.Tool)
        self.setLayout(QtWidgets.QVBoxLayout())
        self.build_ui()
        self.restore_settings()

    def build_ui(self):
        layout = self.layout()
        self.query_type_combo = QtWidgets.QComboBox()
        self.query_type_combo.addItem('GLOB', 'GLOB')
        self.query_type_combo.addItem('LIKE', 'LIKE')
        self.query_type_combo.currentIndexChanged.connect(lambda: self.settingchanged.emit())
        layout.addWidget(self.query_type_combo)
        self.keyword_group = QtWidgets.QButtonGroup(self)
        self.and_radio = QtWidgets.QRadioButton('AND')
        self.or_radio = QtWidgets.QRadioButton('OR')
        self.keyword_group.addButton(self.and_radio)
        self.keyword_group.addButton(self.or_radio)
        self.and_radio.toggled.connect(lambda: self.settingchanged.emit())
        self.or_radio.toggled.connect(lambda: self.settingchanged.emit())
        hlayout1 = QtWidgets.QHBoxLayout()
        hlayout1.addWidget(self.and_radio)
        hlayout1.addWidget(self.or_radio)
        layout.addLayout(hlayout1)
        hlayout3 = QtWidgets.QHBoxLayout()
        self.delimiter_input = QtWidgets.QLineEdit()
        self.delimiter_input.textChanged.connect(lambda: self.settingchanged.emit())
        hlayout3.addWidget(QtWidgets.QLabel(self.t.tr('Split by:')))
        hlayout3.addWidget(self.delimiter_input)
        layout.addLayout(hlayout3)
        layout.addWidget(QtWidgets.QLabel(self.t.tr('Sort:')))
        self.sort_by_combo = QtWidgets.QComboBox()
        self.sort_display_map = {'path': self.t.tr('Path'), 'name': self.t.tr('Name'), 'created': self.t.tr('Created'), 'modified': self.t.tr('Modified'), 'collected': self.t.tr('Collected'), 'size': self.t.tr('File Size'), 'random': self.t.tr('Random')}
        for key, label in self.sort_display_map.items():
            self.sort_by_combo.addItem(label, userData=key)
        self.sort_by_combo.currentIndexChanged.connect(lambda: self.settingchanged.emit())
        layout.addWidget(self.sort_by_combo)
        self.order_group = QtWidgets.QButtonGroup(self)
        self.asc_radio = QtWidgets.QRadioButton(self.t.tr('Ascending'))
        self.desc_radio = QtWidgets.QRadioButton(self.t.tr('Descending'))
        self.order_group.addButton(self.asc_radio)
        self.order_group.addButton(self.desc_radio)
        self.asc_radio.toggled.connect(lambda: self.settingchanged.emit())
        self.desc_radio.toggled.connect(lambda: self.settingchanged.emit())
        hlayout2 = QtWidgets.QHBoxLayout()
        hlayout2.addWidget(self.asc_radio)
        hlayout2.addWidget(self.desc_radio)
        layout.addLayout(hlayout2)

    def restore_settings(self):
        default_query = app_settings.get('query/query_mode', 'GLOB')
        index = self.query_type_combo.findData(default_query)
        self.query_type_combo.setCurrentIndex(index if index >= 0 else 0)
        keyword_mode = app_settings.get('query/keyword_mode', 'AND')
        (self.and_radio if keyword_mode == 'AND' else self.or_radio).setChecked(True)
        sort_by = app_settings.get('query/sort_by', 'path')
        index = self.sort_by_combo.findData(sort_by)
        self.sort_by_combo.setCurrentIndex(index if index >= 0 else 0)
        ascending = app_settings.get('query/ascending', False)
        (self.asc_radio if ascending else self.desc_radio).setChecked(True)
        self.delimiter_input.setText(app_settings.get('query/keyword_separator', ','))

    @profiler.profile
    def move_to(self):
        button_pos = self.pos_parent.mapToGlobal(QtCore.QPoint(0, self.pos_parent.height()))
        x = button_pos.x() + self.pos_parent.rect().width() - self.rect().width()
        y = button_pos.y()
        self.move(x, y)

    @profiler.profile
    def get_settings(self):
        sort_by = self.sort_by_combo.currentData()
        ascending = self.asc_radio.isChecked()
        kwargs = {'query_mode': self.query_type_combo.currentData(), 'keyword_mode': 'AND' if self.and_radio.isChecked() else 'OR', 'sort_by': sort_by, 'ascending': ascending}
        app_settings.set('query/query_mode', kwargs['query_mode'])
        app_settings.set('query/keyword_mode', kwargs['keyword_mode'])
        app_settings.set('query/sort_by', kwargs['sort_by'])
        app_settings.set('query/ascending', ascending)
        return kwargs

    def get_keyword_delimiter(self):
        return self.delimiter_input.text() or ','

    def _set_combo_silent(self, combo, data):
        idx = combo.findData(data)
        if idx < 0:
            return
        combo.blockSignals(True)
        combo.setCurrentIndex(idx)
        combo.blockSignals(False)

    def _set_radio_silent(self, radio):
        radio.blockSignals(True)
        radio.setChecked(True)
        radio.blockSignals(False)

    def set_sort_by(self, key: str):
        self._set_combo_silent(self.sort_by_combo, key)

    def set_query_mode(self, mode: str):
        self._set_combo_silent(self.query_type_combo, mode)

    def set_keyword_mode(self, mode: str):
        self._set_radio_silent(self.and_radio if mode == "AND" else self.or_radio)

    def set_ascending(self, ascending: bool):
        self._set_radio_silent(self.asc_radio if ascending else self.desc_radio)

    def set_keyword_delimiter(self, text: str):
        self.delimiter_input.setText(text)

class SearchOptionsBar(QtWidgets.QWidget, TranslatorMixin):
    settingchanged = QtCore.Signal()

    def __init__(self, parent=None):
        super().__init__(parent=parent)
        self._folder_worker = None
        self.setup()

    def setup(self):
        self.layout = QtWidgets.QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        self.setLayout(self.layout)
        self.search_bar = QtWidgets.QLineEdit()
        self.search_bar.setPlaceholderText(self.t.tr('Enter search terms...'))
        self.search_bar.setText(app_settings.get('query/keywords', None))
        self.search_bar.textChanged.connect(lambda: self.settingchanged.emit())
        self.option_button = QtWidgets.QPushButton(self.t.tr(' Options ▼ '))
        self.option_button.clicked.connect(self.toggle_option_popup)
        self.keys_combo = CheckableCombo()
        self.keys_combo.action_changed.connect(lambda: self.settingchanged.emit())
        self.layout.addWidget(self.keys_combo)
        self.layout.addWidget(self.search_bar)
        self.layout.addWidget(self.option_button)
        self.option_popup = SearchOptionPopup(self.option_button, self)
        self.option_popup.settingchanged.connect(lambda: self.settingchanged.emit())

    @profiler.profile
    def toggle_option_popup(self):
        if self.option_popup.isVisible():
            self.option_popup.hide()
        else:
            self.option_popup.move_to()
            self.option_popup.show()

    @profiler.profile
    def on_move_event(self):
        if self.option_popup and self.option_popup.isVisible():
            self.option_popup.move_to()

    @profiler.profile
    def run_folder_worker(self, dbname, paths):
        if self._folder_worker and self._folder_worker.selected_path == paths:
            return
        if self._folder_worker:
            self._folder_worker.cancel()
        self._folder_worker = FilterKeyUpdateWorker(dbname, paths)
        self._folder_worker.signals.finished.connect(self.keys_combo.remake)
        thread_pool.submit(self._folder_worker, 6)

    def set_search_text(self, text: str):
        self.search_bar.setText(text)

    def set_keyword_delimiter(self, text: str):
        self.option_popup.set_keyword_delimiter(text)

    def set_sort_by(self, key: str):
        self.option_popup.set_sort_by(key)

    def set_query_mode(self, mode: str):
        self.option_popup.set_query_mode(mode)

    def set_keyword_mode(self, mode: str):
        self.option_popup.set_keyword_mode(mode)

    def set_ascending(self, ascending: bool):
        self.option_popup.set_ascending(ascending)

    @profiler.profile
    def get_values(self):
        kwargs = self.option_popup.get_settings()
        keys = self.keys_combo.previous_key
        kwargs.update({'keys': keys if keys else app_settings.get('query/keys'), 'keywords': self.search_bar.text(), 'keyword_separator': self.option_popup.get_keyword_delimiter()})
        app_settings.set('query/keywords', kwargs['keywords'])
        app_settings.set('query/keyword_separator', kwargs['keyword_separator'])
        return kwargs

from PySide6 import QtCore, QtGui, QtWidgets
from ...common.profiling import profiler, logger
from ...db.query import MetaInfoSearchEngine, MetaQuery
from ...image_setting.translation import TranslatorMixin
from ...qt.thread import main_thread
from ..viewer_settings import main_setting

class FolderComboSignals(QtCore.QObject):
    finished = QtCore.Signal(list)

class FolderComboUpdateWorker(QtCore.QRunnable):

    def __init__(self, db_name, selected_path):
        super().__init__()
        self.signals = FolderComboSignals()
        self.engine = MetaInfoSearchEngine(db_name)
        self.selected_path = selected_path
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @QtCore.Slot()
    def run(self):
        if self._cancelled:
            return
        query = MetaQuery(directories=self.selected_path)
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
        self.previous_key = main_setting.get('query/keys', [self.default_key])
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
            self.add_item(f'{key} ({count})', key)
        if not self.checked_items():
            for a in self.actions:
                if a.data() == self.default_key:
                    a.setChecked(True)
                    break
        self.setUpdatesEnabled(True)

    def on_key_changed(self):
        self.previous_key = self.checked_items()
        main_setting.set('query/keys', self.previous_key)
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
        self.splittext = QtWidgets.QLineEdit()
        self.splittext.textChanged.connect(lambda: self.settingchanged.emit())
        hlayout3.addWidget(QtWidgets.QLabel(self.t.tr('Split by:')))
        hlayout3.addWidget(self.splittext)
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
        default_query = main_setting.get('query/query_mode', 'GLOB')
        index = self.query_type_combo.findData(default_query)
        self.query_type_combo.setCurrentIndex(index if index >= 0 else 0)
        keyword_mode = main_setting.get('query/keyword_mode', 'AND')
        (self.and_radio if keyword_mode == 'AND' else self.or_radio).setChecked(True)
        sort_by = main_setting.get('query/sort_by', 'path')
        index = self.sort_by_combo.findData(sort_by)
        self.sort_by_combo.setCurrentIndex(index if index >= 0 else 0)
        ascending = main_setting.get('query/ascending', False)
        (self.asc_radio if ascending else self.desc_radio).setChecked(True)
        self.splittext.setText(main_setting.get('query/splittext', ','))

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
        main_setting.set('query/query_mode', kwargs['query_mode'])
        main_setting.set('query/keyword_mode', kwargs['keyword_mode'])
        main_setting.set('query/sort_by', kwargs['sort_by'])
        main_setting.set('query/ascending', ascending)
        return kwargs

    def get_splittext(self):
        return self.splittext.text() or ','

class SingleRowOption(QtWidgets.QWidget, TranslatorMixin):
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
        self.search_bar.setText(main_setting.get('query/keywords', None))
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
        self._folder_worker = FolderComboUpdateWorker(dbname, paths)
        self._folder_worker.signals.finished.connect(self.keys_combo.remake)
        main_thread.start(self._folder_worker, 6)

    @profiler.profile
    def get_values(self):
        kwargs = self.option_popup.get_settings()
        keys = self.keys_combo.previous_key
        kwargs.update({'keys': keys if keys else main_setting.get('query/keys'), 'keywords': self.search_bar.text(), 'splittext': self.option_popup.get_splittext()})
        main_setting.set('query/keywords', kwargs['keywords'])
        main_setting.set('query/splittext', kwargs['splittext'])
        return kwargs

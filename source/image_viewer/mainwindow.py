from datetime import datetime, timedelta
from PySide6 import QtCore, QtWidgets
from ..actions.actions import ContextMenuBuilder, FolderContextMenuBuilder
from ..common.funcs import get_data_db, get_setting_db, get_setting_file_names, uipx
from ..common.profiling import logger, profiler
from ..constants import APP_NAME, default_db_name
from ..db.query import MetaInfoSearchEngine, MetaQuery
from ..db.setting_db import SettingDB
from ..image_setting.db_settings import DataBaseSettings
from ..image_setting.setting_window import SettingsWindow
from ..image_setting.translation import TranslatorMixin
from ..os.process import Proc
from ..qt.debounce import qt_debounce
from ..qt.dialog import ConfirmDialog, InputDialog
from ..qt.thread import main_thread
from ..zmq.zmq import MessageEnvelope, Role, ZMQNode
from .viewer.justifiedwidget import JustifiedVirtualScrollWidget
from .shower.data_viewer import ViewerWidget
from .viewer_settings import main_setting
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .widgets.foldertree import LazyFolderTreeView
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.progress_bar import ThinProgressBar
from .widgets.query_options import SingleRowOption
from .widgets.scrollarea import AutoScrollArea
from .widgets.table_combo import ComboBoxWithButtons

class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object, object)

class SearchWorkerRunnable(QtCore.QRunnable):

    def __init__(self, db_name, query):
        super().__init__()
        self.engine = MetaInfoSearchEngine(db_name)
        self.query = query
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def run(self):
        if self._cancelled:
            return
        try:
            paths, soruces, aspects = self.engine.get(self.query)
        except Exception as e:
            logger.exception(f'[SearchWorker] Search failed: {e}')
            return
        if self._cancelled:
            return
        self.signals.finished.emit(paths, soruces, aspects)

class MainWindow(QtWidgets.QMainWindow, TranslatorMixin):

    def __init__(self, icon=None, parent=None):
        super().__init__(parent=parent)
        logger.info(f'New Window Running : {APP_NAME}')
        if icon:
            self.setWindowIcon(icon)
        self.setWindowTitle(APP_NAME)
        self.resize(1000, 700)
        self.dbname = None
        self.dbpath = None
        self.setting_db = None
        self.current_runnable = None
        self._is_fullscreen = False
        self.run_folder = True
        self.query_timeout_threshold = timedelta(seconds=5)
        self.current_query_start_time = None
        self.query_lock = QtCore.QMutex()
        self.pending_query = None
        self.last_executed_query = None
        main_thread.watch_start()
        self.start_ipc_listener()
        self.t.set_locale(main_setting.get('window/language', 'en'))
        self.main_ui()
        self.reload_db(self.get_previous())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_close)

    @profiler.profile
    def get_previous(self):
        names = get_setting_file_names()
        if not names:
            return default_db_name
        prevname = main_setting.get('window/tablename', default_db_name)
        if prevname in names:
            return prevname
        elif len(names) >= 1:
            return names[0]

    @QtCore.Slot(str)
    def reload_db(self, name):
        if not main_setting.is_first_time('tree/state/reload'):
            self.folder_view.save_state(self.dbname)
        self.dbname = name
        self.dbpath = get_data_db(name)
        self.setting_db = SettingDB(get_setting_db(name))
        self.folder_view.set(self.setting_db.get_all_parent_folders(), self.setting_db.get_all_ignore_folders())
        QtCore.QTimer.singleShot(0, lambda: self.folder_view.restore_state(self.dbname))
        self.run_folder = True
        QtCore.QTimer.singleShot(0, lambda: self.search(force=True))
        self.progress_bar.setProgress(int(0))
        self.progress_bar.setMaximum(int(0))
        self.reload_combo()
        logger.info('[INFO] reload_db')

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.ActivationChange:
            if self.isActiveWindow():
                self.reload_combo()
            else:
                print('inactiveated window')
        super().changeEvent(event)

    @qt_debounce(200)
    def reload_combo(self):
        names = get_setting_file_names()
        if not names:
            names = ['default']
        self.dbcombo.setItems(names)
        self.dbcombo.setCurrentText(self.dbname)
        logger.debug('[DEBUG] reload_combo')

    def on_add_database(self):
        text = InputDialog.get_text(self.t.tr('Enter a name for the new table'), title=self.t.tr('Create New'), buttons=(self.t.tr('Create'), self.t.tr('Cancel')), parent=self)
        if text is not None:
            text = text.strip()
            logger.info(text)
            if not text:
                return
            elif text in get_setting_file_names():
                return
            else:
                Proc.new_main('--collector', text)
                self.dbcombo.addItem(text)
                self.dbcombo.setCurrentText(text)
                self.reload_db(text)

    def on_remove_database(self):
        if self.dbcombo.count() <= 1:
            return
        ret = ConfirmDialog.ask(self.t.trf('Delete table? : {dbname}', dbname=self.dbname), title=self.t.tr('Delete'), buttons=(self.t.tr('Delete'), self.t.tr('Cancel')), parent=self)
        if ret == self.t.tr('Delete'):
            self.setting_db.set_kv('deleteflag', True)
            self.dbcombo.removeItem(self.dbname)
            self.reload_db(self.dbcombo.currentText())

    @QtCore.Slot(int)
    def update_current(self, value):
        self.progress_bar.setProgress(int(value))

    @QtCore.Slot(int)
    def update_maximum(self, value):
        self.progress_bar.setMaximum(int(value))

    def start_ipc_listener(self):
        def on_message(env):
            table = env.table
            topic = env.topic
            message = env.message
            if table not in ('*', self.dbname):
                return
            handlers = {
                'update': lambda: QtCore.QMetaObject.invokeMethod(
                    self,
                    'search',
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(bool, True),
                ),
                'progress': lambda: QtCore.QMetaObject.invokeMethod(
                    self,
                    'update_current',
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(int, int(message)),
                ),
                'maximum': lambda: QtCore.QMetaObject.invokeMethod(
                    self,
                    'update_maximum',
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(int, int(message)),
                ),
                'folderchanged': lambda: QtCore.QMetaObject.invokeMethod(
                    self,
                    'reload_folderlist',
                    QtCore.Qt.QueuedConnection,
                ),
                'show_toggle': lambda: QtCore.QMetaObject.invokeMethod(
                    self,
                    'toggle_show',
                    QtCore.Qt.QueuedConnection,
                    QtCore.Q_ARG(bool, message == 'True'),
                ),
            }
            try:
                handlers.get(topic, lambda: None)()
            except Exception:
                logger.exception('Error processing IPC message: %s', env)
        self._subscriber = ZMQNode(Role.VIEWER, on_message=on_message, count='enable')
        self._subscriber.start()

    def toggle_language(self):
        new_locale = 'ja' if self.t.current_locale == 'en' else 'en'
        self.t.set_locale(new_locale)
        main_setting.save_important('window/language', new_locale)

    @profiler.profile
    def main_ui(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.folder_view = LazyFolderTreeView()
        self.menu_builder = FolderContextMenuBuilder(self.folder_view, self)
        self.folder_view.set_context_menu_builder(self.menu_builder)
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(uipx(4), uipx(4), uipx(0), uipx(6))
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        self.only_direct_children = main_setting.get('query/only_direct_children', False)
        self.iconbar = IconButtonBar(
            left_buttons=[
                IconButtonConfig('icons/settings.png', 'Settings', lambda: self.show_settings()),
                IconButtonConfig('icons/open.png', 'Add File', lambda: self.add_new_folder()),
            ],
            right_buttons=[
                IconButtonConfig(
                    'icons/save.png',
                    'Bot Only',
                    self.toggle_only_direct_children,
                    checkable=True,
                    checked=self.only_direct_children,
                ),
                IconButtonConfig('icons/save.png', 'AutoScroll', lambda: self.auto_scroll()),
                IconButtonConfig('icons/save.png', 'Full Screen', lambda: self.toggle_fullscreen()),
                IconButtonConfig('icons/save.png', 'Toggle Language', lambda: self.toggle_language()),
            ],
        )
        self.dbcombo = ComboBoxWithButtons()
        self.dbcombo.textChanged.connect(self.reload_db)
        self.dbcombo.addClicked.connect(self.on_add_database)
        self.dbcombo.removeClicked.connect(self.on_remove_database)

        self.progress_bar = ThinProgressBar()
        self.left_layout.addWidget(self.iconbar)
        self.left_layout.addWidget(self.progress_bar)
        self.left_layout.addWidget(self.folder_view)
        self.left_layout.addSpacing(uipx(3))
        self.left_layout.addWidget(self.dbcombo)

        mid_panel = QtWidgets.QWidget()
        self.mid_layout = QtWidgets.QVBoxLayout(mid_panel)
        self.mid_layout.setContentsMargins(uipx(4), uipx(4), uipx(4), uipx(4))
        self.mid_layout.setSpacing(uipx(6))
        self.search_row_widget = SingleRowOption()
        self.search_row_widget.settingchanged.connect(self.search)
        self.mid_layout.addWidget(self.search_row_widget)

        self.viewer = AutoScrollArea()
        self.viewer.setWidgetResizable(True)
        self.viewer.verticalScrollBar().setSingleStep(25)
        self.viewer.horizontalScrollBar().setSingleStep(25)
        self.content = JustifiedVirtualScrollWidget(self.viewer, self)
        viewer_menu = ContextMenuBuilder(self)
        self.content.set_context_menu_builder(viewer_menu)
        self.viewer.setWidget(self.content)
        self.viewer.resized.connect(self.content.on_resize_event)

        self.mid_layout.addWidget(self.viewer)
        self.splitter.addWidget(mid_panel)

        right_panel = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(uipx(0), uipx(12), uipx(8), uipx(8))
        self.right_layout.setSpacing(0)

        self.data_shower = ViewerWidget(self)
        
        self.right_layout.addWidget(self.data_shower)

        self.splitter.addWidget(right_panel)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        geo = main_setting.get('window/geometry', None)
        if geo:
            self.restoreGeometry(geo)
        sizes = main_setting.get('window/splitter', None)
        if sizes:
            self.splitter.setSizes(sizes)
        self.loading_indicator = OverlayLoadingIndicator(self.viewer)
        self.content.layout_ready.connect(self.loading_indicator.stop)

    @profiler.profile
    def add_new_folder(self):
        folder_path = QtWidgets.QFileDialog.getExistingDirectory(self, self.t.tr('Select folder'))
        if folder_path:
            self.setting_db.add_parent_folder(folder_path)
            self.folder_view.add_root(folder_path)

    @profiler.profile
    def build_search_query(self):
        kwargs = self.search_row_widget.get_values()
        kwargs.update({'directories': self.folder_view.get_selected_paths(), 'only_direct_children': self.only_direct_children})
        return MetaQuery(**kwargs)

    def show_settings(self):
        window = SettingsWindow(self)
        window.add_tab(DataBaseSettings())
        window.show()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        logger.debug('[RUNNING] reload_folderlist')
        self.folder_view.reload_tree()

    def toggle_only_direct_children(self, checked):
        logger.info(checked)
        self.only_direct_children = checked
        main_setting.set('query/only_direct_children', checked)
        self.search(force=True)

    def toggle_fullscreen(self):
        if not self._is_fullscreen:
            self.showFullScreen()
        else:
            self.showNormal()
        self._is_fullscreen = not self._is_fullscreen

    def moveEvent(self, event):
        super().moveEvent(event)
        self.search_row_widget.on_move_event()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.search_row_widget.on_move_event()

    def auto_scroll(self):
        if self.viewer.isscrolling():
            self.viewer.stop_auto_scroll()
        else:
            self.viewer.start_auto_scroll(1, 1)

    @profiler.profile
    def on_folder_selected(self):
        self.run_folder = True
        self.search()

    @QtCore.Slot(bool)
    def toggle_show(self, state):
        if state and self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()
        else:
            self.showMinimized()

    @qt_debounce(150)
    @QtCore.Slot(bool)
    @profiler.profile
    def search(self, force=False):
        logger.debug('[RUNNING] search')
        query = self.build_search_query()
        now = datetime.now()
        if not force:
            if self.current_runnable and query == self.current_runnable.query or (self.last_executed_query and query == self.last_executed_query):
                return
        with QtCore.QMutexLocker(self.query_lock):
            if self.current_runnable:
                elapsed = now - self.current_query_start_time if self.current_query_start_time else timedelta.max
                if elapsed < self.query_timeout_threshold:
                    self.current_runnable.cancel()
                else:
                    logger.info('[SEARCH] query is taking more than expected, continueing without cancel.')
                    self.pending_query = query
                    return
            self.pending_query = None
            self._start_search_runnable(query)

    @profiler.profile
    def _start_search_runnable(self, query):
        self.loading_indicator.start()
        runnable = SearchWorkerRunnable(self.dbpath, query)
        runnable.signals.finished.connect(self.on_search_finished)
        self.current_runnable = runnable
        main_thread.start(runnable, 7)

    @QtCore.Slot(object, object)
    @profiler.profile
    def on_search_finished(self, paths, soruces, aspects):
        self.last_executed_query = self.current_runnable.query
        self.current_runnable = None
        self.current_query_start_time = None
        self.content.set_paths(paths, soruces, aspects)
        if self.run_folder:
            self.search_row_widget.run_folder_worker(self.dbpath, self.folder_view.get_selected_paths())
            self.run_folder = False
        with QtCore.QMutexLocker(self.query_lock):
            if self.pending_query:
                query = self.pending_query
                self.pending_query = None
                self._start_search_runnable(query)

    def on_close(self):
        try:
            self.folder_view.save_state(self.dbname)
            main_setting.save_important('window/tablename', self.dbname)
            main_setting.set('window/geometry', self.saveGeometry())
            main_setting.set('viewer/scroll', self.content.get_center_image_index())
            main_setting.set('window/splitter', self.splitter.sizes())
            main_setting.commit()
            self.t.dump_missing_keys()
        except Exception as e:
            logger.warning(e)
        if hasattr(self, '_subscriber'):
            logger.info('on_close [STOPPING]')
            self._subscriber.stop()

    def closeEvent(self, event):
        return super().closeEvent(event)

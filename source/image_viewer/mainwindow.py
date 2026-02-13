from PySide6 import QtCore, QtWidgets
from ..common.funcs import get_data_db, get_setting_db, get_setting_file_names, uipx
from ..common.profiling import logger, profiler
from ..constants import APP_NAME, default_db_name
from ..db.setting_db import SettingDB
from ..lang.manager import TranslatorMixin
from ..qt.debounce import qt_debounce
from ..zmq.zmq import Role, ZMQNode
from .viewer.justifiedwidget import JustifiedGraphicsView
from .viewer.items import ViewerItems
from .commands.window_commands import restore_always_on_top
from .shower.data_model import DataViewModel
from .shower.data_viewer import ViewerWidget
from .viewer_settings import main_setting
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .widgets.foldertree import LazyFolderTreeView
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.overlay_stack import OverlayStack
from .widgets.progress_bar import ThinProgressBar
from .widgets.query_options import SingleRowOption
from .widgets.table_combo import ComboBoxWithButtons

from .commands.menu import MenuMenu
from .search import SearchService
from ..actions.bridge import UI, Command
MenuMenu.setup_menu()


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
        self._pre_fullscreen_snap = None
        self.run_folder = True
        self.search_service = SearchService(lambda: self.dbpath, parent=self)
        self.search_service.search_started.connect(self._on_search_started)
        self.search_service.search_finished.connect(self._on_search_finished)
        self.search_service.params_changed.connect(self._on_search_params_changed)
        UI.register_instance("SearchService", self.search_service)
        self.start_ipc_listener()
        self.t.set_locale(main_setting.get('window/language', 'en'))
        UI.register_instance("MainWindow", self)
        restore_always_on_top(self)
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
        self.search_service.reset_state()
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

    @QtCore.Slot(int)
    def update_current(self, value):
        self.progress_bar.setProgress(int(value))

    @QtCore.Slot(int)
    def update_maximum(self, value):
        self.progress_bar.setMaximum(int(value))

    def start_ipc_listener(self):
        def on_message(env):
            try:
                if not self or not hasattr(self, 'dbname'):
                    return
            except RuntimeError:
                return
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
            except RuntimeError:
                pass
            except Exception:
                logger.exception('Error processing IPC message: %s', env)
        self._subscriber = ZMQNode(Role.VIEWER, on_message=on_message, count='enable')
        self._subscriber.start()

    @profiler.profile
    def main_ui(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.folder_view = LazyFolderTreeView()
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(uipx(4), uipx(4), uipx(0), uipx(6))
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        self.iconbar = IconButtonBar(
            left_buttons=[
                IconButtonConfig('icons/settings.png', 'Settings', lambda: Command.invoke("win.show_settings")),
                IconButtonConfig('icons/open.png', 'Add File', lambda: Command.invoke("ft.add_folder")),
            ],
            right_buttons=[
                IconButtonConfig(
                    'icons/save.png',
                    'Include Subfolders',
                    lambda checked: Command.invoke("qry.toggle_include_subfolders"),
                    checkable=True,
                    checked=self.search_service.get('include_subfolders', True),
                ),
                IconButtonConfig('icons/save.png', 'Full Screen', lambda: Command.invoke("win.toggle_fullscreen")),
                IconButtonConfig('icons/save.png', 'Toggle Language', lambda: Command.invoke("win.toggle_language")),
            ],
        )
        self.dbcombo = ComboBoxWithButtons()
        self.dbcombo.textChanged.connect(self.reload_db)
        self.dbcombo.addClicked.connect(lambda: Command.invoke("db.add_database"))
        self.dbcombo.removeClicked.connect(lambda: Command.invoke("db.remove_database"))

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
        self.search_row_widget.settingchanged.connect(self._on_search_setting_changed)
        self.mid_layout.addWidget(self.search_row_widget)

        self.items = ViewerItems(self)
        self.content = JustifiedGraphicsView(self, self.items)
        self.content.verticalScrollBar().setSingleStep(25)
        self.content.horizontalScrollBar().setSingleStep(25)
        self.content.base_height_changed.connect(self._on_zoom_changed)

        self.mid_layout.addWidget(self.content)
        self.splitter.addWidget(mid_panel)

        right_panel = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(uipx(0), uipx(12), uipx(8), uipx(8))
        self.right_layout.setSpacing(0)

        self.data_model = DataViewModel(dbpath_getter=lambda: self.dbpath, parent=self)
        self.data_shower = ViewerWidget(self.data_model, self)
        UI.register_instance("ViewerWidget", self.data_shower)
        UI.register_instance("DataViewModel", self.data_model)
        UI.register_instance("ViewerItems", self.items)
        
        self.right_layout.addWidget(self.data_shower)

        self.splitter.addWidget(right_panel)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        geo = main_setting.get('window/geometry', None)
        if geo:
            self.restoreGeometry(geo)
        sizes = main_setting.get('window/splitter', [10, 800, 10])
        if sizes:
            self.splitter.setSizes(sizes)
        self.overlay_stack = OverlayStack(self.content)
        UI.register_instance("OverlayStack", self.overlay_stack)
        self.loading_indicator = OverlayLoadingIndicator()
        self.overlay_stack.push_persistent(self.loading_indicator, key="loading")
        self.content.layout_started.connect(self._on_layout_started)
        self.content.layout_ready.connect(lambda: self.overlay_stack.hide_persistent("loading"))
        self._sync_service_from_ui()

    def _sync_service_from_ui(self):
        values = self.search_row_widget.get_values()
        self.search_service.set_params({
            'keywords': values.get('keywords', ''),
            'query_mode': values.get('query_mode', 'GLOB'),
            'keyword_mode': values.get('keyword_mode', 'AND'),
            'sort_by': values.get('sort_by', 'path'),
            'ascending': values.get('ascending', True),
            'splittext': values.get('splittext', ','),
        })
        keys = values.get('keys') or main_setting.get('query/keys')
        self.search_service.set_keys(keys)
        self.search_service.set_directories(self.folder_view.get_selected_paths())
        from .commands.query_commands import sync_groups_from_args
        sync_groups_from_args(self.search_service.params)

    def _on_search_setting_changed(self):
        self._sync_service_from_ui()
        self.search_service.try_execute()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        logger.debug('[RUNNING] reload_folderlist')
        self.folder_view.reload_tree()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.search_row_widget.on_move_event()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.search_row_widget.on_move_event()

    def _on_zoom_changed(self):
        if self.content.isscrolling():
            speed = self.content.get_adjusted_scroll_speed()
            self.content._scroll_speed = speed

    @profiler.profile
    def on_folder_selected(self):
        self.run_folder = True
        self._folder_changed = True
        self.search_service.set_directories(self.folder_view.get_selected_paths())
        self.search_service.try_execute()

    @QtCore.Slot(bool)
    def toggle_show(self, state):
        if state and self.isMinimized():
            self.showNormal()
            self.raise_()
            self.activateWindow()
        else:
            self.showMinimized()

    @QtCore.Slot(bool)
    def search(self, force=False):
        self._sync_service_from_ui()
        self.search_service.execute(force=force)

    def _on_search_params_changed(self, changed):
        if 'include_subfolders' in changed:
            btn = self.iconbar.right_buttons[0]
            btn.blockSignals(True)
            btn.setChecked(changed['include_subfolders'])
            btn.blockSignals(False)

    def _show_loading(self):
        self.loading_indicator.start()
        self.overlay_stack.show_persistent("loading")

    def _on_layout_started(self):
        self._show_loading()

    def _on_search_started(self):
        self._show_loading()

    @QtCore.Slot(object, object, object)
    @profiler.profile
    def _on_search_finished(self, paths, sources, aspects):
        keep_scroll = not getattr(self, '_folder_changed', False)
        self._folder_changed = False
        self.content.set_paths(paths, sources, aspects, keep_scroll=keep_scroll)
        self.data_model.set_items(paths, sources)
        if self.run_folder:
            self.search_row_widget.run_folder_worker(self.dbpath, self.folder_view.get_selected_paths())
            self.run_folder = False

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


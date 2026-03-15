from PySide6 import QtCore, QtWidgets
from ...utils.paths import data_db_path, setting_db_path, list_setting_db_names
from ...utils.formatting import dpix
from ...core.color.theme import ThemeManager
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...constants import APP_NAME, DEV_MODE, DEFAULT_DB_NAME, DEFAULT_SESSION_NAME
from ...core.db.setting_db import SettingDB
from ...core.lang.manager import TranslatorMixin
from ...core.qt.rate_limit import qt_debounce
from ...core.ipc.node import Node
from .grid.grid_view import GridView
from .grid.items import GridItemModel
from .preview.file_model import FileViewModel
from .preview.file_viewer import FileViewerWidget
from .viewer_settings import app_settings
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .widgets.foldertree import LazyFolderTreeView
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.overlay_stack import OverlayStack
from .widgets.progress_bar import ThinProgressBar
from .widgets.search_container import SearchContainer
from .widgets.combo_with_buttons import ComboBoxWithButtons

from .commands.menu import AppMenuRegistrar
from .search import SearchService
from .session import QueryState, UIState, SessionEntry, SessionStore
from ...core.commands.bridge import UI, Command
from ...core.state import StateStore
from ...core.qt.window import WindowStateController
AppMenuRegistrar.setup_menu()


class MainWindow(QtWidgets.QMainWindow, TranslatorMixin):

    def __init__(self, icon=None, parent=None, session_id=None):
        super().__init__(parent=parent)
        self._session_store = SessionStore.instance()
        if session_id:
            self.session_id = session_id
            self._session_store.claim_session(session_id)
        else:
            inactive = self._session_store.find_inactive_session_id()
            if inactive:
                self.session_id = inactive
                self._session_store.claim_session(inactive)
            else:
                name = DEFAULT_SESSION_NAME if not self._session_store.list_sessions() else self._session_store.next_default_name()
                self.session_id = self._session_store.create_session_with_unique_name(name)
                self._session_store.claim_session(self.session_id)
        self._session_entry: SessionEntry | None = self._session_store.get_session(self.session_id)
        self._session_deleted = False
        AppLogger.info(f'New Window Running : {APP_NAME} (session={self.session_id})')
        if icon:
            self.setWindowIcon(icon)
        self.setWindowTitle(APP_NAME)
        self.resize(dpix(1000), dpix(700))
        self.database_name = None
        self.database_path = None
        self.setting_db = None
        self.window_state = WindowStateController(self)
        self._last_paths = None
        self.run_folder = True
        self.search_service = SearchService(lambda: self.database_path, parent=self)
        self.search_service.search_started.connect(self._on_search_started)
        self.search_service.search_finished.connect(self._on_search_finished)
        self.search_service.params_changed.connect(self._on_search_params_changed)
        UI.register_instance("SearchService", self.search_service)
        self.start_ipc_listener()
        self.t.set_locale(app_settings.get('window/language', 'en'))
        UI.register_instance("MainWindow", self)
        self.setup_ui()
        if self._session_entry:
            self._restore_from_session(self._session_entry)
        else:
            self.reload_database(self.get_last_used_db_name())
        QtWidgets.QApplication.instance().aboutToQuit.connect(self.on_close)


    @profiler.profile
    def get_last_used_db_name(self):
        names = list_setting_db_names()
        if not names:
            return DEFAULT_DB_NAME
        prevname = app_settings.get('window/tablename', DEFAULT_DB_NAME)
        if prevname in names:
            return prevname
        return names[0]

    @QtCore.Slot(str)
    def reload_database(self, name):
        self.database_name = name
        self.database_path = data_db_path(name)
        self.setting_db = SettingDB(setting_db_path(name))
        self.search_service.reset_state()
        self.folder_view.set_folders(self.setting_db.get_all_parent_folders(), self.setting_db.get_all_ignore_folders())
        self.run_folder = True
        QtCore.QTimer.singleShot(0, lambda: self.search(force=True))
        self.progress_bar.setProgress(int(0))
        self.progress_bar.setMaximum(int(0))
        self.refresh_db_selector()
        self._update_title()
        AppLogger.info(f'reload_database: {name}')

    def _update_title(self):
        if self._session_entry and self._session_entry.name:
            label = self._session_entry.name
        else:
            dirs = self.folder_view.get_selected_paths()
            if dirs:
                label = ', '.join(d.rsplit('/', 1)[-1] or d for d in dirs)
            else:
                label = self.database_name or ''
        self.setWindowTitle(f'{label}' if label else APP_NAME)
        if hasattr(self, '_session_button'):
            self._sync_session_button()

    def _create_session_button(self):
        btn = QtWidgets.QPushButton()
        btn.setCursor(QtCore.Qt.PointingHandCursor)
        btn.setFixedHeight(dpix(24))
        btn.clicked.connect(lambda: Command.invoke("win.session_list"))
        self._sync_session_button(btn)
        return btn

    def _sync_session_button(self, btn=None):
        btn = btn or self._session_button
        entry = self._session_entry
        label = f'\u25BC {entry.name}' if entry and entry.name else '\u25BC Window'
        btn.setText(label)
        color = entry.color if entry and entry.color else ''
        p = ThemeManager.instance().palette
        fs = dpix(12)
        pad_v = dpix(3)
        pad_h = dpix(8)
        bw = dpix(2)
        bw_l = dpix(5)
        br = dpix(6)
        if color:
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {p.text_primary};"
                f"  border: {bw}px solid {color}; border-left: {bw_l}px solid {color};"
                f"  border-radius: {br}px; padding: {pad_v}px {pad_h}px; font-size: {fs}px; text-align: left; }}"
                f"QPushButton:hover {{ background: {p.bg_hover}; color: {p.text_accent}; }}"
                f"QPushButton:pressed {{ background: {p.bg_pressed}; color: {p.text_accent}; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {p.text_primary}; border: {bw}px solid {p.border_default};"
                f"  border-radius: {br}px; padding: {pad_v}px {pad_h}px; font-size: {fs}px; text-align: left; }}"
                f"QPushButton:hover {{ background: {p.bg_hover}; color: {p.text_accent}; }}"
                f"QPushButton:pressed {{ background: {p.bg_pressed}; color: {p.text_accent}; }}"
            )

    def changeEvent(self, event):
        if event.type() == QtCore.QEvent.ActivationChange:
            if self.isActiveWindow():
                self.refresh_db_selector()
        super().changeEvent(event)

    @qt_debounce(200)
    def refresh_db_selector(self):
        names = list_setting_db_names()
        if not names:
            names = ['default']
        self.database_combo.setItems(names)
        self.database_combo.setCurrentText(self.database_name)
        AppLogger.debug('refresh_db_selector')

    @QtCore.Slot(int)
    def update_progress_value(self, value):
        self.progress_bar.setProgress(int(value))

    @QtCore.Slot(int)
    def update_progress_maximum(self, value):
        self.progress_bar.setMaximum(int(value))

    def start_ipc_listener(self):
        def _guarded(fn):
            def handler(msg):
                try:
                    if msg.db and msg.db != self.database_name:
                        return True
                    fn(msg)
                    return True
                except RuntimeError:
                    return True
            return handler

        def _invoke(slot, *args):
            QtCore.QMetaObject.invokeMethod(self, slot, QtCore.Qt.QueuedConnection, *args)

        self._node = Node('viewer')
        self._node.session_id = self.session_id
        self._node.subscribe('update', _guarded(
            lambda msg: _invoke('search', QtCore.Q_ARG(bool, True))
        )).subscribe('progress', _guarded(
            lambda msg: _invoke('update_progress_value', QtCore.Q_ARG(int, int(msg.payload)))
        )).subscribe('maximum', _guarded(
            lambda msg: _invoke('update_progress_maximum', QtCore.Q_ARG(int, int(msg.payload)))
        )).subscribe('folderchanged', _guarded(
            lambda msg: _invoke('reload_folderlist')
        )).subscribe('show_toggle', _guarded(
            lambda msg: _invoke('toggle_show', QtCore.Q_ARG(bool, bool(msg.payload)))
        )).subscribe('session.focus',
            lambda msg: (
                _invoke('raise_window') if msg.payload == self.session_id else None,
                True,
            )[-1]        ).subscribe('session.close',
            lambda msg: (
                _invoke('close_by_session_delete') if msg.payload == self.session_id else None,
                True,
            )[-1]        ).subscribe('dev.log', lambda msg: self._handle_remote_log(msg) or True)
        self._node.start()
        AppLogger.set_node(self._node, role='viewer')

    @profiler.profile
    def setup_ui(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.folder_view = LazyFolderTreeView()
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(dpix(4), dpix(4), dpix(0), dpix(6))
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        self.iconbar = IconButtonBar(
            left_buttons=[
                IconButtonConfig('gear', 'Settings', lambda: Command.invoke("win.show_settings")),
                IconButtonConfig('folder_plus', 'Add Folder', lambda: Command.invoke("ft.add_folder")),
            ],
            right_buttons=[
                IconButtonConfig(
                    'subfolder',
                    'Include Subfolders',
                    lambda checked: Command.invoke("qry.toggle_include_subfolders"),
                    checkable=True,
                    checked=self.search_service.get('include_subfolders', True),
                ),
                IconButtonConfig('fullscreen', 'Full Screen', lambda: Command.invoke("win.toggle_fullscreen")),
            ],
        )
        self.database_combo = ComboBoxWithButtons()
        self.database_combo.textChanged.connect(self.reload_database)
        self.database_combo.addClicked.connect(lambda: Command.invoke("db.add_database"))
        self.database_combo.removeClicked.connect(lambda: Command.invoke("db.remove_database"))

        self.progress_bar = ThinProgressBar()
        self._session_button = self._create_session_button()
        self.left_layout.addWidget(self._session_button)
        self.left_layout.addWidget(self.progress_bar)
        self.left_layout.addWidget(self.iconbar)
        self.left_layout.addWidget(self.folder_view)
        self.left_layout.addSpacing(dpix(3))
        self.left_layout.addWidget(self.database_combo)

        mid_panel = QtWidgets.QWidget()
        self.mid_layout = QtWidgets.QVBoxLayout(mid_panel)
        self.mid_layout.setContentsMargins(dpix(4), dpix(4), dpix(4), dpix(4))
        self.mid_layout.setSpacing(dpix(6))
        self.search_row_widget = SearchContainer()
        self.search_row_widget.filter_changed.connect(self._on_search_setting_changed)
        self.mid_layout.addWidget(self.search_row_widget)

        self.grid_items = GridItemModel(self)
        self.grid_view = GridView(self, self.grid_items)
        self.grid_view.verticalScrollBar().setSingleStep(25)
        self.grid_view.horizontalScrollBar().setSingleStep(25)
        self.grid_view.base_height_changed.connect(self._on_zoom_changed)

        self.mid_layout.addWidget(self.grid_view)
        self.splitter.addWidget(mid_panel)

        right_panel = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(dpix(0), dpix(12), dpix(8), dpix(8))
        self.right_layout.setSpacing(0)

        self.file_model = FileViewModel(dbpath_getter=lambda: self.database_path, parent=self)
        self.file_viewer = FileViewerWidget(self.file_model, self)
        UI.register_instance("FileViewerWidget", self.file_viewer)
        UI.register_instance("FileViewModel", self.file_model)
        UI.register_instance("GridItemModel", self.grid_items)
        
        self.right_layout.addWidget(self.file_viewer)

        self.splitter.addWidget(right_panel)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 1)
        self.overlay_stack = OverlayStack(self.grid_view)
        UI.register_instance("OverlayStack", self.overlay_stack)
        Notifier.on_info.connect(lambda t: self.overlay_stack.push(t, "info"))
        Notifier.on_warning.connect(lambda t: self.overlay_stack.push(t, "warning"))
        Notifier.on_error.connect(lambda t: self.overlay_stack.push(t, "error"))
        self.loading_indicator = OverlayLoadingIndicator()
        self.overlay_stack.push_persistent(self.loading_indicator, key="loading")
        self.grid_view.layout_started.connect(self._on_layout_started)
        self.grid_view.layout_ready.connect(lambda: self.overlay_stack.hide_persistent("loading"))
        self._register_component_states()
        self._setup_dev_panel()
        self._sync_service_from_ui()
        self._sync_default_checked_states()

    def _sync_default_checked_states(self):
        Command.set_checked('win.toggle_always_on_top',
                            self.window_state.is_always_on_top)
        Command.set_checked('qry.toggle_include_subfolders',
                            self.search_service.get('include_subfolders', True))
        Command.set_checked('qry.toggle_auto_execute',
                            self.search_service.get('auto_execute', True))
        from .commands.grid_commands import sync_grid_groups_from_settings, _SCROLL_ANCHOR_CMDS
        sync_grid_groups_from_settings({
            'orientation': self.grid_view.orientation,
            'layout_mode': self.grid_view.layout_mode,
        })
        Command.set_action_group_current(
            'grid_scroll_anchor', _SCROLL_ANCHOR_CMDS[1], save=False)

    def _register_component_states(self):
        store = StateStore.instance()
        store.register('main_splitter', self._save_splitter, self._restore_splitter)
        store.register('grid', self._save_grid, self._restore_grid)
        self._register_grid_plugin_states(store)

    def _register_grid_plugin_states(self, store):
        from ...plugin.grid.base import WidgetGridPlugin as _WGP
        from .grid.grid_view import grid_resolver
        for name, cls in grid_resolver.registry.all_classes():
            inst = grid_resolver.registry.instance(name)
            if inst is not None and isinstance(inst, _WGP):
                p = inst
                store.register(
                    f'grid_plugin.{name}',
                    lambda p=p: p.save_state(),
                    lambda s, p=p: p.restore_state(s),
                )

    def _save_splitter(self):
        return {'sizes': self.splitter.sizes()}

    def _restore_splitter(self, state):
        sizes = state.get('sizes')
        if sizes:
            self.splitter.setSizes(sizes)

    def _save_grid(self):
        from .commands.grid_commands import _SCROLL_ANCHOR_CMDS
        return {
            'zoom': self.grid_view.base_height,
            'orientation': self.grid_view.orientation,
            'layout_mode': self.grid_view.layout_mode,
            'scroll_index': self.grid_view.get_center_image_index(),
            'scroll_anchor': Command.get_action_group_current('grid_scroll_anchor') or _SCROLL_ANCHOR_CMDS[1],
        }

    def _restore_grid(self, state):
        if 'zoom' in state:
            self.grid_view.base_height = state['zoom']
        if 'orientation' in state:
            self.grid_view.set_orientation(state['orientation'])
        if 'layout_mode' in state:
            self.grid_view.set_layout_mode(state['layout_mode'])
        from .commands.grid_commands import sync_grid_groups_from_settings
        sync_grid_groups_from_settings(state)
        if state.get('scroll_index') is not None:
            self.grid_view.set_pending_scroll_index(state['scroll_index'])
        if 'scroll_anchor' in state:
            from .commands.grid_commands import _SCROLL_ANCHOR_CMDS
            if state['scroll_anchor'] in _SCROLL_ANCHOR_CMDS:
                Command.set_action_group_current('grid_scroll_anchor', state['scroll_anchor'], save=False)

    def _sync_service_from_ui(self):
        dirs = self.folder_view.get_selected_paths()
        self.search_service.set_entries_builder(
            lambda: self.search_row_widget.build_filter_entries(
                self.folder_view.get_selected_paths(),
                self.search_service.get('include_subfolders', True),
            )
        )
        self.search_service.set_directories(dirs)
        sort_by, ascending = self.search_row_widget.get_sort()
        self.search_service.set_params({
            'sort_by': sort_by,
            'ascending': ascending,
        })
        values = self.search_row_widget.get_values()
        self.search_service.set_params({
            'keywords': values.get('keywords', ''),
            'query_mode': values.get('query_mode', 'GLOB'),
            'keyword_mode': values.get('keyword_mode', 'AND'),
            'keyword_separator': values.get('keyword_separator', ','),
        })
        from .commands.query_commands import sync_groups_from_args
        sync_groups_from_args(self.search_service.params)

    def _on_search_setting_changed(self):
        self._sync_service_from_ui()
        self.search_service.execute_if_auto()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        AppLogger.debug('[RUNNING] reload_folderlist')
        self.folder_view.reload_tree()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.search_row_widget.on_move_event()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.search_row_widget.on_move_event()

    def _on_zoom_changed(self):
        if self.grid_view.is_scrolling():
            speed = self.grid_view.get_adjusted_scroll_speed(self.grid_view._autoscroll_base_speed)
            self.grid_view._scroll_speed = speed

    @profiler.profile
    def on_folder_selected(self):
        self.run_folder = True
        self._folder_changed = True
        dirs = self.folder_view.get_selected_paths()
        AppLogger.debug(f'folder selected: {dirs}')
        self.search_service.set_directories(dirs)
        self._update_title()
        self.search_service.execute_if_auto()

    @QtCore.Slot(bool)
    def toggle_show(self, state):
        if self.isMinimized() or not self.isVisible():
            self.window_state.restore_or_activate()
        else:
            self.window_state.minimize()

    @QtCore.Slot()
    def close_by_session_delete(self):
        self._session_deleted = True
        self.close()

    @QtCore.Slot()
    def raise_window(self):
        self.window_state.restore_or_activate()

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
        if paths == self._last_paths:
            self.overlay_stack.hide_persistent("loading")
            return
        self._last_paths = paths
        self.grid_view.set_paths(paths, sources, aspects, keep_scroll=keep_scroll)
        self.file_model.set_items(paths, sources)
        if self.run_folder:
            self.search_row_widget.run_folder_worker(self.database_path, self.folder_view.get_selected_paths())
            self.run_folder = False

    def capture_query_state(self) -> QueryState:
        params = self.search_service.params
        container_state = self.search_row_widget.save_state()
        params['filter_rows'] = container_state.get('rows', [])
        return QueryState(
            database_name=self.database_name or '',
            search_params=params,
            folder_state=dict(zip(
                ('expanded', 'selected'),
                self.folder_view.get_state(),
            )),
        )

    def capture_ui_state(self) -> UIState:
        return UIState(
            window_state=self.window_state.save_full_state(),
            component_states=StateStore.instance().save_all(),
        )

    def restore_query_state(self, query: QueryState) -> None:
        if query.database_name and query.database_name != self.database_name:
            self.reload_database(query.database_name)
        if query.search_params:
            self.search_service.set_params(query.search_params)
            from .commands.query_commands import sync_groups_from_args
            sync_groups_from_args(query.search_params)
            Command.set_checked('qry.toggle_include_subfolders', query.search_params.get('include_subfolders', True))
            Command.set_checked('qry.toggle_auto_execute', query.search_params.get('auto_execute', True))
            filter_rows = query.search_params.get('filter_rows')
            if filter_rows:
                self.search_row_widget.restore_state({
                    'rows': filter_rows,
                    'sort_by': query.search_params.get('sort_by', 'path'),
                    'ascending': query.search_params.get('ascending', True),
                })
            else:
                self._apply_params_to_ui(query.search_params)
        if query.folder_state:
            expanded = query.folder_state.get('expanded', [])
            selected = query.folder_state.get('selected', [])
            self.folder_view.set_state((expanded, selected))
        QtCore.QTimer.singleShot(0, lambda: self.search(force=True))

    def _apply_params_to_ui(self, params):
        row = self.search_row_widget
        if 'sort_by' in params:
            row.set_sort_by(params['sort_by'])
        if 'query_mode' in params:
            row.set_query_mode(params['query_mode'])
        if 'keyword_mode' in params:
            row.set_keyword_mode(params['keyword_mode'])
        if 'ascending' in params:
            row.set_ascending(params['ascending'])
        if 'keyword_separator' in params:
            row.set_keyword_delimiter(params['keyword_separator'])
        if 'keywords' in params:
            row.set_search_text(params['keywords'])

    def restore_ui_state(self, ui: UIState) -> None:
        if ui.window_state:
            try:
                self.window_state.restore_full_state(ui.window_state)
                Command.set_checked('win.toggle_always_on_top', self.window_state.is_always_on_top)
            except Exception as e:
                AppLogger.warning(f'restore_ui_state window_state failed: {e}', exc=e)
        if ui.component_states:
            StateStore.instance().restore_all(ui.component_states)

    def _restore_from_session(self, entry: SessionEntry):
        if entry.query_snapshot:
            db_name = entry.query_snapshot.database_name or self.get_last_used_db_name()
        else:
            db_name = self.get_last_used_db_name()
        self.reload_database(db_name)
        if entry.query_snapshot:
            self.restore_query_state(entry.query_snapshot)
        if entry.ui:
            self.restore_ui_state(entry.ui)

    def _save_session(self):
        if self._session_deleted:
            return
        entry = self._session_entry or SessionEntry(
            session_id=self.session_id, name=DEFAULT_SESSION_NAME)
        entry.ui = self.capture_ui_state()
        entry.query_snapshot = self.capture_query_state()
        self._session_store.save_session(entry)
        self._session_entry = entry

    def on_close(self):
        try:
            self._save_session()
            app_settings.save_immediate('window/tablename', self.database_name)
            app_settings.commit()
            self.t.dump_missing_keys()
        except Exception as e:
            AppLogger.warning(f'on_close failed: {e}', exc=e)
        try:
            if hasattr(self, '_node'):
                AppLogger.info('on_close [STOPPING]')
                self._node.stop()
        except Exception as e:
            AppLogger.debug(f'on_close node.stop failed: {e}')

    def closeEvent(self, event):
        return super().closeEvent(event)

    def _setup_dev_panel(self):
        if not DEV_MODE:
            return
        from .widgets.dev_log_panel import DevLogPanel
        self._dev_panel = DevLogPanel(self)
        self.addDockWidget(QtCore.Qt.BottomDockWidgetArea, self._dev_panel)

    @QtCore.Slot(str, str, str, str)
    def _on_dev_log(self, level: str, text: str, src: str, db: str):
        if hasattr(self, '_dev_panel'):
            self._dev_panel.append_log(level, text, src=src, db=db)

    def _handle_remote_log(self, msg):
        if not hasattr(self, '_dev_panel'):
            return
        p = msg.payload
        if not isinstance(p, dict):
            return
        QtCore.QMetaObject.invokeMethod(
            self, '_on_dev_log',
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, p.get('level', 'info')),
            QtCore.Q_ARG(str, p.get('text', '')),
            QtCore.Q_ARG(str, msg.source),
            QtCore.Q_ARG(str, msg.db or ''),
        )
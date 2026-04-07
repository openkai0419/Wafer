from PySide6 import QtCore, QtWidgets
from ...utils.paths import data_db_path, setting_db_path, list_setting_db_names
from ...utils.formatting import dpix
from ...core.color.theme import ThemeManager
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...constants import APP_NAME, DEFAULT_DB_NAME, DEFAULT_SESSION_NAME
from ...core.db.setting_db import SettingDB
from ...core.lang.manager import TranslatorMixin
from ...core.qt.rate_limit import qt_debounce
from ...core.ipc.node import Node
from .grid.grid_view import GridView
from .grid.items import GridItemModel
from .preview.file_model import FileViewModel
from .preview.file_viewer import FileViewerController
from .preview.file_list_provider import FileListProvider
from .preview.content_viewer import ContentViewerWidget
from .preview.meta_panel import MetaViewerWidget
from ...core.setting.app_settings import app_settings
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .widgets.foldertree import LazyFolderTreeView
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.overlay_stack import OverlayStack
from .widgets.progress_bar import ThinProgressBar
from .widgets.search_container import SearchContainer
from .widgets.combo_with_buttons import ComboBoxWithButtons

from ...builtins.commands.menu import AppMenuRegistrar
from .search import SearchService
from ...core.session import QueryState, UIState, SessionEntry, SessionStore
from ...core.commands.bridge import UI, Command, Menu
from ...core.layout.manager import LayoutManager
from ...core.state import StateStore
from ...core.qt.window import WindowStateController
from ...core.qt.dispatcher import Dispatcher, CancelToken
from ...core.qt.thread import utility_pool

AppMenuRegistrar.setup_menu()


class MainWindow(QtWidgets.QMainWindow, TranslatorMixin):
    def __init__(self, icon=None, parent=None, session_id=None):
        super().__init__(parent=parent)
        self._session_store = SessionStore.instance()
        self.session_id = None
        self._session_entry = None
        self._session_deleted = False
        self._session_ready = False
        if icon:
            self.setWindowIcon(icon)
        self.setWindowTitle(APP_NAME)
        self.resize(dpix(1000), dpix(700))
        self.database_name = None
        self.database_path = None
        self.setting_db = None
        self.window_state = WindowStateController(self)
        self._last_paths = None
        self._folder_changed = False
        self._dispatcher = Dispatcher(utility_pool)
        self._db_reload_cancel: CancelToken | None = None
        self.search_service = SearchService(lambda: self.database_path, parent=self)
        self.search_service.search_started.connect(self._on_search_started)
        self.search_service.search_finished.connect(self._on_search_finished)
        self.search_service.params_changed.connect(self._on_search_params_changed)
        UI.register_instance("SearchService", self.search_service)
        self.t.set_locale(app_settings.get("window/language", "en"))
        UI.register_instance("MainWindow", self)
        self._closed = False
        self.setup_ui()
        self._show_loading()
        self._acquire_session_async(session_id)

    def _acquire_session_async(self, requested_id):
        store = self._session_store

        def task():
            sid, entry = store.acquire_or_create(requested_id)
            self._dispatcher.invoke(lambda: self._on_session_acquired(sid, entry))

        self._dispatcher.post(task, priority=9)

    def _on_session_acquired(self, sid, entry):
        self.session_id = sid
        self._session_entry = entry
        self._session_ready = True
        AppLogger.info(f"New Window Running : {APP_NAME} (session={self.session_id})")
        self.start_ipc_listener()
        self._update_title()
        if entry:
            self._restore_from_session(entry)
        else:
            self.reload_database(self.get_last_used_db_name())

    @profiler.profile
    def get_last_used_db_name(self):
        names = list_setting_db_names()
        if not names:
            return DEFAULT_DB_NAME
        prevname = app_settings.get("window/tablename", DEFAULT_DB_NAME)
        if prevname in names:
            return prevname
        return names[0]

    @QtCore.Slot(str)
    def reload_database(self, name, on_complete=None):
        self.database_name = name
        self.database_path = data_db_path(name)
        self.search_service.reset_state()
        self._last_paths = None
        self.search_row_widget.invalidate_key_cache()
        self.progress_bar.setProgress(0)
        self.progress_bar.setMaximum(0)
        self.refresh_db_selector()
        self._update_title()
        AppLogger.info(f"reload_database: {name}")
        self._reload_db_async(name, on_complete)

    def _reload_db_async(self, name, on_complete=None):
        if self._db_reload_cancel:
            self._db_reload_cancel.cancel()
        cancel = CancelToken()
        self._db_reload_cancel = cancel
        db_path = setting_db_path(name)

        def task():
            try:
                sdb = SettingDB(db_path)
                roots = sdb.get_all_parent_folders()
                excluded = sdb.get_all_ignore_folders()
                if cancel.is_cancelled():
                    return
                self._dispatcher.invoke(lambda: self._apply_db_reload(sdb, roots, excluded, cancel, on_complete))
            except Exception as e:
                AppLogger.error(f"Failed to load database: {name}", exc=e)
                self._dispatcher.invoke(lambda _e=e: self._on_db_reload_failed(name, _e))

        self._dispatcher.post(task, priority=8, cancel=cancel)

    def _apply_db_reload(self, sdb, roots, excluded, cancel, on_complete=None):
        if cancel.is_cancelled():
            return
        self._db_reload_cancel = None
        self.setting_db = sdb
        self.folder_view.set_folders(roots, excluded)
        if on_complete:
            on_complete()
        else:
            self.search_row_widget.run_folder_worker(
                self.database_path,
                self.folder_view.get_selected_paths(),
            )
            QtCore.QTimer.singleShot(0, lambda: self.search(force=True))

    def _on_db_reload_failed(self, name, exc):
        self._db_reload_cancel = None
        self._hide_loading()
        Notifier.error(f'Failed to load database "{name}"')

    def _update_title(self):
        if self._session_entry and self._session_entry.name:
            label = self._session_entry.name
        else:
            dirs = self.folder_view.get_selected_paths()
            if dirs:
                label = ", ".join(d.rsplit("/", 1)[-1] or d for d in dirs)
            else:
                label = self.database_name or ""
        self.setWindowTitle(f"{label}" if label else APP_NAME)
        if hasattr(self, "_session_button"):
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
        label = f"\u25bc {entry.name}" if entry and entry.name else "\u25bc Window"
        btn.setText(label)
        color = entry.color if entry and entry.color else ""
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

    @qt_debounce(200)
    def refresh_db_selector(self):
        names = list_setting_db_names()
        if not names:
            names = ["default"]
        self.database_combo.setItems(names)
        self.database_combo.setCurrentText(self.database_name)
        AppLogger.debug("refresh_db_selector")

    @QtCore.Slot(str)
    def _on_db_created(self, name: str):
        if self.database_combo.combo.findText(name) < 0:
            self.database_combo.addItem(name)

    @QtCore.Slot(str)
    def _on_db_deleted(self, name: str):
        self.database_combo.removeItem(name)
        if self.database_name == name:
            self.reload_database(self.database_combo.currentText())

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
                except RuntimeError as e:
                    if "wrapped C/C++ object" in str(e):
                        return True
                    AppLogger.warning(f"IPC handler RuntimeError: {e}", exc=e)
                    return True

            return handler

        def _invoke(slot, *args):
            QtCore.QMetaObject.invokeMethod(self, slot, QtCore.Qt.QueuedConnection, *args)

        def _for_session(slot):
            def handler(msg):
                if msg.payload == self.session_id:
                    _invoke(slot)
                return True

            return handler

        self._node = Node("viewer")
        self._node.session_id = self.session_id
        self._node.subscribe("update", _guarded(lambda msg: _invoke("_on_db_content_updated"))).subscribe(
            "progress", _guarded(lambda msg: _invoke("update_progress_value", QtCore.Q_ARG(int, int(msg.payload))))
        ).subscribe("maximum", _guarded(lambda msg: _invoke("update_progress_maximum", QtCore.Q_ARG(int, int(msg.payload))))).subscribe(
            "folderchanged", _guarded(lambda msg: _invoke("reload_folderlist"))
        ).subscribe("show_toggle", _guarded(lambda msg: _invoke("toggle_show", QtCore.Q_ARG(bool, bool(msg.payload))))).subscribe("session.focus", _for_session("raise_window")).subscribe(
            "session.close", _for_session("close_by_session_delete")
        ).subscribe("session.restart", _for_session("close_by_restart")).subscribe("dev.log", _guarded(lambda msg: self._handle_remote_log(msg))).subscribe(
            "db.created", _guarded(lambda msg: _invoke("_on_db_created", QtCore.Q_ARG(str, str(msg.payload))))
        ).subscribe("db.deleted", _guarded(lambda msg: _invoke("_on_db_deleted", QtCore.Q_ARG(str, str(msg.payload)))))
        self._node.start()
        AppLogger.set_node(self._node, role="viewer")

    @profiler.profile
    def setup_ui(self):
        self._layout_manager = LayoutManager(self)
        self._layout_manager.set_margin(dpix(5))

        self.folder_view = LazyFolderTreeView()
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        self.iconbar = IconButtonBar(
            left_buttons=[
                IconButtonConfig("menu", "All Menu", lambda: Menu.session(self).all_roots().exec()),
                IconButtonConfig("gear", "Settings", lambda: Menu.session(self).from_folder("Setting").exec()),
                IconButtonConfig(
                    "layout_edit",
                    "Edit Layout",
                    lambda: Menu.session(self).from_folder("Panels").exec(),
                ),
                IconButtonConfig("fullscreen", "Full Screen", lambda: Command.invoke("win.toggle_fullscreen")),
            ],
            right_buttons=[
                IconButtonConfig("folder_plus", "Add Folder", lambda: Command.invoke("ft.add_folder")),
                IconButtonConfig(
                    "subfolder",
                    "Include Subfolders",
                    lambda checked: Command.invoke("qry.toggle_include_subfolders"),
                    checkable=True,
                    checked=self.search_service.get("include_subfolders", True),
                ),
            ],
        )
        self._subfolder_btn = self.iconbar.right_buttons[1]
        self._layout_edit_btn = self.iconbar.left_buttons[2]
        self._layout_manager.mode_changed.connect(self._on_layout_mode_changed)
        self.database_combo = ComboBoxWithButtons()
        self.database_combo.textChanged.connect(self.reload_database)
        self.database_combo.addClicked.connect(lambda: Command.invoke("db.add_database"))
        self.database_combo.removeClicked.connect(lambda: Command.invoke("db.remove_database"))

        self.progress_bar = ThinProgressBar()
        self._session_button = self._create_session_button()

        self.search_row_widget = SearchContainer()
        self.search_row_widget.filter_changed.connect(self._on_search_setting_changed)

        self.grid_items = GridItemModel(self)
        self.grid_view = GridView(self, self.grid_items)
        self.grid_view.verticalScrollBar().setSingleStep(25)
        self.grid_view.horizontalScrollBar().setSingleStep(25)
        self.grid_view.base_height_changed.connect(self._on_zoom_changed)

        self.file_model = FileViewModel(dbpath_getter=lambda: self.database_path, parent=self)
        self.content_viewer = ContentViewerWidget()
        self.meta_viewer_widget = MetaViewerWidget()
        self.file_viewer = FileViewerController(self.file_model, self.content_viewer, self.meta_viewer_widget, self)
        self.file_list_provider = FileListProvider(self.file_model, self.grid_items, self)
        self.file_list_provider.set_search_service(self.search_service)
        UI.register_instance("FileViewerController", self.file_viewer)
        UI.register_instance("FileListProvider", self.file_list_provider)
        UI.register_instance("ContentViewerWidget", self.content_viewer)
        UI.register_instance("FileViewModel", self.file_model)
        UI.register_instance("GridItemModel", self.grid_items)

        self._layout_manager.register("Toolbar", self._create_toolbar_panel, closable=False)
        self._layout_manager.register("Folder Tree", self._create_folder_panel)
        self._layout_manager.register("Search", lambda: self.search_row_widget)
        self._layout_manager.register("Grid View", lambda: self.grid_view)
        self._layout_manager.register("Content Viewer", lambda: self.content_viewer)
        self._layout_manager.register("Meta Viewer", lambda: self.meta_viewer_widget)
        self._register_panel_plugins()

        default_layout = self._load_default_layout()
        self._layout_manager.restore_state(default_layout)

        self.overlay_stack = OverlayStack(self.grid_view)
        UI.register_instance("OverlayStack", self.overlay_stack)
        Notifier.on_info.connect(lambda t: self.overlay_stack.push(t, "info"))
        Notifier.on_warning.connect(lambda t: self.overlay_stack.push(t, "warning"))
        Notifier.on_error.connect(lambda t: self.overlay_stack.push(t, "error"))
        self.loading_indicator = OverlayLoadingIndicator()
        self.overlay_stack.push_persistent(self.loading_indicator, key="loading")
        self.grid_view.layout_started.connect(self._on_layout_started)
        self.grid_view.layout_ready.connect(self._hide_loading)
        self._register_component_states()
        self._sync_service_from_ui()
        self._sync_default_checked_states()

    def _create_toolbar_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._session_button)
        layout.addWidget(self.progress_bar)
        layout.addWidget(self.iconbar)
        panel.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Maximum)
        return panel

    def _create_folder_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.folder_view)
        layout.addSpacing(dpix(3))
        layout.addWidget(self.database_combo)
        return panel

    def _load_default_layout(self):
        import json
        from ...utils.paths import get_resource_path

        layout_path = get_resource_path() / "panel_layout" / "default.json"
        if layout_path.exists():
            with open(layout_path, encoding="utf-8") as f:
                return json.load(f)
        return {"mode": "locked", "tree": {"root": None, "floating": {}}}

    def _sync_default_checked_states(self):
        Command.set_checked("win.toggle_always_on_top", self.window_state.is_always_on_top)
        Command.set_checked("qry.toggle_include_subfolders", self.search_service.get("include_subfolders", True))
        Command.set_checked("qry.toggle_auto_execute", self.search_service.get("auto_execute", True))
        from ...builtins.commands.grid_commands import sync_grid_groups_from_settings, _SCROLL_ANCHOR_CMDS

        sync_grid_groups_from_settings(
            {
                "orientation": self.grid_view.orientation,
                "layout_mode": self.grid_view.layout_mode,
            }
        )
        Command.set_action_group_current("grid_scroll_anchor", _SCROLL_ANCHOR_CMDS[1], save=False)

    def _on_layout_mode_changed(self, mode):
        from ...core.layout.manager import MODE_EDIT

        is_edit = mode == MODE_EDIT
        self._layout_edit_btn.blockSignals(True)
        self._layout_edit_btn.setChecked(is_edit)
        self._layout_edit_btn.blockSignals(False)
        Command.set_checked("win.toggle_layout_mode", is_edit)

    def _register_component_states(self):
        store = StateStore.instance()
        store.register("layout", self._save_layout, self._restore_layout)
        store.register("grid", self._save_grid, self._restore_grid)
        self._register_grid_plugin_states(store)

    def _register_grid_plugin_states(self, store):
        from ...plugin.grid.base import WidgetGridPlugin as _WGP
        from .grid.grid_view import grid_resolver

        for name, _cls in grid_resolver.registry.all_classes():
            inst = grid_resolver.registry.instance(name)
            if inst is not None and isinstance(inst, _WGP):
                p = inst
                store.register(
                    f"grid_plugin.{name}",
                    lambda p=p: p.save_state(),
                    lambda s, p=p: p.restore_state(s),
                )

    def _save_layout(self):
        return self._layout_manager.save_state()

    def _restore_layout(self, state):
        self._layout_manager.restore_state(state)

    def _save_grid(self):
        from ...builtins.commands.grid_commands import _SCROLL_ANCHOR_CMDS

        return {
            "zoom": self.grid_view.base_height,
            "orientation": self.grid_view.orientation,
            "layout_mode": self.grid_view.layout_mode,
            "scroll_index": self.grid_view.get_center_image_index(),
            "scroll_anchor": Command.get_action_group_current("grid_scroll_anchor") or _SCROLL_ANCHOR_CMDS[1],
        }

    def _restore_grid(self, state):
        if "zoom" in state:
            self.grid_view.base_height = state["zoom"]
            self.grid_view._zoom_restore_guard = True
        if "orientation" in state:
            self.grid_view.set_orientation(state["orientation"])
        if "layout_mode" in state:
            self.grid_view.set_layout_mode(state["layout_mode"])
        from ...builtins.commands.grid_commands import sync_grid_groups_from_settings

        sync_grid_groups_from_settings(state)
        if state.get("scroll_index") is not None:
            self.grid_view.set_pending_scroll_index(state["scroll_index"])
        if "scroll_anchor" in state:
            from ...builtins.commands.grid_commands import _SCROLL_ANCHOR_CMDS

            if state["scroll_anchor"] in _SCROLL_ANCHOR_CMDS:
                Command.set_action_group_current("grid_scroll_anchor", state["scroll_anchor"], save=False)
        if "zoom" in state:
            self.grid_view.layout_ready.connect(self._clear_zoom_restore_guard, QtCore.Qt.SingleShotConnection)

    def _clear_zoom_restore_guard(self):
        self.grid_view._zoom_restore_guard = False

    def _sync_service_from_ui(self):
        dirs = self.folder_view.get_selected_paths()
        self.search_service.set_entries_builder(
            lambda: self.search_row_widget.build_filter_entries(
                self.folder_view.get_selected_paths(),
                self.search_service.get("include_subfolders", True),
            )
        )
        self.search_service.set_directories(dirs)
        sort_by, ascending = self.search_row_widget.get_sort()
        self.search_service.set_params(
            {
                "sort_by": sort_by,
                "ascending": ascending,
            }
        )
        values = self.search_row_widget.get_values()
        self.search_service.set_params(
            {
                "keywords": values.get("keywords", ""),
                "query_mode": values.get("query_mode", "GLOB"),
                "keyword_mode": values.get("keyword_mode", "AND"),
                "keyword_separator": values.get("keyword_separator", ","),
            }
        )
        from ...builtins.commands.query_commands import sync_groups_from_args

        sync_groups_from_args(self.search_service.params)

    def _on_search_setting_changed(self):
        self._sync_service_from_ui()
        self.search_service.execute_if_auto()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        AppLogger.debug("[RUNNING] reload_folderlist")
        if self.setting_db:
            state = self.folder_view.get_state()
            roots = self.setting_db.get_all_parent_folders()
            excluded = self.setting_db.get_all_ignore_folders()
            self.folder_view.set_folders(roots, excluded)
            self.folder_view.set_state(state)
        else:
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
        self._folder_changed = True
        dirs = self.folder_view.get_selected_paths()
        AppLogger.debug(f"folder selected: {dirs}")
        self.search_service.set_directories(dirs)
        self._update_title()
        self.search_service.execute_if_auto()

    @QtCore.Slot(bool)
    def toggle_show(self, show):
        if show:
            self.window_state.restore_or_activate()
        else:
            self.window_state.minimize()

    @QtCore.Slot()
    def close_by_session_delete(self):
        self._session_deleted = True
        self.close()

    @QtCore.Slot()
    def close_by_restart(self):
        self._save_session()
        from ...core.platform.process import AppProcess

        args = ["--viewer"]
        if self.session_id:
            args += ["--session", self.session_id]
        AppProcess.new_main(*args)
        self.close()

    @QtCore.Slot()
    def raise_window(self):
        self.window_state.restore_or_activate()

    @QtCore.Slot(bool)
    def search(self, force=False):
        self._sync_service_from_ui()
        self.search_service.execute(force=force)

    @QtCore.Slot()
    def _on_db_content_updated(self):
        self.search_row_widget.invalidate_key_cache()
        self.search(force=True)

    def _on_search_params_changed(self, changed):
        if "include_subfolders" in changed:
            self._subfolder_btn.blockSignals(True)
            self._subfolder_btn.setChecked(changed["include_subfolders"])
            self._subfolder_btn.blockSignals(False)

    def _show_loading(self):
        self.loading_indicator.start()
        self.overlay_stack.show_persistent("loading")

    def _hide_loading(self):
        self.loading_indicator.stop()
        self.overlay_stack.hide_persistent("loading")

    def _on_layout_started(self):
        self._show_loading()

    def _on_search_started(self):
        self._show_loading()

    @QtCore.Slot(object, object, object)
    @profiler.profile
    def _on_search_finished(self, paths, sources, aspects):
        keep_scroll = not self._folder_changed
        self._folder_changed = False
        self.search_row_widget.run_folder_worker(self.database_path, self.folder_view.get_selected_paths())
        if paths == self._last_paths:
            self._hide_loading()
            return
        self._last_paths = paths
        self.grid_view.set_paths(paths, sources, aspects, keep_scroll=keep_scroll)
        self.file_list_provider.on_search_results(paths, sources)

    def capture_query_state(self) -> QueryState:
        params = self.search_service.params
        container_state = self.search_row_widget.save_state()
        params["filter_rows"] = container_state.get("rows", [])
        return QueryState(
            database_name=self.database_name or "",
            search_params=params,
            folder_state=dict(
                zip(
                    ("expanded", "selected"),
                    self.folder_view.get_state(),
                )
            ),
        )

    def capture_ui_state(self) -> UIState:
        return UIState(
            window_state=self.window_state.save_full_state(),
            component_states=StateStore.instance().save_all(),
        )

    def restore_query_state(self, query: QueryState) -> None:
        if query.database_name and query.database_name != self.database_name:
            self.reload_database(query.database_name, on_complete=lambda: self.restore_query_state(QueryState(search_params=query.search_params, folder_state=query.folder_state)))
            return
        if query.search_params:
            self.search_service.set_params(query.search_params)
            from ...builtins.commands.query_commands import sync_groups_from_args

            sync_groups_from_args(query.search_params)
            Command.set_checked("qry.toggle_include_subfolders", query.search_params.get("include_subfolders", True))
            Command.set_checked("qry.toggle_auto_execute", query.search_params.get("auto_execute", True))
            filter_rows = query.search_params.get("filter_rows")
            if filter_rows:
                self.search_row_widget.restore_state(
                    {
                        "rows": filter_rows,
                        "sort_by": query.search_params.get("sort_by", "path"),
                        "ascending": query.search_params.get("ascending", True),
                    }
                )
            else:
                self._apply_params_to_ui(query.search_params)

        def _search_after_keys():
            self.search_row_widget.run_folder_worker(
                self.database_path,
                self.folder_view.get_selected_paths(),
                on_complete=lambda: self.search(force=True),
            )

        if query.folder_state:
            expanded = query.folder_state.get("expanded", [])
            selected = query.folder_state.get("selected", [])
            self.folder_view.set_state_async(
                (expanded, selected),
                on_complete=lambda: QtCore.QTimer.singleShot(0, _search_after_keys),
            )
        else:
            QtCore.QTimer.singleShot(0, _search_after_keys)

    def _apply_params_to_ui(self, params):
        row = self.search_row_widget
        if "sort_by" in params:
            row.set_sort_by(params["sort_by"])
        if "query_mode" in params:
            row.set_query_mode(params["query_mode"])
        if "keyword_mode" in params:
            row.set_keyword_mode(params["keyword_mode"])
        if "ascending" in params:
            row.set_ascending(params["ascending"])
        if "keyword_separator" in params:
            row.set_keyword_delimiter(params["keyword_separator"])
        if "keywords" in params:
            row.set_search_text(params["keywords"])

    def restore_ui_state(self, ui: UIState) -> None:
        if ui.window_state:
            try:
                self.window_state.restore_full_state(ui.window_state)
                Command.set_checked("win.toggle_always_on_top", self.window_state.is_always_on_top)
            except Exception as e:
                AppLogger.warning(f"restore_ui_state window_state failed: {e}", exc=e)
        if ui.component_states:
            StateStore.instance().restore_all(ui.component_states)

    def _restore_from_session(self, entry: SessionEntry):
        if entry.query_snapshot:
            db_name = entry.query_snapshot.database_name or self.get_last_used_db_name()
        else:
            db_name = self.get_last_used_db_name()

        def on_db_ready():
            if entry.query_snapshot:
                self.restore_query_state(entry.query_snapshot)
            else:
                QtCore.QTimer.singleShot(0, lambda: self.search(force=True))
            if entry.ui:
                self.restore_ui_state(entry.ui)

        self.reload_database(db_name, on_complete=on_db_ready)

    def _save_session(self):
        if self._session_deleted or not self._session_ready:
            return
        entry = self._session_entry or SessionEntry(session_id=self.session_id, name=DEFAULT_SESSION_NAME)
        entry.ui = self.capture_ui_state()
        entry.query_snapshot = self.capture_query_state()
        self._session_store.save_session(entry)
        self._session_entry = entry

    def closeEvent(self, event):
        self.on_close()
        super().closeEvent(event)

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        try:
            self._save_session()
            if self.database_name:
                app_settings.save_immediate("window/tablename", self.database_name)
            app_settings.commit()
            self.t.dump_missing_keys()
        except Exception as e:
            AppLogger.warning(f"on_close failed: {e}", exc=e)
        try:
            if hasattr(self, "_node"):
                AppLogger.info("on_close [STOPPING]")
                self._node.stop()
        except Exception as e:
            AppLogger.debug(f"on_close node.stop failed: {e}")

    def _register_panel_plugins(self):
        from ...plugin.panel.handler import panel_registry

        for cls in panel_registry.list_all():
            plugin = cls()
            name = plugin.DISPLAY_NAME or plugin.NAME
            self._layout_manager.register(
                name,
                plugin.create_widget,
                closable=plugin.CLOSABLE,
            )

    @QtCore.Slot(str, str, str, str)
    def _on_dev_log(self, level: str, text: str, src: str, db: str):
        from ...builtins.devlog import DevLogPanel

        panel = DevLogPanel.instance()
        if panel is not None:
            panel.append_log(level, text, src=src, db=db)

    def _handle_remote_log(self, msg):
        from ...builtins.devlog import DevLogPanel

        if DevLogPanel.instance() is None:
            return
        p = msg.payload
        if not isinstance(p, dict):
            return
        QtCore.QMetaObject.invokeMethod(
            self,
            "_on_dev_log",
            QtCore.Qt.QueuedConnection,
            QtCore.Q_ARG(str, p.get("level", "info")),
            QtCore.Q_ARG(str, p.get("text", "")),
            QtCore.Q_ARG(str, msg.source),
            QtCore.Q_ARG(str, msg.db or ""),
        )

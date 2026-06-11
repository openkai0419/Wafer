from PySide6 import QtCore, QtWidgets
from ...utils.paths import data_db_path, setting_db_path, list_setting_db_names
from ...utils.formatting import dpix
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
from ...utils.notifier import Notifier
from ...constants import APP_NAME, DEFAULT_DB_NAME
from ...core.db.setting_db import SettingDB
from wafer.core.lang.manager import t

from ...core.qt.rate_limit import qt_debounce
from ...core.ipc.node import Node
from .ipc_bridge import ViewerIpcBridge
from .grid.grid_view import GridView
from .grid.items import GridItemModel
from .preview.file_model import FileViewModel
from .preview.file_viewer import FileViewerController
from .preview.file_list_provider import FileListProvider
from .preview.content_viewer import ContentViewerWidget
from .preview.meta_panel import MetaViewerWidget
from ...core.app_settings import app_settings
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .widgets.foldertree import LazyFolderTreeView
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.overlay_stack import OverlayStack
from .widgets.progress_bar import ThinProgressBar
from .widgets.search_container import SearchContainer
from .widgets.combo_with_buttons import ComboBoxWithButtons
from .widgets.callout_overlay import CalloutOverlay
from .widgets.workspace_toolbar import WorkspaceToolbarWidget

from ...builtins.commands.menu import AppMenuRegistrar
from .search import SearchService
from ...core.workspace import WorkspaceStore, WindowSlot
from ...core.commands.bridge import UI, Command, Menu
from ...ui.layout.manager import LayoutManager
from ...core.state import StateStore
from ...ui.window import WindowStateController
from ...core.qt.dispatcher import Dispatcher, CancelToken
from ...core.qt.thread import utility_pool
from ...core.platform.taskbar import apply_window_identity

AppMenuRegistrar.setup_menu()


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, icon=None, parent=None, slot_id=None):
        super().__init__(parent=parent)
        self._workspace_store = WorkspaceStore.instance()
        self.slot_id = None
        self._slot_entry: WindowSlot | None = None
        self._slot_deleted = False
        self._slot_ready = False
        self._folder_callout: CalloutOverlay | None = None
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
        UI.register_instance("SearchService", self.search_service)
        t.set_locale(app_settings.get("window/language", "en"))
        UI.register_instance("MainWindow", self)
        from .grid.overlay_host import GridOverlayHost

        self.grid_overlay_host = GridOverlayHost(lambda: self.database_path, lambda: self.database_name, parent=self)
        UI.register_instance("GridOverlayHost", self.grid_overlay_host)
        self._closed = False
        self.setup_ui()
        self._show_loading()
        self._acquire_slot_async(slot_id)
        apply_window_identity(self.winId())

    def _acquire_slot_async(self, requested_id):
        store = self._workspace_store

        def task():
            sid, entry, existed = store.acquire_slot(requested_id)
            self._dispatcher.invoke(lambda: self._on_slot_acquired(sid, entry, existed))

        self._dispatcher.post(task, priority=9)

    def _on_slot_acquired(self, sid, entry, existed):
        self.slot_id = sid
        self._slot_entry = entry
        self._slot_ready = True
        AppLogger.info(f"New Window Running : {APP_NAME} (slot={self.slot_id})")
        self.start_ipc_listener()
        self._update_title()
        self.workspace_toolbar_widget.refresh()
        if existed and entry:
            self._restore_from_slot(entry)
        else:
            self.reload_database(self.get_last_used_db_name())
        self._check_first_run_plugin_panel()
        self._run_panel_plugin_startups()

    @profiler.profile
    def get_last_used_db_name(self):
        names = list_setting_db_names()
        if not names:
            return DEFAULT_DB_NAME
        prevname = self._workspace_store.get_last_used_database_name()
        if prevname and prevname in names:
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
        self.grid_overlay_host.reload()
        if on_complete:
            on_complete()
        else:
            self.search_row_widget.run_folder_worker(
                self.database_path,
                self.folder_view.get_selected_paths(),
                self.search_service.get("include_subfolders", True),
                self.search_service.get("include_contained_files", True),
            )
            QtCore.QTimer.singleShot(0, lambda: self.search(force=True))
        self._check_folder_callout(roots)

    def _on_db_reload_failed(self, name, exc):
        self._db_reload_cancel = None
        self._hide_loading()
        Notifier.error(f'Failed to load database "{name}"')

    def _check_first_run_plugin_panel(self):
        import os
        from ...plugin.settings import _ini_path

        if not os.path.isfile(_ini_path()):
            QtCore.QTimer.singleShot(0, lambda: self._layout_manager.toggle_panel("Plugin Manager"))

    def _check_folder_callout(self, roots):
        if roots:
            self._dismiss_folder_callout()
            return
        if self._folder_callout is not None:
            return
        add_btn = getattr(self, "_add_folder_btn", None)
        if add_btn is None:
            return
        callout = CalloutOverlay(add_btn, t("add folders from here"))
        callout.dismissed.connect(self._on_folder_callout_dismissed)
        add_btn.pressed.connect(self._dismiss_folder_callout)
        self._folder_callout = callout
        QtCore.QTimer.singleShot(300, self._show_folder_callout)

    def _show_folder_callout(self):
        if self._folder_callout is None:
            return
        if self.setting_db and self.setting_db.get_all_parent_folders():
            self._dismiss_folder_callout()
            return
        self._folder_callout.show()

    def _dismiss_folder_callout(self):
        if self._folder_callout is not None:
            self._folder_callout.dismiss()

    def _on_folder_callout_dismissed(self):
        self._folder_callout = None

    def _update_title(self):
        dirs = self.folder_view.get_selected_paths()
        if dirs:
            label = ", ".join(d.rsplit("/", 1)[-1] or d for d in dirs)
        else:
            label = self.database_name or ""
        self.setWindowTitle(f"{label}" if label else APP_NAME)

    @qt_debounce(200)
    def refresh_db_selector(self):
        if not hasattr(self, "database_combo"):
            return
        names = list_setting_db_names()
        if not names:
            names = ["default"]
        self.database_combo.setItems(names)
        self.database_combo.setCurrentText(self.database_name)
        AppLogger.debug("refresh_db_selector")

    def _is_my_db(self, db: str) -> bool:
        return not db or db == self.database_name

    @QtCore.Slot(str)
    def _on_db_created(self, name: str):
        if self.database_combo.combo.findText(name) < 0:
            self.database_combo.addItem(name)

    @QtCore.Slot(str)
    def _on_db_deleted(self, name: str):
        self.database_combo.removeItem(name)
        if self.database_name == name:
            self.reload_database(self.database_combo.currentText())

    @QtCore.Slot(str, int)
    def update_progress_value(self, db, value):
        if self._is_my_db(db):
            self.progress_bar.setProgress(int(value))

    @QtCore.Slot(str, int)
    def update_progress_maximum(self, db, value):
        if self._is_my_db(db):
            self.progress_bar.setMaximum(int(value))

    def start_ipc_listener(self):
        node = Node("viewer")
        node.session_id = self.slot_id
        self._bridge = ViewerIpcBridge(node, parent=self)
        self._node = node

        b = self._bridge
        b.db_content_updated.connect(self._on_db_content_updated)
        b.folder_changed.connect(self._on_folder_changed_ipc)
        b.progress_updated.connect(self.update_progress_value)
        b.progress_maximum.connect(self.update_progress_maximum)
        b.show_toggled.connect(self.toggle_show)
        b.slot_closed.connect(self._on_slot_closed)
        b.slot_restarted.connect(self._on_slot_restarted)
        b.db_created.connect(self._on_db_created)
        b.db_deleted.connect(self._on_db_deleted)
        b.remote_log_received.connect(self._on_dev_log)

        b.tags_updated.connect(self._on_tags_updated_overlay)

        b.settings_received.connect(app_settings.apply_remote)
        app_settings.committed.connect(b.broadcast_settings)

        b.start()
        UI.register_instance("ViewerIpcBridge", b)

    @profiler.profile
    def setup_ui(self):
        self._layout_manager = LayoutManager(self)
        self._layout_manager.set_margin(dpix(5))

        self.folder_view = LazyFolderTreeView()
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        self.progress_bar = ThinProgressBar()
        self.workspace_toolbar_widget = WorkspaceToolbarWidget()
        UI.register_instance("WorkspaceToolbarWidget", self.workspace_toolbar_widget)
        self.iconbar = IconButtonBar(
            left_buttons=[
                IconButtonConfig("menu", "All Menu", lambda: Menu.session(self).all_roots().exec()),
                IconButtonConfig("gear", "Settings", lambda: Menu.session(self).from_folder("Setting").exec()),
                IconButtonConfig("window", "Window", lambda: Menu.session(self).from_folder("Window").exec()),
                IconButtonConfig(
                    "layout_edit",
                    "Edit Layout",
                    lambda: Menu.session(self).from_folder("Panels").exec(),
                ),
            ],
            right_buttons=[
                IconButtonConfig("folder_plus", "Add Folder", lambda: Command.invoke("ft.add_folder")),
                IconButtonConfig("query", "Query", self._show_query_menu),
            ],
        )
        self._add_folder_btn = self.iconbar.find_button("folder_plus", side="right")
        self._layout_edit_btn = self.iconbar.left_buttons[2]
        self._layout_manager.mode_changed.connect(self._on_layout_mode_changed)
        self.database_combo = ComboBoxWithButtons()
        self.database_combo.textChanged.connect(self.reload_database)
        self.database_combo.addClicked.connect(lambda: Command.invoke("db.add_database"))
        self.database_combo.removeClicked.connect(lambda: Command.invoke("db.remove_database"))

        self.search_row_widget = SearchContainer()
        UI.register_instance("SearchContainer", self.search_row_widget)
        self.search_row_widget.filter_changed.connect(self._on_search_setting_changed)

        from .state_coordinator import PathStateCoordinator, QueryStateCoordinator, UIStateCoordinator

        self.ui_coord = UIStateCoordinator(self)
        self.path_coord = PathStateCoordinator(self)
        self.query_coord = QueryStateCoordinator(self)

        self.grid_items = GridItemModel(self)
        self.grid_view = GridView(self, self.grid_items)
        self.grid_view.verticalScrollBar().setSingleStep(25)
        self.grid_view.horizontalScrollBar().setSingleStep(25)
        self.grid_view.base_height_changed.connect(self._on_zoom_changed)
        self.grid_overlay_host.changed.connect(lambda: self.grid_view.viewport().update())

        self.file_model = FileViewModel(dbpath_getter=lambda: self.database_path, parent=self)
        self.content_viewer = ContentViewerWidget()
        self.meta_viewer_widget = MetaViewerWidget()
        self.file_list_provider = FileListProvider(self.file_model, self.grid_items, self)
        self.file_viewer = FileViewerController(self.file_model, self.content_viewer, self.meta_viewer_widget, self.file_list_provider, self)
        self.meta_viewer_widget.reload_requested.connect(self.file_viewer.reload_meta)
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
        self.sync_service_from_ui()

    def _create_toolbar_panel(self):
        panel = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.workspace_toolbar_widget)
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

    def _on_layout_mode_changed(self, mode):
        from ...ui.layout.manager import MODE_EDIT

        is_edit = mode == MODE_EDIT
        self._layout_edit_btn.blockSignals(True)
        self._layout_edit_btn.setChecked(is_edit)
        self._layout_edit_btn.blockSignals(False)

    def _register_component_states(self):
        store = StateStore.instance()
        store.register("layout", self._save_layout, self._restore_layout)
        store.register("grid", self._save_grid, self._restore_grid)
        self._register_grid_plugin_states(store)
        self._register_panel_plugin_states(store)

    def _register_grid_plugin_states(self, store):
        from ...plugin.grid.base import WidgetGridPlugin as _WGP
        from .grid.grid_view import grid_resolver

        for name, _cls in grid_resolver.registry.all_classes():
            inst = grid_resolver.registry.instance(name)
            if inst is not None and isinstance(inst, _WGP):
                p = inst
                store.register(
                    f"grid_plugin.{name}",
                    lambda p=p: p.save_ui_state(),
                    lambda s, p=p: p.restore_ui_state(s),
                )

    def _save_layout(self):
        return self._layout_manager.save_state()

    def _restore_layout(self, state):
        self._layout_manager.restore_state(state)

    def _save_grid(self):
        return {
            "zoom": self.grid_view.base_height,
            "orientation": self.grid_view.orientation,
            "layout_mode": self.grid_view.layout_mode,
            "scroll_index": self.grid_view.get_center_image_index(),
            "scroll_anchor": self.grid_view.scroll_anchor,
            "follow_selection_on_update": self.grid_view.follow_selection_on_update,
        }

    def _restore_grid(self, state):
        if "zoom" in state:
            self.grid_view.base_height = state["zoom"]
            self.grid_view._zoom_restore_guard = True
        if "orientation" in state:
            self.grid_view.set_orientation(state["orientation"])
        if "layout_mode" in state:
            self.grid_view.set_layout_mode(state["layout_mode"])
        if state.get("scroll_index") is not None:
            self.grid_view.set_pending_scroll_index(state["scroll_index"])
        anchor = state.get("scroll_anchor")
        if isinstance(anchor, str):
            if anchor in ("top", "center"):
                self.grid_view.set_scroll_anchor(anchor)
            elif anchor == "grid.scroll_anchor_top":
                self.grid_view.set_scroll_anchor("top")
            elif anchor == "grid.scroll_anchor_center":
                self.grid_view.set_scroll_anchor("center")
        follow = state.get("follow_selection_on_update")
        if isinstance(follow, bool):
            self.grid_view.set_follow_selection_on_update(follow)
        if "zoom" in state:
            self.grid_view.layout_ready.connect(self._clear_zoom_restore_guard, QtCore.Qt.SingleShotConnection)

    def _clear_zoom_restore_guard(self):
        self.grid_view._zoom_restore_guard = False

    def sync_service_from_ui(self):
        dirs = self.folder_view.get_selected_paths()
        self.search_service.set_entries_builder(
            lambda: self.search_row_widget.build_filter_entries(
                self.folder_view.get_selected_paths(),
                self.search_service.get("include_subfolders", True),
                self.search_service.get("include_contained_files", True),
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

    def _on_search_setting_changed(self):
        self.sync_service_from_ui()
        self.search_service.execute_if_auto()

    @QtCore.Slot()
    def _reload_folderlist_now(self):
        AppLogger.debug("[RUNNING] reload_folderlist")
        if self.setting_db:
            roots = self.setting_db.get_all_parent_folders()
            excluded = self.setting_db.get_all_ignore_folders()
            if self.folder_view.is_structure_current(roots, excluded):
                if roots:
                    self._dismiss_folder_callout()
                return
            if self.folder_view.defer_reload_if_editing(self._reload_folderlist_now, strong=True):
                return
            scroll_state = self.folder_view.capture_scroll_state()
            state = self.folder_view.get_state()
            self.folder_view.set_folders(roots, excluded)
            self.folder_view.set_state(state, scroll_to_selection=False)
            self.folder_view.restore_scroll_state(scroll_state)
            if roots:
                self._dismiss_folder_callout()
        else:
            if self.folder_view.defer_reload_if_editing(self.folder_view.reload_tree):
                return
            self.folder_view.reload_tree()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        self._reload_folderlist_now()

    def changeEvent(self, event):
        super().changeEvent(event)
        callout = getattr(self, "_folder_callout", None)
        if callout is None:
            return
        etype = event.type()
        if etype == QtCore.QEvent.ActivationChange:
            if self.isActiveWindow():
                callout.resume()
            else:
                callout.suspend()
        elif etype == QtCore.QEvent.WindowStateChange and self.isMinimized():
            callout.suspend()

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

    @QtCore.Slot(str, bool)
    def toggle_show(self, db, show):
        if not self._is_my_db(db):
            return
        if show:
            self.window_state.restore_or_activate()
        else:
            self.window_state.minimize()

    @QtCore.Slot()
    def close_by_slot_delete(self):
        self._slot_deleted = True
        self.close()

    def _perform_system_restart(self, include_self=False):
        from ...core.platform.process import AppProcess

        node = getattr(self, "_node", None)
        if node:
            store = self._workspace_store
            active_ids = store.get_active_slot_ids()
            own_sid = self.slot_id
            restore_ids = active_ids if include_self else [sid for sid in active_ids if sid != own_sid]
            if restore_ids:
                store.set_restore_slot_ids(restore_ids)
            for sid in active_ids:
                if sid != own_sid:
                    node.send("slot.restart", sid, dst="viewer")

        AppProcess.terminate_cmd("--tray", wait=True)
        AppProcess.new_main("--tray")

    def _restart_other_viewers(self):
        node = getattr(self, "_node", None)
        if not node:
            return
        store = self._workspace_store
        active_ids = store.get_active_slot_ids()
        for sid in active_ids:
            if sid != self.slot_id:
                node.send("slot.restart", sid, dst="viewer")

    @QtCore.Slot()
    def close_by_restart(self):
        self._save_slot()
        from ...core.platform.process import AppProcess

        args = ["--viewer"]
        if self.slot_id:
            args += ["--slot", self.slot_id]
        AppProcess.new_main(*args)
        self.close()

    @QtCore.Slot()
    def raise_window(self):
        self.window_state.restore_or_activate()

    @QtCore.Slot(bool)
    def search(self, force=False):
        self.sync_service_from_ui()
        self.search_service.execute(force=force)

    @QtCore.Slot(str)
    def _on_db_content_updated(self, db: str):
        if not self._is_my_db(db):
            return
        if not self.search_service.get("auto_execute_on_update", True):
            return
        self.search_row_widget.invalidate_key_cache()
        self.search(force=True)

    @QtCore.Slot(dict)
    def _on_tags_updated_overlay(self, payload: dict):
        if not self._is_my_db(payload.get("db", "")):
            return
        from .preview.tag_edit_service import TagEditService

        TagEditService.instance().handle_ack(payload)
        self.grid_overlay_host.reload()

    @QtCore.Slot(str)
    def _on_folder_changed_ipc(self, db: str):
        if not self._is_my_db(db):
            return
        self.reload_folderlist()

    @QtCore.Slot(str)
    def _on_slot_closed(self, slot_id: str):
        if slot_id == self.slot_id:
            self.close_by_slot_delete()

    @QtCore.Slot(str)
    def _on_slot_restarted(self, slot_id: str):
        if slot_id == self.slot_id:
            self.close_by_restart()

    def _show_query_menu(self):
        Menu.session(self).from_folder("Query").exec()

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
        self.search_row_widget.run_folder_worker(
            self.database_path,
            self.folder_view.get_selected_paths(),
            self.search_service.get("include_subfolders", True),
            self.search_service.get("include_contained_files", True),
        )
        self.grid_overlay_host.reload()
        if paths == self._last_paths:
            self._hide_loading()
            return
        self._last_paths = paths
        self.grid_view.set_paths(paths, sources, aspects, keep_scroll=keep_scroll)
        self.file_list_provider.on_search_results(paths, sources)

    def _restore_from_slot(self, entry: WindowSlot, skip_window_state=False):
        def after_path():
            self.query_coord.restore(entry.query)
            self.ui_coord.restore(entry.ui, skip_window_state=skip_window_state)

        self.path_coord.restore(entry.path, on_complete=after_path)

    def _save_slot(self):
        if self._slot_deleted or not self._slot_ready or not self.slot_id:
            return
        entry = self._slot_entry or WindowSlot(slot_id=self.slot_id)
        entry.ui = self.ui_coord.capture()
        entry.path = self.path_coord.capture()
        entry.query = self.query_coord.capture()
        self._workspace_store.save_slot(entry)
        self._slot_entry = entry

    def closeEvent(self, event):
        self.on_close()
        super().closeEvent(event)

    def on_close(self):
        if self._closed:
            return
        self._closed = True
        if self._folder_callout:
            self._folder_callout.close()
            self._folder_callout = None
        try:
            self._save_slot()
            app_settings.commit()
            t.dump_missing_keys()
        except Exception as e:
            AppLogger.warning(f"on_close failed: {e}", exc=e)
        try:
            from ...plugin.settings import PluginSettings
            from ...plugin.installer import RestartScope
            from ...plugin.loader import get_plugin_dir

            ps = PluginSettings()
            scope = ps.needs_restart(get_plugin_dir())
            if scope != RestartScope.NONE:
                ps.clear_restart_scope()
                if RestartScope.TRAY in scope:
                    self._perform_system_restart()
                elif RestartScope.VIEWER in scope:
                    self._restart_other_viewers()
        except Exception as e:
            AppLogger.warning(f"on_close restart failed: {e}", exc=e)
        try:
            if hasattr(self, "_bridge"):
                AppLogger.info("on_close [STOPPING]")
                self._bridge.stop()
        except Exception as e:
            AppLogger.debug(f"on_close bridge.stop failed: {e}")

    def _register_panel_plugin_states(self, store):
        from ...plugin.panel.base import BasePanelPlugin
        from ...plugin.panel.handler import panel_registry

        for cls in panel_registry.list_all():
            inst = panel_registry.instance(cls.NAME)
            if inst is not None and isinstance(inst, BasePanelPlugin):
                p = inst
                store.register(
                    f"panel_plugin.{cls.NAME}",
                    lambda p=p: p.save_ui_state(),
                    lambda s, p=p: p.restore_ui_state(s),
                )

    def _register_panel_plugins(self):
        from ...plugin.panel.handler import panel_registry

        for cls in panel_registry.list_all():
            plugin = panel_registry.instance(cls.NAME)
            if plugin is None:
                continue
            name = plugin.DISPLAY_NAME or plugin.NAME
            self._layout_manager.register(
                name,
                plugin.create_widget,
                closable=plugin.CLOSABLE,
            )

    def _run_panel_plugin_startups(self):
        from ...plugin.panel.base import BasePanelPlugin
        from ...plugin.panel.handler import panel_registry

        for cls in panel_registry.list_all():
            plugin = panel_registry.instance(cls.NAME)
            if plugin is None or not isinstance(plugin, BasePanelPlugin):
                continue
            try:
                plugin.startup()
            except Exception as e:
                AppLogger.warning(f"Failed to start panel plugin: {cls.NAME}", exc=e)

    @QtCore.Slot(str, str, str, str)
    def _on_dev_log(self, level: str, text: str, src: str, db: str):
        from ...builtins.log_panel import LogPanel

        panel = LogPanel.instance()
        if panel is not None:
            panel.append_log(level, text, src=src, db=db)

from PySide6 import QtWidgets, QtGui, QtCore
from datetime import datetime, timedelta
import atexit

from .viewer.justifiedwidget import JustifiedVirtualScrollWidget
from ..core.setting_db import SettingDB
from ..core.query import MetaInfoSearchEngine, MetaQuery
from ..core.zmq import ZMQSubscriber
from ..debounce import qt_debounce
from .widgets.loading_overlay import OverlayLoadingIndicator
from .widgets.foldertree import FolderTreeView
from .widgets.foldertree_menu import FolderContextMenuBuilder
from .widgets.query_options import SingleRowOption
from .widgets.scrollarea import InertialScrollArea, AutoScrollArea
from .widgets.progress_bar import ThinProgressBar
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .thread import main_thread
from .viewer_settings import main_setting
from ..constants import data_db_name, setting_db_name
from ..profiling import logger, profiler
from ..settings.setting_window import SettingsWindow
from ..settings.db_settings import DataBaseSettings
class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object)

class SearchWorkerRunnable(QtCore.QRunnable):
    def __init__(self, db_name, query):
        super().__init__()
        self.engine = MetaInfoSearchEngine(db_name)
        self.query = query
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile  # プロファイル対象に追加
    def run(self):
        if self._cancelled:
            return
        try:
            # self.engine.explain_query_plan(MetaQuery(**self.search_kwargs))
            paths, aspects = self.engine.get(self.query)
        except Exception as e:
            logger.exception(f"[SearchWorker] Search failed: {e}")
            return
        if self._cancelled:
            return
        self.signals.finished.emit(paths, aspects)

class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Justified Layout Viewer")
        self.resize(1000, 700)

        self.current_runnable = None
        self._is_fullscreen = False
        self.run_folder = True

        self.query_timeout_threshold = timedelta(seconds=5)
        self.current_query_start_time = None
        self.query_lock = QtCore.QMutex()
        self.pending_query = None
        self.last_executed_query = None

        self.setting_db = SettingDB(setting_db_name)
        main_thread.watch_start()

        self.dbname = data_db_name

        self.main_ui()
        self.start_ipc_listener()
        QtCore.QTimer.singleShot(100, self.search)
        atexit.register(self.on_close)

    @QtCore.Slot(int)
    def update_current(self, value):
        self.progress_bar.setProgress(int(value))
        self._reset_if_done()

    @QtCore.Slot(int)
    def update_maximum(self, value):
        self.progress_bar.setMaximum(int(value))
        self._reset_if_done()

    def _reset_if_done(self):
        if self.progress_bar.maximum() > 0 and self.progress_bar.value() >= self.progress_bar.maximum():
            self.progress_bar.setProgress(0)
            self.progress_bar.setMaximum(0)

    def start_ipc_listener(self):
        def on_message(msg: str):
            topic, _, event = msg.partition(":")
            handlers = {
                "update": lambda: QtCore.QMetaObject.invokeMethod(self, "search", QtCore.Qt.QueuedConnection,  QtCore.Q_ARG(bool, True)),
                "progress": lambda: QtCore.QMetaObject.invokeMethod(self, "update_current", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, int(event))),
                "maximum": lambda: QtCore.QMetaObject.invokeMethod(self, "update_maximum", QtCore.Qt.QueuedConnection, QtCore.Q_ARG(int, int(event))),
                "folderchanged": lambda: QtCore.QMetaObject.invokeMethod(self, "reload_folderlist", QtCore.Qt.QueuedConnection),
            }
            try:
                handlers.get(topic, lambda: None)()
            except Exception:
                logger.exception("Error processing IPC message: %s", msg)

        self._subscriber = ZMQSubscriber(topic_filter=["update", "progress", "maximum", "folderchanged"])
        self._subscriber.connect_on_message(on_message)
        self._subscriber.start()

    @profiler.profile
    def main_ui(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.folder_view = FolderTreeView(self.setting_db.get_all_parent_folders(), self.setting_db.get_all_ignore_folders())
        menu_builder = FolderContextMenuBuilder(self.folder_view, self.setting_db.db_name)
        self.folder_view.set_context_menu_builder(menu_builder)
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(4, 4, 4, 4)
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        self.only_direct_children = main_setting.get("query/only_direct_children", False)
        
        self.iconbar = IconButtonBar(left_buttons=[
            IconButtonConfig("icons/settings.png", "Settings", lambda: self.show_settings()),
            IconButtonConfig("icons/open.png", "Add File", lambda: self.add_new_folder()),
        ], right_buttons=[
            IconButtonConfig("icons/save.png", "Bot Only", self.toggle_only_direct_children, checkable=True, checked=self.only_direct_children),
            IconButtonConfig("icons/save.png", "AutoScroll", lambda: self.auto_scroll()),
            IconButtonConfig("icons/save.png", "Full Screen", lambda: self.toggle_fullscreen()),
        ])
        self.left_layout.addWidget(self.iconbar)

        self.progress_bar = ThinProgressBar()
        self.left_layout.addWidget(self.progress_bar)
        self.left_layout.addWidget(self.folder_view)

        right_panel = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(4, 4, 4, 4)
        self.right_layout.setSpacing(6)

        self.search_row_widget = SingleRowOption(self)
        self.search_row_widget.settingchanged.connect(self.search)
        self.right_layout.addWidget(self.search_row_widget)

        self.viewer = AutoScrollArea()
        self.viewer.setWidgetResizable(True)
        self.viewer.verticalScrollBar().setSingleStep(25)

        self.content = JustifiedVirtualScrollWidget(self.viewer)
        self.viewer.setWidget(self.content)
        self.right_layout.addWidget(self.viewer)

        self.splitter.addWidget(right_panel)
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        geo = main_setting.get("window/geometry", None)
        if geo:
            self.restoreGeometry(geo)
        sizes = main_setting.get("window/splitter", None)
        if sizes:
            self.splitter.setSizes(sizes)

        self.loading_indicator = OverlayLoadingIndicator(self.viewer)
        self.content.layout_ready.connect(self.loading_indicator.stop)

    @profiler.profile
    def add_new_folder(self):
        folder_path = QtWidgets.QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder_path:
            self.setting_db.add_parent_folder(folder_path)
            self.folder_view.set_root_paths(self.setting_db.get_all_parent_folders())

    @profiler.profile
    def build_search_query(self):
        kwargs = self.search_row_widget.get_values()
        kwargs.update({
            "directories": self.folder_view.get_selected(),
            "only_direct_children": self.only_direct_children
        })
        return MetaQuery(**kwargs)

    def show_settings(self):
        window = SettingsWindow(self)
        window.add_tab(DataBaseSettings())
        window.show()

    @QtCore.Slot()
    @qt_debounce(1000)
    def reload_folderlist(self):
        self.folder_view.reload_async()

    def toggle_only_direct_children(self, checked):
        logger.info(checked)
        self.only_direct_children = checked
        main_setting.set("query/only_direct_children", checked)
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

    @qt_debounce(150)
    @QtCore.Slot(bool)
    @profiler.profile
    def search(self, force=False):
        query = self.build_search_query()
        now = datetime.now()

        if not force:
            if (self.current_runnable and query == self.current_runnable.query) or \
            (self.last_executed_query and query == self.last_executed_query):
                return

        with QtCore.QMutexLocker(self.query_lock):
            # 実行中の検索がある場合
            if self.current_runnable:
                elapsed = now - self.current_query_start_time if self.current_query_start_time else timedelta.max

                if elapsed < self.query_timeout_threshold:
                    # 5秒以内ならキャンセルして実行
                    self.current_runnable.cancel()
                else:
                    logger.info("[SEARCH] query is taking more than expected, continueing without cancel.")
                    # 5秒以上かかってるならキャンセルせず、最新だけ保留
                    self.pending_query = query
                    return

            # 実行中でなければそのまま開始
            self.pending_query = None
            self._start_search_runnable(query)

    @profiler.profile
    def _start_search_runnable(self, query):
        self.loading_indicator.start()
        runnable = SearchWorkerRunnable(self.dbname, query)
        runnable.signals.finished.connect(self.on_search_finished)
        self.current_runnable = runnable
        main_thread.start(runnable, 7)

    @QtCore.Slot(object, object)
    @profiler.profile
    def on_search_finished(self, paths, aspects):
        self.last_executed_query = self.current_runnable.query
        self.current_runnable = None
        self.current_query_start_time = None
        self.content.set_precalculated_meta(paths, aspects)
        self.content.reload_visible_images()
        self.search_row_widget.run_folder_worker()
                
        with QtCore.QMutexLocker(self.query_lock):
            if self.pending_query:
                query = self.pending_query
                self.pending_query = None
                self._start_search_runnable(query)

    def on_close(self):
        if hasattr(self, "_subscriber"):
            self._subscriber.stop()

    def closeEvent(self, event):
        self.folder_view.save_state()
        main_setting.set("window/geometry", self.saveGeometry())
        main_setting.set("viewer/scroll", self.content.get_center_image_index())
        main_setting.set("window/splitter", self.splitter.sizes())
        main_setting.commit()
        self.on_close()
        return super().closeEvent(event)
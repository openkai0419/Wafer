from PySide6 import QtWidgets, QtGui, QtCore

from .viewer.justifiedwidget import JustifiedVirtualScrollWidget
from ..core.setting_db import SettingDB
from ..core.query import MetaInfoSearchEngine, MetaQuery
from ..core.zmq import ZMQSubscriber
from .widgets.foldertree import FolderTreeView
from .widgets.foldertree_menu import FolderContextMenuBuilder
from .widgets.settingwidget import SingleRowOption
from .widgets.scrollarea import InertialScrollArea, AutoScrollArea
from .widgets.progress_bar import ThinProgressBar
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .thread import main_thread
from .viewer_settings import main_setting
from ..constants import data_db_name, setting_db_name
from ..profiling import init_env

logger, profiler = init_env()

class FullscreenWindow(QtWidgets.QWidget):
    def __init__(self, content_widget: QtWidgets.QWidget, exit_callback):
        super().__init__()
        self.setWindowFlags(QtCore.Qt.Window)
        self.setLayout(QtWidgets.QVBoxLayout())
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addWidget(content_widget)
        self._original_widget = content_widget
        self._exit_callback = exit_callback

    def keyPressEvent(self, event):
        if event.key() == QtCore.Qt.Key_Escape:
            self._exit_callback()

class WorkerSignals(QtCore.QObject):
    finished = QtCore.Signal(object, object)

class SearchWorkerRunnable(QtCore.QRunnable):
    def __init__(self, engine, search_kwargs):
        super().__init__()
        self.engine = engine
        self.search_kwargs = search_kwargs
        self.signals = WorkerSignals()
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile  # プロファイル対象に追加
    def run(self):
        if self._cancelled:
            return
        #self.engine.explain_query_plan(MetaQuery(**self.search_kwargs))
        paths, aspects = self.engine.get(MetaQuery(**self.search_kwargs))
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

        self.setting_db = SettingDB(setting_db_name)
        main_thread.watch_start()

        self.engine = MetaInfoSearchEngine(data_db_name)
        self.main_ui()
        self.start_ipc_listener()
        QtCore.QTimer.singleShot(0, self.search)

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

        self.folder_view = FolderTreeView(self.setting_db.get_all_parent_folders())
        menu_builder = FolderContextMenuBuilder(self.folder_view, self.setting_db.db_name)
        self.folder_view.set_context_menu_builder(menu_builder)
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(4, 4, 4, 4)
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        self.iconbar = IconButtonBar(left_buttons=[
            IconButtonConfig("icons/open.png", "Open File", lambda: self.add_new_folder()),
            IconButtonConfig("icons/save.png", "Save File", lambda: print("Save clicked")),
        ], right_buttons=[
            IconButtonConfig("icons/settings.png", "Settings", lambda: print("Settings clicked"), checkable=True),
        ])
        self.left_layout.addWidget(self.iconbar)

        self.progress_bar = ThinProgressBar()
        self.left_layout.addWidget(self.progress_bar)
        self.left_layout.addWidget(self.folder_view)

        right_panel = QtWidgets.QWidget()
        self.right_layout = QtWidgets.QVBoxLayout(right_panel)
        self.right_layout.setContentsMargins(4, 4, 4, 4)
        self.right_layout.setSpacing(6)

        self.row_widget = SingleRowOption(self)
        self.row_widget.settingchanged.connect(self.search)
        self.right_layout.addWidget(self.row_widget)

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

        self.fullscreen_window = None
        btn_fs = QtWidgets.QPushButton("全画面")
        btn_fs.clicked.connect(self.toggle_fullscreen)
        self.right_layout.addWidget(btn_fs)

    def add_new_folder(self):
        folder_path = QtWidgets.QFileDialog.getExistingDirectory(self, "フォルダを選択")
        if folder_path:
            self.setting_db.add_parent_folder(folder_path)
            self.folder_view.set_root_paths(self.setting_db.get_all_parent_folders())

    def build_search_query(self):
        kwargs = self.row_widget.get_values()
        kwargs.update({
            "directories": self.folder_view.get_selected(),
            "only_direct_children": False
        })
        return kwargs

    @QtCore.Slot()
    def reload_folderlist(self):
        self.folder_view.reload_async()

    def toggle_fullscreen(self):
        if not self._is_fullscreen:
            self.viewer.setParent(None)
            self.fullscreen_window = FullscreenWindow(self.viewer, self.exit_fullscreen)
            self.fullscreen_window.showFullScreen()
            self._is_fullscreen = True
        else:
            self.exit_fullscreen()

    def exit_fullscreen(self):
        if self.fullscreen_window:
            self.viewer.setParent(None)
            self.right_layout.insertWidget(1, self.viewer)
            self.fullscreen_window.close()
            self.fullscreen_window = None
            self._is_fullscreen = False

    def moveEvent(self, event):
        super().moveEvent(event)
        self.row_widget.on_move_event()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.row_widget.on_move_event()

    def auto_scroll(self):
        if self.viewer.isscrolling():
            self.viewer.stop_auto_scroll()
        else:
            self.viewer.start_auto_scroll(1, 1)

    @profiler.profile
    def on_folder_selected(self, selected_path):
        self.run_folder = True
        self.search()
        self.auto_scroll()

    @profiler.profile
    @QtCore.Slot(bool)
    def search(self, force=False):
        search_kwargs = self.build_search_query()

        if self.current_runnable:
            if search_kwargs == self.current_runnable.search_kwargs and not force:
                return
            self.current_runnable.cancel()

        runnable = SearchWorkerRunnable(self.engine, search_kwargs)
        runnable.signals.finished.connect(self.on_search_finished)
        self.current_runnable = runnable
        main_thread.start(runnable, 7)

    @QtCore.Slot(object, object)
    def on_search_finished(self, paths, aspects):
        self.content.set_precalculated_meta(paths, aspects)
        self.content.reload_visible_images()
        self.row_widget.run_folder_worker()

    def closeEvent(self, event):
        self.folder_view.save_state()
        main_setting.set("window/geometry", self.saveGeometry())
        main_setting.set("viewer/scroll", self.content.get_center_image_index())
        main_setting.commit()
        if hasattr(self, "_subscriber"):
            self._subscriber.stop()
        return super().closeEvent(event)

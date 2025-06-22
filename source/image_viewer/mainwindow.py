import sys
import os
from PySide6 import QtWidgets, QtGui, QtCore
import threading
from multiprocessing.connection import Listener

from .viewer.justifiedwidget import JustifiedVirtualScrollWidget
from ..core.query import MetaInfoSearchEngine, MetaQuery
from ..core.zmq import ZMQSubscriber
from .widgets.multiroottree import FolderTreeView
from .widgets.settingwidget import SingleRowOption
from .widgets.scrollarea import InertialScrollArea, AutoScrollArea
from .widgets.progress_bar import ThinProgressBar
from .widgets.button_bar import IconButtonBar, IconButtonConfig
from .thread import main_thread
from .viewer_settings import main_setting
from ..constants import data_db
from ..profiling import init_env
logger, profiler = init_env("viewer")

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

    def run(self):
        if self._cancelled:
            return
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
        self.run_folder = True
        
        main_thread.watch_start()

        self.engine = MetaInfoSearchEngine(data_db)
        self.main_ui()
        QtCore.QTimer.singleShot(0, self.search)
        self.start_ipc_listener()

    def update_current(self, current):
        pass

    def update_maximum(self, max):
        pass

    def start_ipc_listener(self):
        def on_message(msg: str):
            try:
                _, event = msg.split(":", 1)
            except ValueError:
                event = msg
            if "update" in event:
                logger.info(event)
                QtCore.QMetaObject.invokeMethod(self, "search", QtCore.Qt.QueuedConnection)

        self._subscriber = ZMQSubscriber(topic_filter="update")
        self._subscriber.connect_on_message(on_message)
        self._subscriber.start()

    @profiler.profile
    def main_ui(self):
        self.splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
        self.setCentralWidget(self.splitter)

        self.base_paths = [
        r"M:\\collect\\picture\\ーNovelAI\\1_7_NAI4",
        r"M:\\collect\\picture\\ーNovelAI\\1_8_NAI4.5",
        r"C:\\Users\\openk\\Downloads",
        r"M:\\collect\\picture\\ーNovelAI\\1_6_XL",
        ]


        self.folder_view = FolderTreeView(self.base_paths)
        self.folder_view.folder_selected.connect(self.on_folder_selected)

        left_panel = QtWidgets.QWidget()
        self.left_layout = QtWidgets.QVBoxLayout(left_panel)
        self.left_layout.setContentsMargins(4, 4, 4, 4)
        self.left_layout.setSpacing(0)
        self.splitter.addWidget(left_panel)

        # 使用例
        def on_open(): print("Open clicked")
        def on_save(): print("Save clicked")
        def on_settings(): print("Settings clicked")

        left = [
            IconButtonConfig("icons/open.png", "Open File", on_open),
            IconButtonConfig("icons/save.png", "Save File", on_save),
        ]
        right = [
            IconButtonConfig("icons/settings.png", "Settings", on_settings, checkable=True),
        ]

        self.iconbar = IconButtonBar(left_buttons=left, right_buttons=right)
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

        #self.viewer = InertialScrollArea()
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

    def toggle_fullscreen(self):
        if self.fullscreen_window is None:
            # self.content を一時的に切り離して新ウィンドウへ
            self.viewer.setParent(None)
            self.fullscreen_window = FullscreenWindow(self.viewer, self.exit_fullscreen)
            self.fullscreen_window.showFullScreen()
        else:
            self.exit_fullscreen()

    def exit_fullscreen(self):
        if self.fullscreen_window:
            # 元の中央レイアウトに content を戻す
            self.viewer.setParent(None)
            self.right_layout.insertWidget(1, self.viewer)
            self.fullscreen_window.close()
            self.fullscreen_window = None

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
    def search(self, *args, **kwargs):
        kwargs = self.row_widget.get_values()
        kwargs["directories"] = self.folder_view.get_selected()
        kwargs["only_direct_children"] = False

        if self.current_runnable:
            self.current_runnable.cancel()

        print(kwargs)
        runnable = SearchWorkerRunnable(self.engine, kwargs)
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
        return super().closeEvent(event)

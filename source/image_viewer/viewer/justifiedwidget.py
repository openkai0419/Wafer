import os
from PySide6 import QtWidgets, QtGui, QtCore
from .loader import ImageLoaderRunnable
from ..viewer_settings import main_setting
from ..thread import main_thread
from .layout import JustifiedLayoutCalculator
from .scroll_manager import ScrollManager, SizeMismatchChecker
from ..mouseeventmanager import (
    MouseEventManager,
    MouseEventDispatcher,
    MouseActionKey,
    MouseButton,
    ClickType
)
from .cachemanager import MemoryLimitedPixmapCache, QLabelPool
from ...profiling import init_env
from ...common import get_main_based_directory
logger, profiler = init_env()
QWIDGETSIZE_MAX = 16777215

class JustifiedVirtualScrollWidget(QtWidgets.QWidget):
    layout_ready = QtCore.Signal()

    def __init__(self, scroll, parent=None):
        super().__init__(parent)
        self.parent_scroll = scroll

        self.mouse_event_manager = MouseEventManager()
        self.setup_mouse_bindings()
        self._mouse_dispatcher = MouseEventDispatcher(self, self.mouse_event_manager)
    
        self.image_paths = []
        self.aspect_ratios = []
        self.rects = []

        self._restore_scroll_index = None
        self._restore_scroll_requested = False

        self.screen_width = QtGui.QGuiApplication.primaryScreen().availableGeometry().width()
        self.base_height = main_setting.get("viewer/zoom", int(self.screen_width / 10))
        self.min_height = int(self.screen_width / 30)
        self.max_height = int(self.screen_width)
        self.setMinimumWidth(self.min_height)
        self.spacing = 4

        self.calculator = None

        self.pixmap_cache = MemoryLimitedPixmapCache(500 * 1024 * 1024)
        self.active_threads = {}

        self.error_placeholder = self._generate_error_pixmap()

        self.label_pool = QLabelPool(self)
        self.widgets = {}
        self.visible_indices = set()
        
        self.scroll_manager = ScrollManager(self)

        self._zoom_timer = QtCore.QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(50)
        self._zoom_timer.timeout.connect(self._recalc_layout)

        self._resize_timer = QtCore.QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(200)
        self._resize_timer.timeout.connect(self._on_resize_event)

        self.size_checker = SizeMismatchChecker(self)
        self.size_checker.start()

    def setup_mouse_bindings(self):
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()),
            lambda: print("左クリック：次の画像")
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.X1, ClickType.DOUBLE, (MouseButton.RIGHT,)),
            lambda: print("右ボタンを押しながらX1ダブルクリック")
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, (MouseButton.MIDDLE,)),
            lambda: print("中押し＋ホイールアップでズームイン")
        )

    def _generate_error_pixmap(self):
        try:
            import sys
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))  # main.py 実行位置

            imgpath = get_main_based_directory() / "resources/fail_fetch_02.png"
            pixmap = QtGui.QPixmap(imgpath)
            if not pixmap.isNull():
                return pixmap
        except Exception as e:
            logger.warning(f"Failed to load error image: {e}")

        # フォールバック描画
        size = QtCore.QSize(64, 64)
        pixmap = QtGui.QPixmap(size)
        pixmap.fill(QtGui.QColor("#ccc"))
        painter = QtGui.QPainter(pixmap)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        pen = QtGui.QPen(QtCore.Qt.red, 4)
        painter.setPen(pen)
        painter.drawLine(10, 10, 54, 54)
        painter.drawLine(10, 54, 54, 10)
        painter.end()
        return pixmap


    @profiler.profile
    def wheelEvent(self, event):
        if QtWidgets.QApplication.keyboardModifiers() == QtCore.Qt.ControlModifier:
            self._restore_scroll_index = self.get_center_image_index()
            delta = event.angleDelta().y()
            zoom_step = 50
            new_height = self.base_height + (zoom_step if delta > 0 else -zoom_step)
            new_height = min(self.max_height, new_height)
            old_height = self.base_height
            self.base_height = max(self.min_height, min(new_height, self.screen_width ))
            if self.base_height != old_height:
                self._restore_scroll_requested = True
                self._zoom_timer.start()
                main_setting.set("viewer/zoom", self.base_height)
        else:
            super().wheelEvent(event)


    @profiler.profile
    def set_precalculated_meta(self, path_list, aspect_ratios):
        if not path_list:
            self._clear_all_widgets()
        self.image_paths = path_list
        self.aspect_ratios = aspect_ratios
        self._recalc_layout()

    @profiler.profile
    def _clear_all_widgets(self):
        for i in list(self.widgets.keys()):
            self._recycle_widget(i)
        self.widgets.clear()
        self.visible_indices.clear()
        self.rects = []
        self.setMinimumHeight(0)

    @profiler.profile
    def reload_visible_images(self):
        for i in list(self.visible_indices):
            if i >= len(self.image_paths) or i >= len(self.rects):
                continue
            if i in self.active_threads:
                runnable = self.active_threads.pop(i)
                if hasattr(runnable, "cancel"):
                    runnable.cancel()
            if i in self.widgets and i < len(self.rects):
                rect = self.rects[i]
                runnable = ImageLoaderRunnable(i, self.image_paths[i], rect.size(), self)
                self.active_threads[i] = runnable
                main_thread.start(runnable, 5)
        logger.debug("reload_visible_images")


    @profiler.profile
    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._resize_timer.start()

    @profiler.profile
    def _on_resize_event(self):
        self._restore_scroll_index = self.get_center_image_index()
        self._restore_scroll_requested = True
        self._recalc_layout()

    @profiler.profile
    def _recalc_layout(self):
        if self.calculator:
            self.calculator.cancel()

        self.calculator = JustifiedLayoutCalculator(
            self.aspect_ratios, self.base_height, self.spacing, self.width()
        )
        self.calculator.signals.layout_ready.connect(self._on_layout_ready)
        main_thread.start(self.calculator, 7)
        self.size_checker.trigger()
        logger.debug("_recalc_layout")

    @profiler.profile
    def get_center_image_index(self):
        scroll_area = self.parent_scroll
        if isinstance(scroll_area, QtWidgets.QAbstractScrollArea):
            center_y = scroll_area.verticalScrollBar().value() + scroll_area.viewport().height() // 2
            center_x = scroll_area.horizontalScrollBar().value() + scroll_area.viewport().width() // 2
            center_point = QtCore.QPoint(center_x, center_y)
            for i, r in enumerate(self.rects):
                if r.contains(center_point):
                    return i
        return None

    def reinstall_scroll_index(self, ind):
        scroll_area = self.parent_scroll
        target_rect = self.rects[ind]
        if isinstance(scroll_area, QtWidgets.QAbstractScrollArea):
            bar = scroll_area.verticalScrollBar()
            new_value = target_rect.center().y() - scroll_area.viewport().height() // 2
            bar.setValue(new_value)

    @profiler.profile
    def _on_layout_ready(self, rects):
        self.rects = rects
        self._update_visible_items()

        if self._restore_scroll_requested and self._restore_scroll_index is not None:
            if main_setting.is_first_time("viewer/scroll"):
                self._restore_scroll_index = main_setting.get("viewer/scroll", 30)
            if self._restore_scroll_index < len(self.rects):
                self.reinstall_scroll_index(self._restore_scroll_index)
                self._restore_scroll_requested = False
        self.layout_ready.emit()

        # 高速化：画面内またはプリフェッチ対象のみジオメトリを更新
        for i in self.visible_indices:
            if i < len(self.rects):
                self._ensure_widget_visible(i, self.rects[i])

    @profiler.profile
    def _update_visible_items(self):
        if not self.rects:
            return

        scroll_area = self.parent_scroll
        viewport = scroll_area.viewport()
        scroll_y = scroll_area.verticalScrollBar().value()
        view_rect = viewport.rect().translated(0, scroll_y)

        visible_range = ScrollManager.calculate_visible_indices(self.rects, view_rect)
        expanded_range = ScrollManager.expand_prefetch_range(self.rects, visible_range)

        new_visible = set(expanded_range)
        newly_added = new_visible - self.visible_indices
        no_longer_visible = self.visible_indices - new_visible

        # 中央優先読み込み用の順序付け
        if newly_added:
            center = (visible_range.start + visible_range.stop) // 2
            sorted_added = sorted(newly_added, key=lambda i: abs(i - center))
            for i in sorted_added:
                if i < len(self.rects):
                    self._ensure_widget_visible(i, self.rects[i])

        for i in no_longer_visible:
            self._recycle_widget(i)

        self.visible_indices = new_visible

        if self.rects:
            total_height = self.rects[-1].bottom() + self.spacing
            self.setMinimumHeight(total_height)

        if i not in self.widgets:
            label = self.label_pool.acquire()
            label.setGeometry(rect)
            self.widgets[i] = label
            if i in self.pixmap_cache:
                label.set_pixmap(self.pixmap_cache[i], self.image_paths[i])
            elif i not in self.active_threads:
                runnable = ImageLoaderRunnable(i, self.image_paths[i], rect.size(), self)
                self.active_threads[i] = runnable
                main_thread.start(runnable, 5)
        else:
            if self.widgets[i].geometry() != rect:
                self.widgets[i].setGeometry(rect)

    @profiler.profile
    def _recycle_widget(self, i):
        if i in self.widgets:
            label = self.widgets.pop(i)
            self.label_pool.release(label)
        if i in self.pixmap_cache:
            del self.pixmap_cache[i]
        if i in self.active_threads:
            runnable = self.active_threads.pop(i)
            if hasattr(runnable, "cancel"):
                runnable.cancel()

    @profiler.profile
    @QtCore.Slot(int, QtGui.QPixmap)
    def _on_pixmap_ready(self, index: int, pixmap: QtGui.QPixmap):
        if index >= len(self.image_paths):
            logger.warning(f"_on_pixmap_ready: index {index} out of range (len={len(self.image_paths)})")
            return
        if index in self.widgets:
            label = self.widgets[index]
            self.pixmap_cache[index] = pixmap
            label.set_pixmap(pixmap, self.image_paths[index])
        if index in self.active_threads:
            del self.active_threads[index]

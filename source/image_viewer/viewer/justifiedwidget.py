import os
import psutil
import cv2
import numpy as np
import multiprocessing
from collections import OrderedDict
from PySide6 import QtWidgets, QtGui, QtCore

from .loader import ImageLoaderRunnable
from ..viewer_settings import main_setting
from ..thread import main_thread
from ..mouseeventmanager import (
    MouseEventManager,
    MouseEventDispatcher,
    MouseActionKey,
    MouseButton,
    ClickType
)
from .cachemanager import MemoryLimitedPixmapCache, QLabelPool
from ...profiling import init_env
logger, profiler = init_env()

QWIDGETSIZE_MAX = 16777215

def _size_mismatch(a: QtCore.QSize, b: QtCore.QSize, tolerance: int = 1):
    return abs(a.width() - b.width()) > tolerance or abs(a.height() - b.height()) > tolerance

class CalculatorSignals(QtCore.QObject):
    layout_ready = QtCore.Signal(list)

class JustifiedLayoutCalculator(QtCore.QRunnable):
    def __init__(self, aspect_ratios, base_height, spacing, container_width):
        super().__init__()
        self.signals = CalculatorSignals()
        self.aspect_ratios = aspect_ratios
        self.base_height = base_height
        self.spacing = spacing
        self.container_width = container_width
        self._cancelled = False

    def cancel(self):
        self._cancelled = True

    @profiler.profile
    def run(self):
        rects = []
        x, y = 0, 0
        line = []
        line_width = 0
        spacing = self.spacing
        base_height = self.base_height
        container_width = self.container_width

        append_rects = rects.append
        aspect_ratios = self.aspect_ratios

        i = 0
        while i < len(aspect_ratios):
            if self._cancelled:
                return
            aspect = aspect_ratios[i]
            w = aspect * base_height

            if line and (line_width + w + spacing * len(line)) > container_width:
                total_spacing = spacing * (len(line) - 1)
                scale = (container_width - total_spacing) / line_width
                cur_x = 0
                for a in line:
                    if self._cancelled:
                        return
                    iw = int(a * base_height * scale)
                    ih = int(base_height * scale)
                    append_rects(QtCore.QRect(cur_x, y, iw, ih))
                    cur_x += iw + spacing
                y += ih + spacing
                line.clear()
                line_width = 0
            else:
                line.append(aspect)
                line_width += w
                i += 1

        if line and not self._cancelled:
            total_spacing = spacing * (len(line) - 1)
            scale = (container_width - total_spacing) / line_width
            cur_x = 0
            for a in line:
                iw = int(a * base_height * scale)
                ih = int(base_height * scale)
                append_rects(QtCore.QRect(cur_x, y, iw, ih))
                cur_x += iw + spacing

        if not self._cancelled:
            self.signals.layout_ready.emit(rects)

class SizeMismatchChecker(QtCore.QTimer):
    def __init__(self, target_widget, debug=False):
        super().__init__()
        self.target_widget = target_widget
        self.debug = debug
        self.setInterval(400)
        self.timeout.connect(self.check)

        self._active = False
        self._idle_timer = QtCore.QTimer()
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(1600)
        self._idle_timer.timeout.connect(self._on_idle)

    def trigger(self):
        self._active = True
        self._idle_timer.start()
        if not self.isActive():
            self.start()

    def _on_idle(self):
        self._active = False

    @profiler.profile
    def check(self):
        if not self._active:
            return

        max_index = len(self.target_widget.image_paths)
        for i, label in self.target_widget.widgets.items():
            if i >= max_index:
                continue 
            pixmap = label.pixmap()
            if pixmap is None:
                continue
            if _size_mismatch(pixmap.size(), label.size()):
                if i not in self.target_widget.active_threads:
                    runnable = ImageLoaderRunnable(i, self.target_widget.image_paths[i], label.size(), self.target_widget)
                    self.target_widget.active_threads[i] = runnable
                    main_thread.start(runnable, 5)

        logger.debug("SizeMismatchChecker: check")
        

class JustifiedVirtualScrollWidget(QtWidgets.QWidget):

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
        
        self._scroll_last_time = 0
        self._scroll_throttle_ms = 100

        self.parent_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

        self.scroll_timer = QtCore.QTimer(self)
        self.scroll_timer.setInterval(100)
        self.scroll_timer.timeout.connect(self._on_scroll_timer)
        self.scroll_timer.start()

        self._scrolling = False
        self._scroll_idle_timer = QtCore.QTimer(self)
        self._scroll_idle_timer.setSingleShot(True)
        self._scroll_idle_timer.setInterval(100)
        self._scroll_idle_timer.timeout.connect(self._on_scroll_idle)

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

            imgpath = os.path.join(base_dir, "fail_fetch_01.png")
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

    def _on_scroll_bar_changed(self):
        self._scrolling = True
        self._scroll_idle_timer.start()

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
    def _on_scroll_idle(self):
        self._scrolling = False
        self._update_visible_items()

    @profiler.profile
    def _on_scroll_timer(self):
        if self._scrolling:
            self._throttled_update_visible_items()

    @profiler.profile
    def _throttled_update_visible_items(self):
        now = QtCore.QTime.currentTime().msecsSinceStartOfDay()
        if now - self._scroll_last_time >= self._scroll_throttle_ms:
            self._scroll_last_time = now
            self._update_visible_items()

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

        visible_range = self._calculate_visible_indices(view_rect)
        expanded_range = self._expand_prefetch_range(visible_range)

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

    @profiler.profile
    def _calculate_visible_indices(self, view_rect):
        def find_start():
            low, high = 0, len(self.rects) - 1
            while low <= high:
                mid = (low + high) // 2
                if self.rects[mid].bottom() < view_rect.top():
                    low = mid + 1
                else:
                    high = mid - 1
            return low

        def find_end():
            low, high = 0, len(self.rects) - 1
            while low <= high:
                mid = (low + high) // 2
                if self.rects[mid].top() > view_rect.bottom():
                    high = mid - 1
                else:
                    low = mid + 1
            return high

        start = find_start()
        end = find_end()
        return range(start, end + 1)

    @profiler.profile
    def _expand_prefetch_range(self, visible_range):
        if not visible_range:
            return range(0, 0)

        prefetch = len(visible_range) + 3
        start = max(0, visible_range.start - prefetch)
        end = min(len(self.rects), visible_range.stop + prefetch)
        return range(start, end)


    @profiler.profile
    def _ensure_widget_visible(self, i, rect):
        if i >= len(self.image_paths):
            logger.warning(f"Index {i} out of range for image_paths (len={len(self.image_paths)})")
            return
        if i not in self.widgets:
            label = self.label_pool.acquire()
            label.setGeometry(rect)
            label.setToolTip(self.image_paths[i])
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

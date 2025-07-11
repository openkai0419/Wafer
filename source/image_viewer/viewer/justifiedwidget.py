import copy
import bisect
import math
from PySide6 import QtWidgets, QtGui, QtCore

from .loader import ImageLoaderRunnable
from ...common import uipx, is_dark_theme
from .calc_layout import JustifiedLayoutCalculator
from ..viewer_settings import main_setting
from ..thread import main_thread
from .mouseeventmanager import (
    MouseEventManager,
    MouseEventDispatcher,
    MouseActionKey,
    MouseButton,
    ClickType
)
from .cachemanager import MemoryLimitedPixmapCache, QLabelPool
from .sizechecker import SizeMismatchChecker
from .selectionmanager import SelectionManager
from ...profiling import logger, profiler
from ...common import get_resource_path
from ...debounce import qt_debounce


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
        self.spacing = uipx(4)
        self.calculator = None

        self.pixmap_cache = MemoryLimitedPixmapCache(500 * 1024 * 1024)
        self.active_threads = {}

        self.error_placeholder = self._generate_error_pixmap()

        self.selection_manager = SelectionManager()
        self.selection_manager.selectionChanged.connect(self._on_selection_changed)

        self.label_pool = QLabelPool(self)
        self.widgets = {}
        self.visible_indices = set()
        
        self._scroll_last_time = 0
        self._scroll_throttle_ms = 100

        self.parent_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)
        self.parent_scroll.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

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

    def _on_selection_changed(self, _):
        self.update()

    @profiler.profile
    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QtGui.QPainter(self)

        scroll_y = self.parent_scroll.verticalScrollBar().value()
        scroll_x = self.parent_scroll.horizontalScrollBar().value()
        viewport_rect = self.parent_scroll.viewport().rect().translated(scroll_x, scroll_y)
        space = self.spacing / 4

        if is_dark_theme():
            pen = QtGui.QPen(QtGui.QColor("#FFFFFF"), max(1, self.spacing / 2))
        else:
            pen = QtGui.QPen(QtGui.QColor("#000000"), max(1, self.spacing / 2))
        painter.setPen(pen)

        for index in (set(self.selection_manager.selected_indices()) & self.visible_indices):
            if index >= len(self.rects):
                continue
            rect = self.rects[index]
            if rect.intersects(viewport_rect):
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(rect.adjusted(-space, -space, space, space))

        painter.end()

    @profiler.profile
    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder
    
    @profiler.profile
    def get_selected_paths(self):
        return [self.image_paths[i] for i in self.selection_manager.selected_indices()]

    @profiler.profile
    def _on_left_click(self, event):
        index = self.index_at_pos(event.pos())
        if index is not None:
            modifiers = event.modifiers()
            last = self.selection_manager.last_added()
            if modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
                self.selection_manager.toggle(index)
            elif event.modifiers() & QtCore.Qt.ShiftModifier and last is not None:
                if last < index:
                    adding  =list(range(last, index + 1))
                    self.selection_manager.add_selection(adding, -1)
                else:
                    adding  =list(range(index, last + 1))
                    self.selection_manager.add_selection(adding, 0)
            else: 
                if not self.selection_manager.is_selected(index):
                    self.selection_manager.set_selected([index], 0) 
                else:
                    if len(self.selection_manager.selected_indices()) > 1:
                        self.selection_manager.set_selected([index], 0)
                    else:
                        self.selection_manager.deselect(index)
        else:
            pass

    @profiler.profile
    def _on_right_click(self, event):
        index = self.index_at_pos(event.pos())
        if index is not None:
            path = self.image_paths[index]
            logger.info(path)
            logger.info(event.globalPos())
            if self.context_menu_builder:
                menu = self.context_menu_builder.build_menu(path)
                menu.popup(event.globalPos())
            if not self.selection_manager.is_selected(index):
                self._on_left_click(event) 
        else:
            pass

    @profiler.profile    
    def _on_double_click(self, event):
        index = self.index_at_pos(event.pos())
        if index is not None:
            if not self.selection_manager.is_selected(index):
                self._on_left_click(event)
                pass

    @profiler.profile
    def index_at_pos(self, pos: QtCore.QPoint) -> int | None:
        for i, rect in enumerate(self.rects):
            if rect.contains(pos):
                return i
        return None

    @profiler.profile
    def setup_mouse_bindings(self):
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()),
            self._on_left_click
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, ()),
            self._on_double_click
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()),
            self._on_right_click
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.X1, ClickType.DOUBLE, (MouseButton.RIGHT,)),
            lambda x: print("Double click X1 while holding right button")
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, (MouseButton.MIDDLE,)),
            lambda x: print("Middle press + wheel up to zoom in")
        )

    def _generate_error_pixmap(self):
        try:
            imgpath = get_resource_path() / "fail_fetch_02.png"
            pixmap = QtGui.QPixmap(imgpath)
            if not pixmap.isNull():
                return pixmap
        except Exception as e:
            logger.warning(f"Failed to load error image: {e}")

        # Fallback drawing
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
            self.aspect_ratios, self.base_height, self.spacing, self.width(), self.height(), 1
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
        self.rects_tops = [r.top() for r in rects]
        self.rects_bottoms = [r.bottom() for r in rects]
        self._update_visible_items()

        if self._restore_scroll_requested and self._restore_scroll_index is not None:
            index = self._restore_scroll_index
            if main_setting.is_first_time("viewer/scroll"):
                index = main_setting.get("viewer/scroll", 0)
            elif self.selection_manager.last_added():
                index = self.selection_manager.last_added()
            if index < len(self.rects):
                self.reinstall_scroll_index(index)
                self._restore_scroll_requested = False
        self.layout_ready.emit()

        # Speed up: update geometry only for visible or prefetched items
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
        scroll_x = scroll_area.horizontalScrollBar().value()

        view_rect = viewport.rect().translated(scroll_x, scroll_y)

        visible_range = self._calculate_visible_indices(view_rect)
        expanded_range = self._expand_prefetch_range(visible_range)

        new_visible = set(expanded_range)
        newly_added = new_visible - self.visible_indices
        no_longer_visible = self.visible_indices - new_visible

        # Order for center-priority loading
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
        self.update()

    @profiler.profile
    def _calculate_visible_indices(self, view_rect):
        if not self.rects:
            return range(0, 0)

        # 範囲のY座標
        top = view_rect.top()
        bottom = view_rect.bottom()

        # 開始インデックス: bottom < view_rect.top() の最後の次
        start = bisect.bisect_left(self.rects_bottoms, top)

        # 終了インデックス: top > view_rect.bottom() の最初の手前
        end = bisect.bisect_right(self.rects_tops, bottom) - 1

        # 範囲外チェック
        start = max(0, min(start, len(self.rects)-1))
        end = max(start, min(end, len(self.rects)-1))

        return range(start, end+1)

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

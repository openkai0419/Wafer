import copy
import bisect
import math
import os
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


def draw_centered_text_with_background(
    pixmap: QtGui.QPixmap,
    text: str,
    font: QtGui.QFont = None,
    padding: int = 4,
    text_color: QtGui.QColor = QtGui.QColor("#FFFFFF"),
    bg_color: QtGui.QColor = QtGui.QColor("#3B80FF")
    ) -> QtGui.QPixmap:
    pixmap_copy = QtGui.QPixmap(pixmap)
    painter = QtGui.QPainter(pixmap_copy)

    if font is None:
        font = painter.font()
        font.setBold(True)
        font.setPointSize(uipx(12))
    painter.setFont(font)

    # テキストのサイズを計算
    metrics = QtGui.QFontMetrics(font)
    text_rect = metrics.boundingRect(text)

    # 背景矩形のサイズ
    bg_width = text_rect.width() + padding * 2
    bg_height = text_rect.height() + padding * 2

    # pixmap の中央座標
    center_x = pixmap.width() // 2
    center_y = pixmap.height() // 2

    # 背景矩形の左上座標
    bg_x = center_x - bg_width // 2
    bg_y = center_y - bg_height // 2

    bg_rect = QtCore.QRect(bg_x, bg_y, bg_width, bg_height)

    # 背景描画
    painter.setBrush(bg_color)
    painter.setPen(QtCore.Qt.NoPen)
    painter.drawRect(bg_rect)

    # テキスト描画
    text_x = bg_x + padding
    text_y = bg_y + padding + metrics.ascent()
    painter.setPen(text_color)
    painter.drawText(text_x, text_y, text)

    painter.end()
    return pixmap_copy


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

        self.last_selections = []
        self._restore_scroll_index = None

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

        self._drag_rect_start = None
        self._drag_rect_current = None
        self._is_shift_dragging = False
        self._drag_state = False
        self._disable_next_click = False

        self.size_checker = SizeMismatchChecker(self)
        self.size_checker.start()

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

        self.installEventFilter(self)

    def _on_selection_changed(self, _):
        self.last_selections = self.get_selected_paths()
        self.update()

    @profiler.profile
    def paintEvent(self, event):
        super().paintEvent(event)

        painter = QtGui.QPainter(self)

        scroll_y = self.parent_scroll.verticalScrollBar().value()
        scroll_x = self.parent_scroll.horizontalScrollBar().value()
        viewport_rect = self.parent_scroll.viewport().rect().translated(scroll_x, scroll_y)
        space = self.spacing / 4

        if not hasattr(self, '_selection_pen'):
            self._selection_pen = QtGui.QPen(QtGui.QColor("#3B80FF"), max(1, self.spacing / 2))
        painter.setPen(self._selection_pen)

        for index in (self.selection_manager.selected_indices() & self.visible_indices):
            if index >= len(self.rects):
                continue
            rect = self.rects[index]
            if rect.intersects(viewport_rect):
                painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(rect.adjusted(-space, -space, space, space))

        if self._is_shift_dragging and self._drag_rect_start and self._drag_rect_current:
            selection_rect = QtCore.QRect(self._drag_rect_start, self._drag_rect_current).normalized()
            color = QtGui.QColor(59, 128, 255, 50)  # 半透明の青
            border_color = QtGui.QColor(59, 128, 255)
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(border_color, 1, QtCore.Qt.DashLine))
            painter.drawRect(selection_rect)
        painter.end()

    @profiler.profile
    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder
    
    @profiler.profile
    def get_selected_paths(self):
        return [self.image_paths[i] for i in self.selection_manager.selected_indices() if i < len(self.image_paths)]

    @profiler.profile
    def index_at_pos(self, pos: QtCore.QPoint) -> int | None:
        y = pos.y()
        start = bisect.bisect_left(self.rects_bottoms, y)
        end = bisect.bisect_right(self.rects_tops, y)
        for i in range(start, end):
            if self.rects[i].contains(pos):
                return i
        return None

    def _on_left_ctrl_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        index = self.index_at_pos(event.pos())
        if index is not None:
            self.selection_manager.toggle(index)

    def _on_left_shift_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        index = self.index_at_pos(event.pos())
        if index is not None:
            last = self.selection_manager.last_added()
            if last is not None:
                if last < index:
                    adding  =list(range(last, index + 1))
                    self.selection_manager.add_selection(adding, -1)
                else:
                    adding  =list(range(index, last + 1))
                    self.selection_manager.add_selection(adding, 0)
            else:
                self.selection_manager.add_selection([index], 0)

    def _on_left_single_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        index = self.index_at_pos(event.pos())
        if index is not None:    
            if not self.selection_manager.is_selected(index):
                self.selection_manager.set_selected([index], 0) 
            else:
                if len(self.selection_manager.selected_indices()) > 1:
                    self.selection_manager.set_selected([index], 0)
                else:
                    self.selection_manager.deselect(index)

    @profiler.profile
    def _on_left_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        modifiers = event.modifiers()
        if modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self._on_left_ctrl_click(event)
        elif modifiers & QtCore.Qt.ShiftModifier:
            self._on_left_shift_click(event)
        else: 
            self._on_left_single_click(event)


    @profiler.profile
    def _on_right_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        index = self.index_at_pos(event.pos())
        if index is not None:
            path = self.image_paths[index]
            if self.context_menu_builder:
                menu = self.context_menu_builder.build_menu(path)
                menu.popup(event.globalPos())
            if not self.selection_manager.is_selected(index):
                self._on_left_click(event) 
        else:
            pass

    @profiler.profile    
    def _on_double_click(self, event):
        if self._disable_next_click:
            self._disable_next_click = False
            return
        index = self.index_at_pos(event.pos())
        if index is not None:
            if not self.selection_manager.is_selected(index):
                self._on_left_click(event)
                pass

    def _on_drag(self, event):
        modifiers = event.modifiers()
        if modifiers & QtCore.Qt.ShiftModifier and modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self._on_shift_ctrl_drag(event)
        elif modifiers & QtCore.Qt.ShiftModifier:
            self._on_shift_drag(event)
        else: 
            self._on_drag_start(event)

    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseMove and self._is_shift_dragging:
            self._drag_rect_current = event.pos()
            self.update()
        elif event.type() == QtCore.QEvent.MouseButtonRelease and self._is_shift_dragging:
            self._drag_rect_current = event.pos()
            self._is_shift_dragging = False
            if self._drag_state == True:
                self._finalize_rectangle_selection(add=True)
            else:
                self._finalize_rectangle_selection()
            self._drag_rect_start = None
            self._drag_rect_current = None
            self.update()
        return super().eventFilter(watched, event)

    def _on_shift_ctrl_drag(self, event):
        self._drag_state = True
        self._start_shift_drag(event)

    def _on_shift_drag(self, event):
        self._drag_state = False
        self._start_shift_drag(event)

    def _start_shift_drag(self, event):
        if not self._is_shift_dragging:
            self._is_shift_dragging = True
            self._drag_rect_start = event.pos()
            self._drag_rect_current = event.pos()
            self._disable_next_click = True
            self.update()

    def _finalize_rectangle_selection(self, add=False):
        if not self._drag_rect_start or not self._drag_rect_current:
            return
        rect = QtCore.QRect(self._drag_rect_start, self._drag_rect_current).normalized()
        selected_indices = []
        for i, r in enumerate(self.rects):
            if rect.intersects(r):
                selected_indices.append(i)

        if selected_indices:
            if add:
                self.selection_manager.add_selection(selected_indices, last=-1)
            else:
                self.selection_manager.set_selected(selected_indices, last=-1)
        else:
            logger.info("No items in selection rectangle.")

    @profiler.profile
    def _on_drag_start(self, event):
        index = self.index_at_pos(event.pos())
        if index is not None:
            if not self.selection_manager.is_selected(index):
                self._on_left_click(event)

        selected = self.get_selected_paths()
        urls = [QtCore.QUrl.fromLocalFile(path) for path in selected]
        if not urls:
            return

        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setUrls(urls)
        drag.setMimeData(mime)

        widget = QtWidgets.QApplication.widgetAt(event.globalPos())
        logger.info(widget)
        if widget:
            pixmap = QtGui.QPixmap(widget.grab())
            pixmap = pixmap.scaled(QtCore.QSize(uipx(150), uipx(150)),
                                    QtCore.Qt.KeepAspectRatio,
                                    QtCore.Qt.FastTransformation)
            
            transparent_pixmap = QtGui.QPixmap(pixmap.size())
            transparent_pixmap.fill(QtCore.Qt.transparent)

            painter = QtGui.QPainter(transparent_pixmap)
            painter.setOpacity(0.5)  # 0.0〜1.0 で半透明度を指定
            painter.drawPixmap(0, 0, pixmap)
            painter.end()

            pixmap = transparent_pixmap

            if len(urls) > 1:
                pixmap = draw_centered_text_with_background(pixmap, f" {len(urls)}  ")

            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().topLeft())
        drag.exec(QtCore.Qt.CopyAction | QtCore.Qt.MoveAction)


    @profiler.profile
    def _on_drop(self, event):
        if not event.mimeData().hasUrls():
            return
        urls = event.mimeData().urls()
        files = []
        for url in urls:
            f = url.toLocalFile()
            if os.path.exists(f):
                files.append(f)
        logger.info(files)
        

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
            MouseActionKey(MouseButton.NONE, ClickType.DRAG_START, (MouseButton.LEFT,)),
            self._on_drag
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.DROP, ()),
            self._on_drop
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, ()),
            self._on_wheel
        )
        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_DOWN, ()),
            self._on_wheel
        )

        self.mouse_event_manager.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, (MouseButton.LEFT,)),
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

    def wheelEvent(self, event):
        return

    def _on_wheel(self, event):
        if QtWidgets.QApplication.keyboardModifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self._on_zoom_wheel(event)
        else:
            super().wheelEvent(event)

    def _on_zoom_wheel(self, event):
        self._restore_scroll_index = self.get_center_image_index()
        delta = event.angleDelta().y()
        zoom_step = 50
        new_height = self.base_height + (zoom_step if delta > 0 else -zoom_step)
        new_height = min(self.max_height, new_height)
        old_height = self.base_height
        self.base_height = max(self.min_height, min(new_height, self.screen_width ))
        if self.base_height != old_height:
            self._debounce_recalc_layout()
            main_setting.set("viewer/zoom", self.base_height)

    def _on_scroll_bar_changed(self):
        self._scrolling = True
        self._scroll_idle_timer.start()

    @profiler.profile
    def set_paths(self, path_list, aspect_ratios):
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
    @qt_debounce(100)
    def on_resize_event(self):
        self._restore_scroll_index = self.get_center_image_index()
        logger.info("on_resize_event")
        self._recalc_layout()

    @qt_debounce(100)
    def _debounce_recalc_layout(self):
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

    @profiler.profile
    def reinstall_scroll_index(self, ind):
        scroll_area = self.parent_scroll
        target_rect = self.rects[ind]
        if isinstance(scroll_area, QtWidgets.QAbstractScrollArea):
            bar = scroll_area.verticalScrollBar()
            new_value = target_rect.center().y() - scroll_area.viewport().height() // 2
            bar.setValue(new_value)

    @profiler.profile
    def _on_layout_ready(self, rects):
        if self.rects == rects:
            self.layout_ready.emit()
            return

        self.rects = rects
        self.rects_tops = [r.top() for r in rects]
        self.rects_bottoms = [r.bottom() for r in rects]
        self._update_visible_items()
        
        logger.info("_on_layout_ready")
        self.size_checker.trigger()
        self.layout_ready.emit()

        if self.last_selections:
            indexes = [self.image_paths.index(p) for p in self.last_selections if p in self.image_paths]
            if indexes:
                with self.selection_manager.noemit():
                    self.selection_manager.set_selected(indexes, last=-1)
                logger.info(f"set: {indexes}")
                logger.info(self.selection_manager.last_added())
            else:
                with self.selection_manager.noemit():
                    self.selection_manager.clear()

        index = self.get_last_index()
        logger.info(f"loead: {index}")
        if index is not None:
            if index < len(self.rects):
                self.reinstall_scroll_index(index)

        for i in self.visible_indices:
            if i < len(self.rects):
                self._ensure_widget_visible(i, self.rects[i])

    @profiler.profile
    def get_last_index(self):
        index = None
        if main_setting.is_first_time("viewer/scroll"):
            return main_setting.get("viewer/scroll", 0)
        if self.selection_manager.last_added():
            return self.selection_manager.last_added()
        if self._restore_scroll_index is not None:
            index = self._restore_scroll_index
            self._restore_scroll_index = None
            return index
        return index

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

import bisect
import math
import os
from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import uipx
from ...common.profiling import logger, profiler
from .loader import ImageLoaderRunnable
from ...qt.debounce import qt_debounce, qt_throttle
from ...qt.pixmap import PixmapFactory
from ...qt.thread import main_thread
from ..viewer_settings import main_setting
from .cachemanager import MemoryLimitedImageCache, QLabelPool
from .calc_layout import JustifiedLayoutCalculator
from .items import ViewerItems
from .sizechecker import SizeMismatchChecker
from ...actions.bridge import Kit

class OverLayPainter(QtWidgets.QWidget):

    def __init__(self, parent, spacing, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)
        self.setFocusPolicy(QtCore.Qt.NoFocus)
        self.color = (59, 128, 255)
        self.half_pos = spacing / 2
        self._qcolor_main = QtGui.QColor(*self.color)
        self._qcolor_fill_sel = QtGui.QColor(*self.color, 25)
        self._qcolor_fill_drag = QtGui.QColor(*self.color, 50)
        self._selection_pen = QtGui.QPen(self._qcolor_main, max(1, spacing * 0.5))
        self._selection_pen.setCosmetic(True)
        self._parent = parent
        parent.installEventFilter(self)
        self.resize(self._parent.size())
        self.show()
        logger.info(f'STACK UNDER : {self.stackUnder(self._parent)}')
        self._last_state = None
        self.viewport_rect = QtCore.QRect()
        self.selection_indices = set()
        self.visible_indices = set()
        self.rects = []
        self.drag_rect_start = None
        self.drag_rect_current = None
        self.is_shift_dragging = False
        self.drop_rect = None
        self.drop_title = None
        self.drop_text = None
        self.raise_()

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if watched == self._parent and event.type() == QtCore.QEvent.Resize:
            self.resize(self._parent.size())
        return super().eventFilter(watched, event)

    def set_paintvalue(self, viewport_rect, selection_indices, visible_indices, rects, drag_rect_start, drag_rect_current, is_shift_dragging, drop_rect, drop_title, drop_text):
        state = (viewport_rect, frozenset(selection_indices), frozenset(visible_indices), drag_rect_start, drag_rect_current, is_shift_dragging, drop_rect, drop_title, drop_text)
        if state != self._last_state:
            self._last_state = state
            self.viewport_rect = viewport_rect
            self.selection_indices = selection_indices
            self.visible_indices = visible_indices
            self.rects = rects
            self.drag_rect_start = drag_rect_start
            self.drag_rect_current = drag_rect_current
            self.is_shift_dragging = is_shift_dragging
            self.drop_rect = drop_rect
            self.drop_title = drop_title
            self.drop_text = drop_text
            self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        painter.setClipRegion(event.region())
        if not self.viewport_rect.isNull():
            painter.setClipRect(self.viewport_rect, QtCore.Qt.IntersectClip)
        space = self.half_pos - self._selection_pen.width() / 2
        if self.selection_indices and self.visible_indices and self.rects:
            indices = self.selection_indices & self.visible_indices
            rect_list = []
            for i in indices:
                if 0 <= i < len(self.rects):
                    r = self.rects[i]
                    if r.intersects(self.viewport_rect):
                        rect_list.append(r.adjusted(-space, -space, space, space))
            if rect_list:
                painter.setPen(self._selection_pen)
                painter.setBrush(self._qcolor_fill_sel)
                painter.drawRects(rect_list)
        if self.is_shift_dragging and self.drag_rect_start and self.drag_rect_current:
            selection_rect = QtCore.QRect(self.drag_rect_start, self.drag_rect_current).normalized()
            dash_pen = QtGui.QPen(self._qcolor_main, 1, QtCore.Qt.DashLine)
            dash_pen.setCosmetic(True)
            painter.setPen(dash_pen)
            painter.setBrush(self._qcolor_fill_drag)
            painter.drawRect(selection_rect)
        if self.drop_rect and not self.drop_rect.isNull():
            r = self.drop_rect
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 160))
            painter.drawRect(r)
            if self.drop_title or self.drop_text:
                inner = r.adjusted(2, 2, -2, -2)
                painter.save()
                painter.setPen(QtGui.QColor(255, 255, 255))
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                fm = QtGui.QFontMetrics(font)
                title = fm.elidedText(str(self.drop_title or ""), QtCore.Qt.ElideMiddle, max(1, inner.width() - int(self.half_pos)))
                text = fm.elidedText(str(self.drop_text or ""), QtCore.Qt.ElideMiddle, max(1, inner.width() - int(self.half_pos)))
                painter.drawText(inner, QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, f"{title}\n{text}".strip())
                painter.restore()
        painter.end()

class JustifiedVirtualScrollWidget(QtWidgets.QWidget, Kit.UIMixin):
    layout_ready = QtCore.Signal()
    base_height_changed = QtCore.Signal()

    def __init__(self, scroll, root, items: ViewerItems | None = None, parent=None):
        super().__init__(parent)
        self.root = root
        self.items = items or ViewerItems(self)
        self.parent_scroll = scroll
        self.init_command_binding("JustifiedView", enable_drops=True)
        self.setObjectName('JustifiedVirtualScrollWidget')
        self.rects = []
        self.rects_tops = []
        self.rects_bottoms = []
        self.last_selections = []
        self._restore_scroll_index = None
        self._rect_select_mode = "replace"
        self._rect_select_dragging = False
        self._rect_select_start_pos = None
        self._rect_select_current_pos = None
        self._drop_preview_rect = None
        self._drop_preview_title = None
        self._drop_preview_text = None
        self.screen_width = QtGui.QGuiApplication.primaryScreen().availableGeometry().width()
        self.base_height = main_setting.get('viewer/zoom', int(self.screen_width / 10))
        self._width_ref = self.width()
        self.min_height = int(self.screen_width / 30)
        self.max_height = int(self.screen_width)
        self.setMinimumWidth(self.min_height)
        self.spacing = uipx(4)
        self.calculator = None
        self.image_cache = MemoryLimitedImageCache(main_setting.get('window/chache_size', 500))
        self.label_pool = QLabelPool(self)
        self.active_threads = {}
        self.error_placeholder = PixmapFactory.generate().toImage()
        self.overlay_painter = OverLayPainter(self, self.spacing)
        self.items.selectionChanged.connect(self._on_selection_changed)
        self.widgets = {}
        self.visible_indices = set()
        self.size_checker = SizeMismatchChecker(self)
        self.size_checker.start()
        self.parent_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)
        self.parent_scroll.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        paths = self.items.selected_paths()
        path = self.items.last_selected_path() or self.items.path_at(self.items.current_index())
        return {"path": path, "paths": paths}

    def _on_selection_changed(self, _):
        self.last_selections = self.items.selected_paths()
        logger.info(self.last_selections)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        scroll_y = self.parent_scroll.verticalScrollBar().value()
        scroll_x = self.parent_scroll.horizontalScrollBar().value()
        viewport_rect = self.parent_scroll.viewport().rect().translated(scroll_x, scroll_y)
        self.overlay_painter.set_paintvalue(viewport_rect, self.items.selected_indices(), self.visible_indices, self.rects, self._rect_select_start_pos, self._rect_select_current_pos, self._rect_select_dragging, self._drop_preview_rect, self._drop_preview_title, self._drop_preview_text)

    @profiler.profile
    def get_mouse_pos_path(self):
        i = self.index_at_pos(self.mapFromGlobal(QtCore.QCursor.pos()))
        return self.items.path_at(i)

    def get_mouse_pos_source(self):
        i = self.index_at_pos(self.mapFromGlobal(QtCore.QCursor.pos()))
        return self.items.source_at(i)

    @profiler.profile
    def index_at_pos(self, pos):
        y = pos.y()
        start = bisect.bisect_left(self.rects_bottoms, y)
        end = bisect.bisect_right(self.rects_tops, y)
        for i in range(start, end):
            if self.rects[i].contains(pos):
                return i
        return None

    @qt_throttle(50, 100)
    def _on_scroll_bar_changed(self, *args, **kwargs):
        self._update_visible_items()

    @profiler.profile
    def set_paths(self, path_list, sources, aspect_ratios):
        if not path_list:
            self.items.clear()
            self._clear_all_widgets()
            self.layout_ready.emit()
            return
        if self.items.paths == path_list and self.items.sources == sources and self.items.aspect_ratios == aspect_ratios:
            self.layout_ready.emit()
            return
        self.items.set_items(path_list, sources, aspect_ratios)
        self._recalc_layout()

    @profiler.profile
    def _clear_all_widgets(self):
        for i in list(self.widgets.keys()):
            self._recycle_widget(i)
        for runnable in self.active_threads.values():
            if hasattr(runnable, 'cancel'):
                runnable.cancel()
        self.widgets.clear()
        self.visible_indices.clear()
        self.rects = []
        self.setMinimumHeight(0)

    @profiler.profile
    @qt_debounce(100)
    def on_resize_event(self):
        width = self.width()
        if width != self._width_ref:
            scale = width / self._width_ref
            new_height = int(self.base_height * scale)
            new_height = min(self.max_height, max(self.min_height, new_height))
            if new_height != self.base_height:
                self.base_height = new_height
                self._width_ref = width
                self.base_height_changed.emit()
        self._restore_scroll_index = self.get_center_image_index()
        logger.info('on_resize_event')
        self._recalc_layout()

    @qt_debounce(100)
    def _debounce_recalc_layout(self):
        self._recalc_layout()

    @profiler.profile
    def _recalc_layout(self):
        if self.calculator:
            self.calculator.cancel()
        self.calculator = JustifiedLayoutCalculator(self.items.aspect_ratios, self.base_height, self.spacing, self.width(), self.height(), 1)
        self.calculator.signals.layout_ready.connect(self._on_layout_ready)
        main_thread.start(self.calculator, 7)

    def get_adjusted_scroll_speed(self, base_speed=50):
        reference_height = self.screen_width / 10
        speed_ratio = self.base_height / reference_height
        adjusted_speed = base_speed * max(0.1, min(speed_ratio, 1.0))
        return adjusted_speed

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
    def reinstall_scroll_index(self, ind, animated: bool = False):
        scroll_area = self.parent_scroll
        if not isinstance(scroll_area, QtWidgets.QAbstractScrollArea):
            return
        bar = scroll_area.verticalScrollBar()
        if ind < len(self.rects):
            target = self.rects[ind].center().y() - scroll_area.viewport().height() // 2
        else:
            target = bar.maximum()
        target = max(bar.minimum(), min(target, bar.maximum()))
        distance = abs(bar.value() - target)
        if not animated or distance < 2:
            bar.setValue(target)
            return
        if hasattr(self, '_scroll_anim') and self._scroll_anim is not None:
            self._scroll_anim.stop()
        duration = min(int(40 * math.log2(distance + 1)) + 2, 500)
        anim = QtCore.QPropertyAnimation(bar, b"value", self)
        anim.setDuration(duration)
        anim.setStartValue(bar.value())
        anim.setEndValue(target)
        anim.setEasingCurve(QtCore.QEasingCurve.OutQuad)
        self._scroll_anim = anim
        anim.start()

    @profiler.profile
    def _on_layout_ready(self, rects):
        self.rects = rects
        self.rects_tops = [r.top() for r in rects]
        self.rects_bottoms = [r.bottom() for r in rects]
        self._update_visible_items()
        self.size_checker.trigger()
        self.layout_ready.emit()
        if self.last_selections:
            indexes = [i for i in (self.items.index_of_path(p) for p in self.last_selections) if i is not None]
            if indexes:
                with self.items.selection_noemit():
                    self.items.set_selected(indexes, last=-1)
            else:
                with self.items.selection_noemit():
                    self.items.clear_selection()
        index = self.get_last_index()
        logger.info(index)
        if index is not None:
            if index < len(self.rects):
                self.reinstall_scroll_index(index)
        for i in self.visible_indices:
            if i < len(self.rects):
                self._ensure_widget_visible(i)

    @profiler.profile
    def get_last_index(self):
        index = None
        if main_setting.is_first_time('viewer/scroll'):
            return main_setting.get('viewer/scroll', 0)
        last = self.items.last_selected_index()
        if last is not None:
            return last
        cur = self.items.current_index()
        if cur is not None:
            return cur
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
        if newly_added:
            center = (visible_range.start + visible_range.stop) // 2
            sorted_added = sorted(newly_added, key=lambda i: abs(i - center))
            for i in sorted_added:
                if i < len(self.rects):
                    self._ensure_widget_visible(i)
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
        if not self.rects_bottoms or not self.rects_tops:
            return
        top = view_rect.top()
        bottom = view_rect.bottom()
        start = bisect.bisect_left(self.rects_bottoms, top)
        end = bisect.bisect_right(self.rects_tops, bottom) - 1
        start = max(0, min(start, len(self.rects) - 1))
        end = max(start, min(end, len(self.rects) - 1))
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
    def _ensure_widget_visible(self, i):
        rect = self.rects[i]
        if i >= len(self.items.paths):
            logger.warning(f'Index {i} out of range for paths (len={len(self.items.paths)})')
            return
        if i not in self.widgets:
            label = self.label_pool.acquire()
            label.stackUnder(self.overlay_painter)
            label.setGeometry(rect)
            self.widgets[i] = label
            if i in self.image_cache:
                label.set_image(self.image_cache[i], self.items.paths[i])
            elif i not in self.active_threads:
                runnable = ImageLoaderRunnable(i, self.items.paths[i], rect.size(), self)
                runnable.signal.image_ready.connect(self._on_image_ready)
                runnable.signal.widget_ready.connect(self._on_widget_ready)
                self.active_threads[i] = runnable
                main_thread.start(runnable, 5)
        elif self.widgets[i].geometry() != rect:
            self.widgets[i].setGeometry(rect)

    @profiler.profile
    def _recycle_widget(self, i):
        if i in self.widgets:
            label = self.widgets.pop(i)
            if hasattr(label, "delete"):
                label.delete()
            self.label_pool.release(label)
        if i in self.image_cache:
            del self.image_cache[i]
        if i in self.active_threads:
            runnable = self.active_threads.pop(i)
            if hasattr(runnable, 'cancel'):
                runnable.cancel()

    @profiler.profile
    @QtCore.Slot(int, object)
    def _on_image_ready(self, index, image):
        if index >= len(self.items.paths):
            logger.warning(f'_on_image_ready: index {index} out of range (len={len(self.items.paths)})')
            return
        if index in self.widgets:
            label = self.widgets[index]
            self.image_cache[index] = image
            label.set_image(image, self.items.paths[index])
        if index in self.active_threads:
            del self.active_threads[index]

    @profiler.profile
    @QtCore.Slot(int, object, object)
    def _on_widget_ready(self, index, widget, kwargs):
        if index >= len(self.items.paths):
            logger.warning(f'_on_image_ready: widget {widget} out of range (len={len(self.items.paths)})')
            return

        if issubclass(widget, QtWidgets.QWidget):
            rect = self.rects[index]
            instance = widget(parent=self, **kwargs)
            instance.setGeometry(rect)
            instance.stackUnder(self.overlay_painter)
            self.widgets[index] = instance
        
        if index in self.active_threads:
            del self.active_threads[index]
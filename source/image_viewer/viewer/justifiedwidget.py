import copy
import bisect
import math
import os
from PySide6 import QtWidgets, QtGui, QtCore

from .loader import ImageLoaderRunnable
from ...funcs import uipx, is_dark_theme
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
from ...debounce import qt_debounce, qt_throttle
from ...core.drop import MimeDataParser, FileSaver
from .pixmap import PixmapFactory


class OverLayPainter(QtWidgets.QWidget):
    def __init__(self, parent, spacing, *args, **kwargs):
        super().__init__(parent, *args, **kwargs)
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_NoSystemBackground)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setWindowFlags(QtCore.Qt.FramelessWindowHint)

        self.color = (59, 128, 255)
        self.half_pos = spacing / 2
        self._selection_pen = QtGui.QPen(QtGui.QColor(*self.color), max(1, spacing * 0.5))

        self._parent = parent 
        parent.installEventFilter(self)
        self.resize(self._parent.size())
        self.show()
        logger.info(f"STACK UNDER : {self.stackUnder(self._parent)}")

    def eventFilter(self, watched, event):
        if watched == self._parent and event.type() == QtCore.QEvent.Resize:
            self.resize(self._parent.size())
        return super().eventFilter(watched, event)

    @profiler.profile
    def paint(self, viewport_rect, selection_indices, visible_indices, rects, drag_rect_start, drag_rect_current, is_shift_dragging):
        self.viewport_rect = viewport_rect
        self.selection_indices = selection_indices
        self.visible_indices = visible_indices
        self.rects = rects
        self.drag_rect_start = drag_rect_start
        self.drag_rect_current = drag_rect_current 
        self.is_shift_dragging = is_shift_dragging
        self.raise_()
        self.update()

    def paintEvent(self, event):        
        painter = QtGui.QPainter(self)
        space = self.half_pos - (self._selection_pen.width() / 2)
        painter.setPen(self._selection_pen)

        for index in (self.selection_indices & self.visible_indices):
            if index >= len(self.rects):
                continue
            rect = self.rects[index]
            if rect.intersects(self.viewport_rect):
                color = QtGui.QColor(*self.color, 25)  # 半透明の青
                painter.setBrush(color)
                #painter.setBrush(QtCore.Qt.NoBrush)
                painter.drawRect(rect.adjusted(-space, -space, space, space))

        if self.is_shift_dragging and self.drag_rect_start and self.drag_rect_current:
            selection_rect = QtCore.QRect(self.drag_rect_start, self.drag_rect_current).normalized()
            color = QtGui.QColor(*self.color, 50)  # 半透明の青
            border_color = QtGui.QColor(*self.color)
            painter.setBrush(color)
            painter.setPen(QtGui.QPen(border_color, 1, QtCore.Qt.DashLine))
            painter.drawRect(selection_rect)
        painter.end()

        super().paintEvent(event)

class MouseHandlerBinder(QtCore.QObject):
    def __init__(self, widget):
        super().__init__()
        self.widget = widget

        self._drag_rect_start = None
        self._drag_rect_current = None
        self._is_shift_dragging = False
        self._drag_state = 0
        self._disable_next_click = False

        self.mouse_event_manager = MouseEventManager()
        self._mouse_dispatcher = MouseEventDispatcher(self.widget, self.mouse_event_manager)

    @profiler.profile
    def bind_all(self):
        m = self.mouse_event_manager
        m.bind(MouseActionKey(MouseButton.LEFT, ClickType.SINGLE, ()), self.on_left_click)
        m.bind(MouseActionKey(MouseButton.LEFT, ClickType.DOUBLE, ()), self.on_double_click)
        m.bind(MouseActionKey(MouseButton.RIGHT, ClickType.SINGLE, ()), self.on_right_click)
        m.bind(MouseActionKey(MouseButton.NONE, ClickType.DRAG_START, (MouseButton.LEFT,)), self.on_drag)
        m.bind(MouseActionKey(MouseButton.NONE, ClickType.DROP, ()), self.on_drop)
        m.bind(MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, ()), self.on_wheel)
        m.bind(MouseActionKey(MouseButton.NONE, ClickType.WHEEL_DOWN, ()), self.on_wheel)
        m.bind(
            MouseActionKey(MouseButton.NONE, ClickType.WHEEL_UP, (MouseButton.LEFT,)),
            lambda x: print("Middle press + wheel up to zoom in")
        )

    def _consume_disable_next_click(self) -> bool:
        if self._disable_next_click:
            self._disable_next_click = False
            return True
        return False

    @profiler.profile
    def on_left_click(self, event):
        if self._consume_disable_next_click():
            return
        modifiers = event.modifiers()
        if modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self.on_left_ctrl_click(event)
        elif modifiers & QtCore.Qt.ShiftModifier:
            self.on_left_shift_click(event)
        else: 
            self.on_left_single_click(event)

    @profiler.profile
    def on_left_ctrl_click(self, event):
        if self._consume_disable_next_click():
            return
        index = self.widget.index_at_pos(event.pos())
        if index is not None:
            self.widget.selection_manager.toggle(index)

    @profiler.profile
    def on_left_shift_click(self, event):
        if self._consume_disable_next_click():
            return
        index = self.widget.index_at_pos(event.pos())
        if index is not None:
            last = self.widget.selection_manager.last_added()
            if last is not None:
                if last < index:
                    adding  =list(range(last, index + 1))
                    self.widget.selection_manager.add_selection(adding, -1)
                else:
                    adding  =list(range(index, last + 1))
                    self.widget.selection_manager.add_selection(adding, 0)
            else:
                self.widget.selection_manager.add_selection([index], 0)

    @profiler.profile
    def on_left_single_click(self, event):
        if self._consume_disable_next_click():
            return
        index = self.widget.index_at_pos(event.pos())
        if index is not None:    
            if not self.widget.selection_manager.is_selected(index):
                self.widget.selection_manager.set_selected([index], 0) 
            else:
                if len(self.widget.selection_manager.selected_indices()) > 1:
                    self.widget.selection_manager.set_selected([index], 0)
                else:
                    self.widget.selection_manager.deselect(index)

    @profiler.profile    
    def on_double_click(self, event):
        if self._consume_disable_next_click():
            return
        index = self.widget.index_at_pos(event.pos())
        if index is not None:
            if not self.widget.selection_manager.is_selected(index):
                self.on_left_click(event)
            

    @profiler.profile
    def on_right_click(self, event):
        if self._consume_disable_next_click():
            return
        index = self.widget.index_at_pos(event.pos())
        if index is not None:
            path = self.widget.image_paths[index]
            if self.widget.context_menu_builder:
                menu = self.widget.context_menu_builder.build_menu(path)
                menu.popup(event.globalPos())
            if not self.widget.selection_manager.is_selected(index):
                self.on_left_click(event) 
        else:
            pass

    @profiler.profile
    def on_wheel(self, event):
        if QtWidgets.QApplication.keyboardModifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self.on_zoom_wheel(event)
        else:
            QtWidgets.QWidget.wheelEvent(self.widget, event)

    @profiler.profile
    def on_zoom_wheel(self, event):
        self.widget._restore_scroll_index = self.widget.get_center_image_index()
        delta = event.angleDelta().y()
        zoom_step = 50
        new_height = self.widget.base_height + (zoom_step if delta > 0 else -zoom_step)
        new_height = min(self.widget.max_height, new_height)
        old_height = self.widget.base_height
        self.widget.base_height = max(self.widget.min_height, min(new_height, self.widget.screen_width ))
        if self.widget.base_height != old_height:
            self.widget._debounce_recalc_layout()
            main_setting.set("viewer/zoom", self.widget.base_height)

    @profiler.profile
    def on_drag(self, event):
        modifiers = event.modifiers()
        if modifiers & QtCore.Qt.ShiftModifier and modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self.on_shift_ctrl_drag(event)
        elif modifiers & QtCore.Qt.ShiftModifier:
            self.on_shift_drag(event)
        elif modifiers & (QtCore.Qt.ControlModifier | QtCore.Qt.MetaModifier):
            self.on_ctrl_drag(event)
        else: 
            self.on_drag_start(event)

    def on_shift_drag(self, event):
        self._drag_state = 0
        self.start_shift_drag(event)

    def on_shift_ctrl_drag(self, event):
        self._drag_state = 1
        self.start_shift_drag(event)

    def on_ctrl_drag(self, event):
        self._drag_state = 2
        self.start_shift_drag(event)

    @profiler.profile
    def start_shift_drag(self, event):
        if not self._is_shift_dragging:
            self._is_shift_dragging = True
            self._drag_rect_start = event.pos()
            self._drag_rect_current = event.pos()
            self._disable_next_click = True
            self.widget.update()

    @profiler.profile
    def on_drop(self, event):
        parser = MimeDataParser()
        items = parser.parse(event.mimeData())
        logger.info(items)
        if not items:
            return
        logger.info(items[0].mime_type)
        saver = FileSaver()
        for item in items:
            path = r"C:\Users\openk\Downloads\drop\{}".format(item.name)
            if os.path.exists(path):
                pass # cancel or overwrite or new_name
            if item.is_local_file():
                pass # move or copy
            saver.save(item, path, move=False)
            logger.info(f"Dropped files: {path}")
            

    def finalize_rectangle_selection(self, state=0):
        if not self._drag_rect_start or not self._drag_rect_current:
            return
        rect = QtCore.QRect(self._drag_rect_start, self._drag_rect_current).normalized()
        selected_indices = []
        for i, r in enumerate(self.widget.rects):
            if rect.intersects(r):
                selected_indices.append(i)

        if selected_indices:
            if state == 2:
                self.widget.selection_manager.remove_selection(selected_indices)
            elif state == 1:
                self.widget.selection_manager.add_selection(selected_indices, last=-1)
            else:
                self.widget.selection_manager.set_selected(selected_indices, last=-1)
        else:
            logger.info("No items in selection rectangle.")
        
    @profiler.profile
    def on_drag_start(self, event):
        index = self.widget.index_at_pos(event.pos())
        if index == None:
            return
        if not self.widget.selection_manager.is_selected(index):
            self.on_left_click(event)

        selected = self.widget.get_selected_paths()
        urls = [QtCore.QUrl.fromLocalFile(path) for path in selected]
        if not urls:
            return

        drag = QtGui.QDrag(self)
        mime = QtCore.QMimeData()
        mime.setUrls(urls)
        drag.setMimeData(mime)
        widget = self.widget.widgets.get(index)
        if widget is None:
            logger.warning(f"No widget for index {index}")
            return
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
                pixmap = PixmapFactory.draw_centered_text_with_background(pixmap, f" {len(urls)}  ")

            drag.setPixmap(pixmap)
            drag.setHotSpot(pixmap.rect().topLeft())
        QtCore.QTimer.singleShot(0, lambda: self._start_drag(drag))

    def _start_drag(self, drag):
        # イベントループを回してから実行（より自然なレスポンスになる）
        QtWidgets.QApplication.processEvents()
        drag.exec(QtCore.Qt.CopyAction | QtCore.Qt.MoveAction)
            
    def eventFilter(self, watched, event):
        if event.type() == QtCore.QEvent.MouseMove and self._is_shift_dragging:
            self._drag_rect_current = event.pos()
            self.widget.update()
        elif event.type() == QtCore.QEvent.MouseButtonRelease and self._is_shift_dragging:
            self._drag_rect_current = event.pos()
            self._is_shift_dragging = False
            self.finalize_rectangle_selection(state=self._drag_state)
            self._drag_rect_start = None
            self._drag_rect_current = None
            self.widget.update()     
        elif isinstance(event, QtGui.QDragEnterEvent):
            event.acceptProposedAction()
            return False
        
        return super().eventFilter(watched, event)


class JustifiedVirtualScrollWidget(QtWidgets.QWidget):
    layout_ready = QtCore.Signal()

    def __init__(self, scroll, parent=None):
        super().__init__(parent)
        self.parent_scroll = scroll

        self.mouse_handler = MouseHandlerBinder(self)
        self.mouse_handler.bind_all()
        self.installEventFilter(self.mouse_handler)

        self.setObjectName("JustifiedVirtualScrollWidget")
        self.image_paths = []
        self.aspect_ratios = []
        self.rects = []
        self.rects_tops = []
        self.rects_bottoms = []
        
        self.last_selections = []
        self._restore_scroll_index = None

        self.screen_width = QtGui.QGuiApplication.primaryScreen().availableGeometry().width()
        self.base_height = main_setting.get("viewer/zoom", int(self.screen_width / 10))
        self._width_ref = self.width()
        self.min_height = int(self.screen_width / 30)
        self.max_height = int(self.screen_width)
        self.setMinimumWidth(self.min_height)
        self.spacing = uipx(4)
        self.calculator = None

        self.pixmap_cache = MemoryLimitedPixmapCache(500 * 1024 * 1024)
        self.active_threads = {}

        self.error_placeholder = PixmapFactory.generate()
        self.overlay_painter = OverLayPainter(self, self.spacing)

        self.selection_manager = SelectionManager()
        self.selection_manager.selectionChanged.connect(self._on_selection_changed)

        self.label_pool = QLabelPool(self)
        self.widgets = {}
        self.visible_indices = set()

        self.size_checker = SizeMismatchChecker(self)
        self.size_checker.start()

        self.parent_scroll.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)
        self.parent_scroll.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

    def _on_selection_changed(self, _):
        self.last_selections = self.get_selected_paths()
        logger.info(self.last_selections)
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)

        scroll_y = self.parent_scroll.verticalScrollBar().value()
        scroll_x = self.parent_scroll.horizontalScrollBar().value()
        viewport_rect = self.parent_scroll.viewport().rect().translated(scroll_x, scroll_y)

        self.overlay_painter.paint(
            viewport_rect,
            self.selection_manager.selected_indices(),
            self.visible_indices,
            self.rects,
            self.mouse_handler._drag_rect_start,
            self.mouse_handler._drag_rect_current,
            self.mouse_handler._is_shift_dragging
        )


    @profiler.profile
    def set_context_menu_builder(self, builder):
        self.context_menu_builder = builder
    
    @profiler.profile
    def get_selected_paths(self):
        return [self.image_paths[i] for i in self.selection_manager.selected_indices() if i < len(self.image_paths)]
    
    @profiler.profile
    def get_last_selected_path(self):
        i = self.selection_manager.last_added()
        return self.image_paths[i] if i < len(self.image_paths) else None
    
    @profiler.profile
    def get_mouse_pos_path(self):
        i = self.index_at_pos(self.mapFromGlobal(QtCore.QCursor.pos()))
        return self.image_paths[i] if i < len(self.image_paths) else None

    @profiler.profile
    def index_at_pos(self, pos: QtCore.QPoint) -> int | None:
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
    def set_paths(self, path_list, aspect_ratios):
        if not path_list:
            self._clear_all_widgets()
        if self.image_paths == path_list:
            self.layout_ready.emit()
            return 
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
            else:
                with self.selection_manager.noemit():
                    self.selection_manager.clear()

        index = self.get_last_index()
        logger.info(index)
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

        if not self.rects_bottoms or not self.rects_tops:
            return
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

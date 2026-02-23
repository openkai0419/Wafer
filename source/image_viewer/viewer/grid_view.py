import bisect
import math
from PySide6 import QtCore, QtGui, QtWidgets
from ...common.funcs import uipx
from ...common.profiling import profiler
from ...common.logs import AppLogger
from .loader import ImageLoaderRunnable
from ...qt.debounce import qt_debounce, qt_throttle
from ...qt.pixmap import PixmapFactory
from ...qt.thread import main_thread
from ..viewer_settings import main_setting
from ...io.grid.handler import grid_handler
from .cachemanager import MemoryLimitedImageCache, GraphicsItemPool, ProxyWidgetPool
from .calc_layout import JustifiedLayoutCalculator, LayoutData
from .items import ViewerItems
from ...actions.bridge import Kit


class GridView(QtWidgets.QGraphicsView, Kit.UIMixin):
    layout_started = QtCore.Signal()
    layout_ready = QtCore.Signal()
    base_height_changed = QtCore.Signal()
    resized = QtCore.Signal()

    def __init__(self, root, items: ViewerItems | None = None, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlags(QtWidgets.QGraphicsView.DontAdjustForAntialiasing)
        self.setRenderHint(QtGui.QPainter.SmoothPixmapTransform, False)

        self.root = root
        self.items = items or ViewerItems(self)
        self.init_command_binding("GridView", enable_drops=True)
        self.setObjectName('GridView')

        self.rects = LayoutData.empty()
        self.last_selections = []
        self._restore_scroll_path = None
        self._rect_select_mode = "replace"
        self._rect_select_dragging = False
        self._rect_select_start_pos = None
        self._rect_select_current_pos = None
        self._drop_preview_rect = None
        self._drop_preview_title = None
        self._drop_preview_text = None

        self.screen_width = QtGui.QGuiApplication.primaryScreen().availableGeometry().width()
        self.base_height = main_setting.get('viewer/zoom', int(self.screen_width / 10))
        self._width_ref = 0
        self.min_height = int(self.screen_width / 30)
        self.max_height = int(self.screen_width)
        self.setMinimumWidth(self.min_height)
        self.spacing = uipx(4)
        self.orientation = main_setting.get('viewer/orientation', 0)
        self._hz = self.orientation <= 1
        self._reversed = self.orientation == 3
        self.calculator = None
        self.image_cache = MemoryLimitedImageCache(main_setting.get('window/chache_size', 500))
        self.label_pool = GraphicsItemPool(self._scene)
        self.proxy_pool = ProxyWidgetPool(self._scene, grid_handler)
        self.active_threads = {}
        self._widget_plugin_names: dict[int, str] = {}
        self.error_placeholder = PixmapFactory.generate().toImage()

        self.color = (59, 128, 255)
        self._half_pos = self.spacing / 2
        self._qcolor_main = QtGui.QColor(*self.color)
        self._qcolor_fill_sel = QtGui.QColor(*self.color, 25)
        self._qcolor_fill_drag = QtGui.QColor(*self.color, 50)
        self._selection_pen = QtGui.QPen(self._qcolor_main, max(1, self.spacing * 0.5))
        self._selection_pen.setCosmetic(True)

        self.items.selectionChanged.connect(self._on_selection_changed)
        self.widgets = {}
        self.visible_indices = set()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

        self._scroll_speed = 100
        self._speed_callback = self.get_adjusted_scroll_speed
        self._connected_bar = None
        self._auto_scroll_anim = None
        self._setup_primary_scroll()

    @property
    def parent_scroll(self):
        return self

    def _is_horizontal(self):
        return self._hz

    def _is_primary_reversed(self):
        return self._reversed

    def _primary_bar(self):
        return self.verticalScrollBar() if self._hz else self.horizontalScrollBar()

    def _primary_viewport_size(self):
        vp = self.viewport()
        return vp.height() if self._hz else vp.width()

    def _secondary_viewport_size(self):
        vp = self.viewport()
        return vp.width() if self._hz else vp.height()

    def _primary_pos(self, point):
        return point.y() if self._hz else point.x()

    def _setup_primary_scroll(self):
        bar = self._primary_bar()
        if self._connected_bar is not None:
            try:
                self._connected_bar.sliderPressed.disconnect(self._on_auto_scroll_user_interaction)
                self._connected_bar.actionTriggered.disconnect(self._on_auto_scroll_user_interaction)
            except RuntimeError:
                pass
        if self._auto_scroll_anim is not None:
            self._auto_scroll_anim.stop()
        self._auto_scroll_anim = QtCore.QPropertyAnimation(bar, b"value")
        self._auto_scroll_anim.setEasingCurve(QtCore.QEasingCurve.Linear)
        bar.sliderPressed.connect(self._on_auto_scroll_user_interaction)
        bar.actionTriggered.connect(self._on_auto_scroll_user_interaction)
        self._connected_bar = bar

    def set_orientation(self, orientation):
        if self.orientation == orientation:
            return
        self.orientation = orientation
        self._hz = orientation <= 1
        self._reversed = orientation == 3
        self._width_ref = self._secondary_viewport_size()
        main_setting.set('viewer/orientation', orientation)
        self._setup_primary_scroll()
        self._recalc_layout()

    def set_speed_callback(self, callback):
        self._speed_callback = callback

    def start_auto_scroll(self, speed=100):
        self._scroll_speed = speed
        self._start_auto_scroll_from_current()

    def stop_auto_scroll(self):
        self._auto_scroll_anim.stop()

    def isscrolling(self):
        return self._auto_scroll_anim.state() == QtCore.QAbstractAnimation.Running

    def _on_auto_scroll_user_interaction(self):
        if self.isscrolling():
            self._start_auto_scroll_from_current()

    def _start_auto_scroll_from_current(self):
        bar = self._primary_bar()
        start_value = max(bar.minimum(), min(bar.value(), bar.maximum()))
        if self._is_primary_reversed():
            end_value = bar.minimum()
        else:
            end_value = bar.maximum()
        distance = abs(end_value - start_value)
        if distance < 1:
            self.stop_auto_scroll()
            return
        if self._speed_callback:
            self._scroll_speed = self._speed_callback()
        duration = min(int(distance / max(self._scroll_speed, 0.01) * 1000), 2147483647)
        self._auto_scroll_anim.stop()
        self._auto_scroll_anim.setStartValue(start_value)
        self._auto_scroll_anim.setEndValue(end_value)
        self._auto_scroll_anim.setDuration(duration)
        self._auto_scroll_anim.start()

    def extend_context(self, ctx, cmd, event=None, key=None, source=None):
        paths = self.items.selected_paths()
        path = self.items.last_selected_path()
        return {"path": path, "paths": paths}

    def _on_selection_changed(self, _):
        self.last_selections = self.items.selected_paths()
        self.viewport().update()

    def _scene_view_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect().toAlignedRect()

    def drawForeground(self, painter, rect):
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        space = self._half_pos - self._selection_pen.width() / 2
        view_rect = self._scene_view_rect()
        sel_indices = self.items.selected_indices()
        if sel_indices and self.visible_indices and self.rects:
            indices = sel_indices & self.visible_indices
            rect_list = []
            for i in indices:
                if 0 <= i < len(self.rects):
                    r = self.rects[i]
                    if r.intersects(view_rect):
                        rect_list.append(QtCore.QRectF(r).adjusted(-space, -space, space, space))
            if rect_list:
                painter.setPen(self._selection_pen)
                painter.setBrush(self._qcolor_fill_sel)
                for r in rect_list:
                    painter.drawRect(r)
        if self._rect_select_dragging and self._rect_select_start_pos and self._rect_select_current_pos:
            selection_rect = QtCore.QRectF(
                QtCore.QPointF(self._rect_select_start_pos),
                QtCore.QPointF(self._rect_select_current_pos)
            ).normalized()
            dash_pen = QtGui.QPen(self._qcolor_main, 1, QtCore.Qt.DashLine)
            dash_pen.setCosmetic(True)
            painter.setPen(dash_pen)
            painter.setBrush(self._qcolor_fill_drag)
            painter.drawRect(selection_rect)
        if self._drop_preview_rect and not self._drop_preview_rect.isNull():
            r = QtCore.QRectF(self._drop_preview_rect)
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 160))
            painter.drawRect(r)
            if self._drop_preview_title or self._drop_preview_text:
                inner = r.adjusted(2, 2, -2, -2)
                painter.save()
                painter.setPen(QtGui.QColor(255, 255, 255))
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                fm = QtGui.QFontMetrics(font)
                title = fm.elidedText(str(self._drop_preview_title or ""), QtCore.Qt.ElideMiddle, max(1, int(inner.width() - self._half_pos)))
                text = fm.elidedText(str(self._drop_preview_text or ""), QtCore.Qt.ElideMiddle, max(1, int(inner.width() - self._half_pos)))
                painter.drawText(inner.toRect(), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, f"{title}\n{text}".strip())
                painter.restore()

    @profiler.profile
    def get_mouse_pos_path(self):
        i = self.index_at_pos(self.viewport().mapFromGlobal(QtCore.QCursor.pos()))
        return self.items.path_at(i)

    def get_mouse_pos_source(self):
        i = self.index_at_pos(self.viewport().mapFromGlobal(QtCore.QCursor.pos()))
        return self.items.source_at(i)

    @profiler.profile
    def index_at_pos(self, pos):
        if not self.rects:
            return None
        scene_pos = self.mapToScene(pos)
        return self.rects.index_at_point(scene_pos.toPoint())

    def to_scene_pos(self, pos):
        return self.mapToScene(pos).toPoint()

    def grab_widget_pixmap(self, index):
        w = self.widgets.get(index)
        if w is None:
            return None
        if hasattr(w, 'pixmap'):
            p = w.pixmap()
            if not p.isNull():
                return p
        if isinstance(w, QtWidgets.QGraphicsProxyWidget) and w.widget():
            return w.widget().grab()
        return None

    @qt_throttle(50, 100)
    def _on_scroll_bar_changed(self, *args, **kwargs):
        self._update_visible_items()

    @profiler.profile
    def set_paths(self, path_list, sources, aspect_ratios, keep_scroll=True):
        if not path_list:
            self.items.clear()
            self._clear_all_widgets()
            self.layout_ready.emit()
            return
        if self.items.paths == path_list and self.items.sources == sources and self.items.aspect_ratios == aspect_ratios:
            self.layout_ready.emit()
            return
        self.last_selections = self.items.selected_paths()
        if keep_scroll:
            center_idx = self.get_center_image_index()
            self._restore_scroll_path = self.items.path_at(center_idx) if center_idx is not None else None
        else:
            self._restore_scroll_path = None
        self._clear_all_widgets()
        with self.items.selection_noemit():
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
        self._widget_plugin_names.clear()
        self.visible_indices.clear()
        self.rects = LayoutData.empty()
        self._scene.setSceneRect(0, 0, 0, 0)

    @profiler.profile
    @qt_debounce(100)
    def on_resize_event(self):
        sv = self._secondary_viewport_size()
        if sv > 0 and self._width_ref > 0 and sv != self._width_ref:
            scale = sv / self._width_ref
            new_height = int(self.base_height * scale)
            new_height = min(self.max_height, max(self.min_height, new_height))
            if new_height != self.base_height:
                self.base_height = new_height
                self._width_ref = sv
                self.base_height_changed.emit()
        elif self._width_ref == 0 and sv > 0:
            self._width_ref = sv
        center_idx = self.get_center_image_index()
        self._restore_scroll_path = self.items.path_at(center_idx) if center_idx is not None else None
        self._recalc_layout()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.resized.emit()
        self.on_resize_event()

    @qt_debounce(100)
    def _debounce_recalc_layout(self):
        self._recalc_layout()

    @profiler.profile
    def _recalc_layout(self):
        self.layout_started.emit()
        if self.calculator:
            self.calculator.cancel()
        margin = self._half_pos
        secondary = self._secondary_viewport_size() - margin * 2
        primary_vp = self._primary_viewport_size()
        bh = self.base_height
        if self._is_horizontal():
            cw, ch = secondary, primary_vp
        else:
            cw, ch = primary_vp, secondary
            ratios = self.items.aspect_ratios
            avg_aspect = sum(r or 1.0 for r in ratios) / len(ratios) if ratios else 1.0
            bh = int(bh * avg_aspect)
        self.calculator = JustifiedLayoutCalculator(self.items.aspect_ratios, bh, self.spacing, cw, ch, self.orientation)
        self.calculator.signals.layout_ready.connect(self._on_layout_ready)
        main_thread.start(self.calculator, 7)

    def get_adjusted_scroll_speed(self, base_speed=50):
        reference_height = self.screen_width / 10
        speed_ratio = self.base_height / reference_height
        return base_speed * max(0.1, min(speed_ratio, 1.0))

    @profiler.profile
    def get_center_image_index(self):
        if not self.rects:
            return None
        center = self.mapToScene(self.viewport().rect().center()).toPoint()
        return self.rects.index_at_point(center)

    def _group_starts(self) -> list[int]:
        return self.rects.group_starts

    def _effective_scroll_top(self, bar):
        if (hasattr(self, '_scroll_anim') and self._scroll_anim is not None
                and self._scroll_anim.state() == QtCore.QAbstractAnimation.Running
                and hasattr(self, '_scroll_target')):
            return self._scroll_target
        return bar.value()

    def _is_center_anchor(self):
        from ...actions.bridge import Command
        return Command.get_action_group_current('grid_scroll_anchor') == 'grid.scroll_anchor_center'

    def _group_ends(self) -> list[int]:
        return self.rects.group_ends

    def _group_mids(self) -> list[int]:
        return self.rects.group_mids

    def _scroll_row(self, forward: bool, animated: bool = True):
        bar = self._primary_bar()
        vs = self._primary_viewport_size()
        rev = self._is_primary_reversed()
        if self._is_center_anchor():
            refs = self._group_mids()
            current = self._effective_scroll_top(bar) + vs // 2
            offset = vs // 2
        elif rev:
            refs = self._group_ends()
            current = self._effective_scroll_top(bar) + vs
            offset = vs
        else:
            refs = self._group_starts()
            current = self._effective_scroll_top(bar)
            offset = 0
        if forward != rev:
            idx = bisect.bisect_right(refs, current)
            if idx < len(refs):
                self._scroll_to(refs[idx] - offset, animated)
        else:
            idx = bisect.bisect_left(refs, current) - 1
            if idx >= 0:
                self._scroll_to(refs[idx] - offset, animated)

    def scroll_to_next_row(self, animated: bool = True):
        self._scroll_row(True, animated)

    def scroll_to_prev_row(self, animated: bool = True):
        self._scroll_row(False, animated)

    def _scroll_to(self, y: int, animated: bool = True):
        bar = self._primary_bar()
        target = max(bar.minimum(), min(y, bar.maximum()))
        self._scroll_target = target
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
    def reinstall_scroll_index(self, ind, animated: bool = False):
        bar = self._primary_bar()
        vs = self._primary_viewport_size()
        is_center = self._is_center_anchor()
        rev = self._is_primary_reversed()
        if ind < len(self.rects):
            rect = self.rects[ind]
            if is_center:
                y = self._primary_pos(rect.center()) - vs // 2
            elif rev:
                primary_size = rect.height() if self._hz else rect.width()
                y = self._primary_pos(rect.topLeft()) + primary_size - vs
            else:
                y = self._primary_pos(rect.topLeft())
        else:
            y = bar.maximum()
        self._scroll_to(y, animated)

    def _needs_reload(self, item, cell_size):
        if not hasattr(item, 'pixmap'):
            return False
        pixmap = item.pixmap()
        if pixmap.isNull():
            return False
        margin = uipx(3) * 2
        return pixmap.width() < (cell_size.width() - margin) or pixmap.height() < (cell_size.height() - margin)

    def _request_reload(self, i, rect):
        if i in self.active_threads:
            self.active_threads.pop(i).cancel()
        runnable = ImageLoaderRunnable(i, self.items.paths[i], rect.size(), self)
        runnable.signal.image_ready.connect(self._on_image_ready)
        runnable.signal.widget_ready.connect(self._on_widget_ready)
        self.active_threads[i] = runnable
        main_thread.start(runnable, 5)

    @profiler.profile
    def _on_layout_ready(self, layout):
        was_scrolling = self.isscrolling()
        self.rects = layout
        n = len(layout)
        for i in list(self.visible_indices):
            if i < n and i in self.widgets:
                self.widgets[i].setGeometry(layout[i])
                if self._needs_reload(self.widgets[i], layout[i].size()):
                    self._request_reload(i, layout[i])
            else:
                self._recycle_widget(i)
                self.visible_indices.discard(i)
        self._update_visible_items()
        self.layout_ready.emit()
        if self.last_selections:
            indexes = [i for i in (self.items.index_of_path(p) for p in self.last_selections) if i is not None]
            if indexes:
                with self.items.selection_noemit():
                    self.items.set_selected(indexes, last=-1)
            else:
                with self.items.selection_noemit():
                    self.items.clear_selection()
        index = self.get_restore_index()
        if index is None:
            index = 0
        elif index >= len(self.rects):
            index = 0
        self.reinstall_scroll_index(index)
        if was_scrolling:
            self._start_auto_scroll_from_current()

    @profiler.profile
    def get_restore_index(self):
        if main_setting.is_first_time('viewer/scroll'):
            return main_setting.get('viewer/scroll', 0)
        last_path = self.items.last_selected_path()
        if last_path is not None:
            idx = self.items.index_of_path(last_path)
            if idx is not None:
                return idx
        if self._restore_scroll_path is not None:
            path = self._restore_scroll_path
            self._restore_scroll_path = None
            idx = self.items.index_of_path(path)
            if idx is not None:
                return idx
        return None

    @profiler.profile
    def _update_visible_items(self):
        if not self.rects:
            return
        view_rect = self._scene_view_rect()
        visible_range = self._calculate_visible_indices(view_rect)
        expanded_range = self._expand_prefetch_range(visible_range)
        new_visible = set(expanded_range)
        newly_added = new_visible - self.visible_indices
        no_longer_visible = self.visible_indices - new_visible
        if newly_added:
            if isinstance(visible_range, range):
                center = (visible_range.start + visible_range.stop) // 2
            else:
                center = (min(visible_range) + max(visible_range)) // 2 if visible_range else 0
            sorted_added = sorted(newly_added, key=lambda i: abs(i - center))
            for i in sorted_added:
                if i < len(self.rects):
                    self._ensure_widget_visible(i)
        for i in no_longer_visible:
            self._recycle_widget(i)
        self.visible_indices = new_visible
        if self.rects:
            margin = self._half_pos
            if self._hz:
                new_rect = QtCore.QRectF(-margin, -margin, max(self.viewport().width(), 1), self.rects.total_extent + margin)
            else:
                new_rect = QtCore.QRectF(-margin, -margin, self.rects.total_extent + margin, max(self.viewport().height(), 1))
            if self._scene.sceneRect() != new_rect:
                self._scene.setSceneRect(new_rect)
        self.viewport().update()

    @profiler.profile
    def _calculate_visible_indices(self, view_rect):
        if not self.rects:
            return range(0, 0)
        hz = self._hz
        p_start = view_rect.top() if hz else view_rect.left()
        p_end = view_rect.bottom() if hz else view_rect.right()
        return self.rects.calculate_visible_indices(p_start, p_end)

    @profiler.profile
    def _expand_prefetch_range(self, visible):
        if not visible:
            return range(0, 0)
        if isinstance(visible, range):
            prefetch = len(visible) + 3
            start = max(0, visible.start - prefetch)
            end = min(len(self.rects), visible.stop + prefetch)
        else:
            prefetch = len(visible) + 3
            v_min, v_max = min(visible), max(visible)
            start = max(0, v_min - prefetch)
            end = min(len(self.rects), v_max + 1 + prefetch)
        return range(start, end)

    @profiler.profile
    def _ensure_widget_visible(self, i):
        rect = self.rects[i]
        if i >= len(self.items.paths):
            AppLogger.warning(f'Index {i} out of range for paths (len={len(self.items.paths)})')
            return
        if i not in self.widgets:
            path = self.items.paths[i]
            item = self.label_pool.acquire()
            item.setGeometry(rect)
            self.widgets[i] = item
            cached = self.image_cache.get(path)
            if cached is not None:
                item.set_image(cached, path)
            if (not cached or self._needs_reload(item, rect.size())) and i not in self.active_threads:
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
            item = self.widgets.pop(i)
            plugin_name = self._widget_plugin_names.pop(i, None)
            if plugin_name is not None and isinstance(item, QtWidgets.QGraphicsProxyWidget):
                self.proxy_pool.release(item, plugin_name)
            else:
                if hasattr(item, "delete"):
                    item.delete()
                self.label_pool.release(item)
        if i in self.active_threads:
            runnable = self.active_threads.pop(i)
            if hasattr(runnable, 'cancel'):
                runnable.cancel()

    @profiler.profile
    @QtCore.Slot(int, object)
    def _on_image_ready(self, index, image):
        if index >= len(self.items.paths):
            return
        runnable = self.active_threads.pop(index, None)
        if runnable is not None and runnable.path != self.items.paths[index]:
            return
        if index in self.widgets:
            path = self.items.paths[index]
            self.image_cache[path] = image
            self.widgets[index].set_image(image, path)

    @profiler.profile
    @QtCore.Slot(int, str)
    def _on_widget_ready(self, index, plugin_name):
        if index >= len(self.items.paths):
            return
        runnable = self.active_threads.pop(index, None)
        if runnable is not None and runnable.path != self.items.paths[index]:
            return
        proxy = self.proxy_pool.acquire(plugin_name)
        if proxy is not None:
            rect = self.rects[index]
            proxy.setGeometry(QtCore.QRectF(rect))
            if index in self.widgets:
                self._recycle_widget(index)
            self.widgets[index] = proxy
            self._widget_plugin_names[index] = plugin_name
            path = self.items.paths[index]
            size = rect.size().toSize()
            grid_handler.render(path, proxy.widget(), size)
import math
from PySide6 import QtCore, QtGui, QtWidgets
from ....utils.formatting import dpix
from ....utils.profiling import profiler
from ....core.qt.rate_limit import qt_debounce, qt_throttle
from ....core.qt.dispatcher import Dispatcher
from ....core.setting.app_settings import app_settings
from ....plugin.grid.handler import grid_resolver, WidgetNotifier
from ....plugin.grid.base import WidgetGridPlugin as _WidgetGridPlugin
from .cachemanager import MemoryLimitedImageCache, GraphicsItemPool, AdditionalWidgetPool
from ....plugin.layout.calc import LayoutData
from .pipeline import GridPipeline
from .items import GridItemModel
from ....core.color.theme import ThemeManager
from ....core.commands.bridge import ActionKit

class _SelectionOverlay(QtWidgets.QWidget):
    def __init__(self, grid_view, parent):
        super().__init__(parent)
        self._grid = grid_view
        self.setAttribute(QtCore.Qt.WA_TransparentForMouseEvents)
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)

    def _map_rect(self, scene_rect):
        g = self._grid
        tl = g.mapFromScene(scene_rect.topLeft())
        br = g.mapFromScene(scene_rect.bottomRight())
        return QtCore.QRectF(QtCore.QPointF(tl), QtCore.QPointF(br))

    def paintEvent(self, event):
        parent = self.parent()
        if parent is not None:
            expected = parent.rect()
            if self.geometry() != expected:
                self.setGeometry(expected)
        g = self._grid
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing, False)
        sel_indices = g.items.selected_indices()
        if sel_indices and g.visible_indices and g.rects:
            indices = sel_indices & g.visible_indices
            if indices:
                space = g._half_pos - g._selection_pen.width() / 2
                view_rect = g._scene_view_rect()
                rect_list = []
                for i in indices:
                    if 0 <= i < len(g.rects):
                        r = g.rects[i]
                        if r.intersects(view_rect):
                            vp_r = self._map_rect(QtCore.QRectF(r))
                            rect_list.append(vp_r.adjusted(-space, -space, space, space))
                if rect_list:
                    painter.setPen(g._selection_pen)
                    painter.setBrush(g._qcolor_fill_sel)
                    for r in rect_list:
                        painter.drawRect(r)
        if g._rect_select_dragging and g._rect_select_start_pos and g._rect_select_current_pos:
            start = QtCore.QPointF(g.mapFromScene(QtCore.QPointF(g._rect_select_start_pos)))
            cur = QtCore.QPointF(g.mapFromScene(QtCore.QPointF(g._rect_select_current_pos)))
            selection_rect = QtCore.QRectF(start, cur).normalized()
            dash_pen = QtGui.QPen(g._qcolor_main, 1, QtCore.Qt.DashLine)
            dash_pen.setCosmetic(True)
            painter.setPen(dash_pen)
            painter.setBrush(g._qcolor_fill_drag)
            painter.drawRect(selection_rect)
        if g._drop_preview_rect and not g._drop_preview_rect.isNull():
            r = self._map_rect(QtCore.QRectF(g._drop_preview_rect))
            painter.setPen(QtCore.Qt.NoPen)
            painter.setBrush(QtGui.QColor(0, 0, 0, 160))
            painter.drawRect(r)
            if g._drop_preview_title or g._drop_preview_text:
                inner = r.adjusted(2, 2, -2, -2)
                painter.save()
                painter.setPen(QtGui.QColor(255, 255, 255))
                font = painter.font()
                font.setBold(True)
                painter.setFont(font)
                fm = QtGui.QFontMetrics(font)
                title = fm.elidedText(str(g._drop_preview_title or ""), QtCore.Qt.ElideMiddle, max(1, int(inner.width() - g._half_pos)))
                text = fm.elidedText(str(g._drop_preview_text or ""), QtCore.Qt.ElideMiddle, max(1, int(inner.width() - g._half_pos)))
                painter.drawText(inner.toRect(), QtCore.Qt.AlignHCenter | QtCore.Qt.AlignVCenter, f"{title}\n{text}".strip())
                painter.restore()
        painter.end()


class GridView(QtWidgets.QGraphicsView, ActionKit.UIMixin):
    layout_started = QtCore.Signal()
    layout_ready = QtCore.Signal()
    base_height_changed = QtCore.Signal()
    resized = QtCore.Signal()

    def __init__(self, root, items: GridItemModel | None = None, parent=None):
        super().__init__(parent)
        self._scene = QtWidgets.QGraphicsScene(self)
        self.setScene(self._scene)
        self.setAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        self.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarAsNeeded)
        self.setViewportUpdateMode(QtWidgets.QGraphicsView.MinimalViewportUpdate)
        self.setOptimizationFlags(QtWidgets.QGraphicsView.DontAdjustForAntialiasing)
        self.setRenderHints(QtGui.QPainter.Antialiasing | QtGui.QPainter.SmoothPixmapTransform)

        self.root = root
        self.items = items or GridItemModel(self)
        self.init_command_binding("GridView", enable_drops=True)
        self.setObjectName('GridView')

        self.rects = LayoutData.empty()
        self.last_selections = []
        self._restore_scroll_path = None
        self._pending_scroll_index = None
        self._rect_select_mode = "replace"
        self._rect_select_dragging = False
        self._rect_select_start_pos = None
        self._rect_select_current_pos = None
        self._drop_preview_rect = None
        self._drop_preview_title = None
        self._drop_preview_text = None

        self.screen_width = QtGui.QGuiApplication.primaryScreen().availableGeometry().width()
        self.base_height = int(self.screen_width / 10)
        self._width_ref = 0
        self._zoom_restore_guard = False
        self.min_height = int(self.screen_width / 30)
        self.max_height = int(self.screen_width)
        self.setMinimumSize(self.min_height, self.min_height)
        self.spacing = dpix(4)
        self.orientation = 0
        self._hz = self.orientation <= 1
        self._reversed = self.orientation == 3
        self.layout_mode = 'justified'
        self.image_cache = MemoryLimitedImageCache(app_settings.get('window/cache_size', 500))
        self.pixmap_item_pool = GraphicsItemPool(self._scene)
        self.additional_pool = AdditionalWidgetPool(grid_resolver)
        self.additional_pool.warm_up(self.viewport())
        self._notifier = WidgetNotifier(grid_resolver.registry)
        from ....core.qt.thread import grid_thumb_pool, grid_render_pool, utility_pool
        self._thumb_dispatcher = Dispatcher(grid_thumb_pool)
        self._render_dispatcher = Dispatcher(grid_render_pool)
        self._utility_dispatcher = Dispatcher(utility_pool)
        self._pipeline = GridPipeline(
            self._thumb_dispatcher, self._render_dispatcher,
            self._utility_dispatcher,
            self.image_cache, self._widget_lookup, self._promote_to_widget,
        )
        self._pipeline.layout_ready.connect(self._on_layout_ready)

        _accent = QtGui.QColor(ThemeManager.instance().palette.accent)
        self._half_pos = self.spacing / 2
        self._qcolor_main = _accent
        self._qcolor_fill_sel = QtGui.QColor(_accent)
        self._qcolor_fill_sel.setAlpha(25)
        self._qcolor_fill_drag = QtGui.QColor(_accent)
        self._qcolor_fill_drag.setAlpha(50)
        self._selection_pen = QtGui.QPen(self._qcolor_main, max(1, self.spacing * 0.5))
        self._selection_pen.setCosmetic(True)

        self.items.selectionChanged.connect(self._on_selection_changed)
        self.widgets = {}
        self._additional_widgets: dict[int, QtWidgets.QWidget] = {}
        self._prev_selection_set: set[int] = set()
        self.visible_indices = set()

        self.verticalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)
        self.horizontalScrollBar().valueChanged.connect(self._on_scroll_bar_changed)

        self._overlay = _SelectionOverlay(self, self.viewport())
        self._overlay.setGeometry(self.viewport().rect())
        self._overlay.show()
        self.viewport().installEventFilter(self)

        self._scroll_speed = 100
        self._autoscroll_base_speed = 50
        self._speed_callback = lambda: self.get_adjusted_scroll_speed(self._autoscroll_base_speed)
        self._connected_bar = None
        self._auto_scroll_anim = None
        self._scroll_anim = None
        self._scroll_target = 0
        self._setup_primary_scroll()

    def eventFilter(self, obj, event):
        if obj is self.viewport():
            t = event.type()
            if t == QtCore.QEvent.Resize:
                self._overlay.setGeometry(self.viewport().rect())
                self._overlay.raise_()
            elif t == QtCore.QEvent.Paint:
                self._overlay.update()
        return super().eventFilter(obj, event)

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
        self._setup_primary_scroll()
        self._recalc_layout()

    def set_layout_mode(self, mode):
        if self.layout_mode == mode:
            return
        self.layout_mode = mode
        self._recalc_layout()

    def set_speed_callback(self, callback):
        self._speed_callback = callback

    def start_auto_scroll(self, speed=100, base_speed=50):
        self._scroll_speed = speed
        self._autoscroll_base_speed = base_speed
        self._start_auto_scroll_from_current()

    def stop_auto_scroll(self):
        self._auto_scroll_anim.stop()

    def is_scrolling(self):
        return self._auto_scroll_anim.state() == QtCore.QAbstractAnimation.Running

    def _on_auto_scroll_user_interaction(self):
        if self.is_scrolling():
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

    @profiler.profile
    def _on_selection_changed(self, current_selection):
        newly_selected = current_selection - self._prev_selection_set
        newly_deselected = self._prev_selection_set - current_selection
        self._prev_selection_set = set(current_selection)
        for i in newly_deselected:
            widget = self._additional_widgets.get(i)
            if widget is not None:
                self._notifier.deselect(i, widget)
        for i in newly_selected:
            widget = self._additional_widgets.get(i)
            if widget is not None:
                self._notifier.select(i, widget)
        self.last_selections = self.items.selected_paths()
        self._overlay.update()

    def _scene_view_rect(self):
        return self.mapToScene(self.viewport().rect()).boundingRect().toAlignedRect()

    @profiler.profile
    def get_mouse_pos_path(self):
        return self.items.path_at(self._index_at_cursor())

    def get_mouse_pos_source(self):
        return self.items.source_at(self._index_at_cursor())

    def _index_at_cursor(self):
        return self.index_at_pos(self.viewport().mapFromGlobal(QtCore.QCursor.pos()))

    @profiler.profile
    def index_at_pos(self, pos):
        if not self.rects:
            return None
        scene_pos = self.mapToScene(pos)
        return self.rects.index_at_point(scene_pos.toPoint())

    def to_scene_pos(self, pos):
        return self.mapToScene(pos).toPoint()

    def grab_widget_pixmap(self, index):
        if index in self._additional_widgets:
            return self._additional_widgets[index].grab()
        w = self.widgets.get(index)
        if w is None:
            return None
        if hasattr(w, 'pixmap'):
            p = w.pixmap()
            if not p.isNull():
                return p
        return None

    @profiler.profile
    @qt_throttle(50, 100)
    def _on_scroll_bar_changed(self, *args, **kwargs):
        self._update_visible_items()

    @profiler.profile
    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._overlay.move(0, 0)
        self._sync_additional_widgets()
        self._overlay.update()

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
        for i in list(self._additional_widgets.keys()):
            self._recycle_widget(i)
        self.widgets.clear()
        self._additional_widgets.clear()
        self._notifier.clear()
        self._pipeline.cancel_all()
        self.visible_indices.clear()
        self.rects = LayoutData.empty()
        self._scene.setSceneRect(0, 0, 0, 0)

    @profiler.profile
    @qt_debounce(100)
    def on_resize_event(self):
        sv = self._secondary_viewport_size()
        if sv > 0 and self._width_ref > 0 and sv != self._width_ref:
            if not self._zoom_restore_guard:
                scale = sv / self._width_ref
                new_height = int(self.base_height * scale)
                new_height = min(self.max_height, max(self.min_height, new_height))
                if new_height != self.base_height:
                    self.base_height = new_height
                    self.base_height_changed.emit()
            self._width_ref = sv
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
        if not self.items.aspect_ratios:
            return
        self.layout_started.emit()
        margin = self._half_pos
        secondary = self._secondary_viewport_size() - margin * 2
        primary_vp = self._primary_viewport_size()
        bh = self.base_height
        if self._is_horizontal():
            cw, ch = secondary, primary_vp
        else:
            cw, ch = primary_vp, secondary
        if self.layout_mode != 'masonry' and not self._is_horizontal():
            bh = int(bh * self.items.avg_aspect)
        self._pipeline.request_layout(
            self.items.aspect_ratios, bh, self.spacing,
            cw, ch, self.orientation, self.layout_mode,
        )

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

    def _effective_scroll_top(self, bar):
        if (self._scroll_anim is not None
                and self._scroll_anim.state() == QtCore.QAbstractAnimation.Running):
            return self._scroll_target
        return bar.value()

    def _is_center_anchor(self):
        from ....core.commands.bridge import Command
        return Command.get_action_group_current('grid_scroll_anchor') == 'grid.scroll_anchor_center'

    def _find_center_index(self):
        rects = self.rects
        if not rects:
            return None
        bar = self._primary_bar()
        vs = self._primary_viewport_size()
        hz = self._hz
        scroll_top = self._effective_scroll_top(bar)
        center_p = scroll_top + vs // 2
        actual = self.mapToScene(self.viewport().rect().center()).toPoint()
        center = QtCore.QPoint(actual.x(), center_p) if hz else QtCore.QPoint(center_p, actual.y())
        idx = rects.index_at_point(center)
        if idx is not None:
            return idx
        biased = QtCore.QPoint(center.x() - self.spacing, center.y()) if hz else QtCore.QPoint(center.x(), center.y() - self.spacing)
        idx = rects.index_at_point(biased)
        if idx is not None:
            return idx
        view_rect = self._scene_view_rect()
        s_start = view_rect.left() if hz else view_rect.top()
        s_end = view_rect.right() if hz else view_rect.bottom()
        visible = rects.calculate_visible_indices(scroll_top, scroll_top + vs, s_start, s_end)
        if not visible:
            return None
        return min(visible, key=lambda i: (
            abs(((rects[i].y() + rects[i].height() // 2) if hz else (rects[i].x() + rects[i].width() // 2)) - center_p),
            (rects[i].x() if hz else rects[i].y()),
        ))

    def _scroll_row(self, forward: bool, animated: bool = True):
        rects = self.rects
        if not rects:
            return
        vs = self._primary_viewport_size()
        hz = self._hz
        increasing = forward != self._is_primary_reversed()
        idx = self._find_center_index()
        if idx is None:
            return
        neighbor = rects.nearest_in_direction(idx, increasing)
        if neighbor is None:
            return
        nr = rects[neighbor]
        if self._is_center_anchor():
            target = (nr.y() + nr.height() // 2 if hz else nr.x() + nr.width() // 2) - vs // 2
        elif increasing:
            target = nr.y() if hz else nr.x()
        else:
            target = (nr.y() + nr.height() if hz else nr.x() + nr.width()) - vs
        self._scroll_to(target, animated)

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
        if self._scroll_anim is not None:
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
    def scroll_to_index(self, ind, animated: bool = False):
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
        margin = dpix(3) * 2
        return pixmap.width() < (cell_size.width() - margin) or pixmap.height() < (cell_size.height() - margin)

    def _content_size(self, cell_size):
        margin = dpix(3) * 2
        return QtCore.QSize(int(cell_size.width()) - margin, int(cell_size.height()) - margin)

    def _widget_lookup(self, index):
        widget = self._additional_widgets.get(index)
        if widget is not None:
            return widget
        return self.widgets.get(index)

    @profiler.profile
    def _on_layout_ready(self, layout):
        was_scrolling = self.is_scrolling()
        self.rects = layout
        n = len(layout)
        for i in list(self.visible_indices):
            if i >= n:
                self._recycle_widget(i)
                self.visible_indices.discard(i)
            elif i in self._additional_widgets:
                old_size = self._additional_widgets[i].size()
                new_size = layout[i].size()
                if old_size.width() < new_size.width() or old_size.height() < new_size.height():
                    plugin_name = self._notifier.plugin_name(i)
                    if plugin_name is not None:
                        instance = grid_resolver.registry.instance(plugin_name)
                        if isinstance(instance, _WidgetGridPlugin):
                            self._pipeline.schedule_render(
                                i, self.items.paths[i],
                                self._content_size(new_size), instance,
                            )
            elif i in self.widgets:
                self.widgets[i].setGeometry(layout[i])
                if self._needs_reload(self.widgets[i], layout[i].size()):
                    self._pipeline.schedule_render(
                        i, self.items.paths[i], self._content_size(layout[i].size()),
                    )
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
        self._prev_selection_set = set(self.items.selected_indices())
        index = self.get_restore_index()
        if index is None:
            index = 0
        elif index >= len(self.rects):
            index = 0
        self.scroll_to_index(index)
        if was_scrolling:
            self._start_auto_scroll_from_current()

    def set_pending_scroll_index(self, index):
        self._pending_scroll_index = index

    @profiler.profile
    def get_restore_index(self):
        if self._pending_scroll_index is not None:
            idx = self._pending_scroll_index
            self._pending_scroll_index = None
            return idx
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
        vp = self.viewport()
        if no_longer_visible:
            vp.setUpdatesEnabled(False)
            for i in no_longer_visible:
                self._recycle_widget(i)
            vp.setUpdatesEnabled(True)
        if newly_added:
            if isinstance(visible_range, range):
                center = (visible_range.start + visible_range.stop) // 2
            else:
                center = (min(visible_range) + max(visible_range)) // 2 if visible_range else 0
            sorted_added = sorted(newly_added, key=lambda i: abs(i - center))
            for i in sorted_added:
                if i < len(self.rects):
                    self._setup_cell(i)
        self.visible_indices = new_visible
        self._sync_additional_widgets()
        if self.rects:
            margin = self._half_pos
            if self._hz:
                new_rect = QtCore.QRectF(-margin, -margin, max(self.viewport().width(), 1), self.rects.total_extent + margin)
            else:
                new_rect = QtCore.QRectF(-margin, -margin, self.rects.total_extent + margin, max(self.viewport().height(), 1))
            if self._scene.sceneRect() != new_rect:
                self._scene.setSceneRect(new_rect)
        self._overlay.raise_()
        self.viewport().update()

    @profiler.profile
    def _calculate_visible_indices(self, view_rect):
        if not self.rects:
            return range(0, 0)
        hz = self._hz
        p_start = view_rect.top() if hz else view_rect.left()
        p_end = view_rect.bottom() if hz else view_rect.right()
        s_start = view_rect.left() if hz else view_rect.top()
        s_end = view_rect.right() if hz else view_rect.bottom()
        return self.rects.calculate_visible_indices(p_start, p_end, s_start, s_end)

    @profiler.profile
    def _expand_prefetch_range(self, visible):
        if not visible:
            return range(0, 0)
        if isinstance(visible, range):
            prefetch = len(visible) + 3
            start = max(0, visible.start - prefetch)
            end = min(len(self.rects), visible.stop + prefetch)
            return range(start, end)
        rects = self.rects
        view_rect = self._scene_view_rect()
        hz = self._hz
        margin = self.base_height * 2
        if hz:
            expanded = rects.calculate_visible_indices(
                view_rect.top() - margin, view_rect.bottom() + margin,
                view_rect.left(), view_rect.right(),
            )
        else:
            expanded = rects.calculate_visible_indices(
                view_rect.left() - margin, view_rect.right() + margin,
                view_rect.top(), view_rect.bottom(),
            )
        result = set(visible)
        result.update(expanded)
        return sorted(result)

    @profiler.profile
    def _setup_cell(self, i):
        rect = self.rects[i]
        if i >= len(self.items.paths):
            return
        if i in self._additional_widgets:
            return
        if i not in self.widgets:
            path = self.items.paths[i]
            item = self.pixmap_item_pool.acquire()
            item.setGeometry(rect)
            self.widgets[i] = item
            content_size = self._content_size(rect.size())
            cached = self.image_cache.get_if_sufficient(path, content_size)
            if cached is not None:
                item.set_image(cached, path)
            else:
                cached = self.image_cache.get(path)
                if cached is not None:
                    item.set_image(cached, path)
                self._pipeline.schedule_render(i, path, content_size)
        elif self.widgets[i].geometry() != rect:
            self.widgets[i].setGeometry(rect)

    @profiler.profile
    def _recycle_widget(self, i):
        if i in self._additional_widgets:
            widget = self._additional_widgets.pop(i)
            self._notifier.unbind(i, widget)
            self.additional_pool.release(widget)
        if i in self.widgets:
            item = self.widgets.pop(i)
            self.pixmap_item_pool.release(item)
        self._pipeline.cancel_index(i)

    @profiler.profile
    def _promote_to_widget(self, index, plugin_name):
        if index not in self.visible_indices:
            return
        if index in self._additional_widgets:
            return
        if index >= len(self.items.paths):
            return
        vp = self.viewport()
        vp.setUpdatesEnabled(False)
        widget = self.additional_pool.acquire(plugin_name, vp)
        if widget is None:
            vp.setUpdatesEnabled(True)
            return
        if index in self.widgets:
            self.pixmap_item_pool.release(self.widgets.pop(index))
        self._notifier.bind(index, plugin_name)
        self._additional_widgets[index] = widget
        self._sync_additional_widget(index)
        if index in self.items.selected_indices():
            self._notifier.select(index, widget)
        path = self.items.paths[index]
        cached = self.image_cache.get(path)
        if cached is not None:
            instance = grid_resolver.registry.instance(plugin_name)
            if isinstance(instance, _WidgetGridPlugin):
                instance.on_thumb_loaded(widget, cached)
        vp.setUpdatesEnabled(True)

    @profiler.profile
    def _sync_additional_widget(self, index, vp_rect=None):
        widget = self._additional_widgets.get(index)
        if widget is None:
            return
        if index >= len(self.rects):
            if widget.isVisible():
                widget.hide()
                self._notifier.disappear(index, widget)
            return
        scene_rect = self.rects[index]
        if vp_rect is None:
            vp_rect = self.viewport().rect()
        vp_point = self.mapFromScene(QtCore.QPointF(scene_rect.x(), scene_rect.y()))
        mapped = QtCore.QRect(
            int(vp_point.x()), int(vp_point.y()),
            scene_rect.width(), scene_rect.height(),
        )
        visible = mapped.intersects(vp_rect)
        was_visible = widget.isVisible()
        if not visible:
            if was_visible:
                widget.hide()
                self._notifier.disappear(index, widget)
            return
        current = widget.geometry()
        if current != mapped:
            if current.size() == mapped.size():
                widget.move(mapped.topLeft())
            else:
                widget.setGeometry(mapped)
        if not was_visible:
            widget.show()
            self._notifier.appear(index, widget)

    @profiler.profile
    def _sync_additional_widgets(self):
        if not self._additional_widgets:
            return
        vp_rect = self.viewport().rect()
        for idx in list(self._additional_widgets):
            self._sync_additional_widget(idx, vp_rect)
        self._overlay.raise_()
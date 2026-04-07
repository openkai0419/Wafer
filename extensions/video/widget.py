from PySide6.QtCore import Qt, Slot, Signal, QObject, QRect, QTimer
from PySide6.QtGui import QImage, QPainter, QCursor
from PySide6.QtWidgets import QWidget, QApplication
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from collections import OrderedDict
from wafer.core.qt.rate_limit import qt_debounce_manager
from wafer.utils.logs import AppLogger
from wafer.utils.profiling import profiler

DEFAULT_VOLUME = 40
GL_COLOR_BUFFER_BIT = 0x00004000
_MPV_EVENT_PLAYBACK_RESTART = 21


def _get_proc_address(_, name):
    from PySide6.QtGui import QOpenGLContext

    ctx = QOpenGLContext.currentContext()
    if ctx is None:
        return 0
    addr = ctx.getProcAddress(name)
    return int(addr) if addr else 0


class MpvGLOverlay(QOpenGLWidget):
    _mpv = None
    _proc_addr_cb = None
    _init_attempted = False

    _MPV_OPTIONS = dict(
        vo="libmpv",
        hwdec="auto",
        keep_open="yes",
        idle="yes",
        loop="inf",
        panscan=1.0,
        demuxer_max_back_bytes="128KiB",
        osd_level=0,
        sub="no",
        framedrop="vo",
        opengl_pbo="yes",
        vd_lavc_threads=2,
        demuxer_lavf_analyzeduration=0.1,
        demuxer_lavf_probesize=32768,
        video_latency_hacks="yes",
        hr_seek="no",
    )

    _on_update = Signal()

    @classmethod
    def _ensure_mpv(cls) -> bool:
        if cls._init_attempted:
            return cls._mpv is not None
        cls._init_attempted = True
        try:
            import mpv

            proc_addr_cb = mpv.MpvGlGetProcAddressFn(_get_proc_address)
            cls._mpv = mpv
            cls._proc_addr_cb = proc_addr_cb
            return True
        except (OSError, ImportError, AttributeError):
            cls._mpv = None
            return False

    @classmethod
    def _create_player(cls):
        if cls._mpv is None:
            return None
        player = cls._mpv.MPV(**cls._MPV_OPTIONS)
        player.volume = DEFAULT_VOLUME
        return player

    _on_playback_ready = Signal(int)

    @profiler.profile
    def __init__(self, parent=None, player=None):
        super().__init__(parent)
        self._ctx = None
        self._frame_ready = False
        self._playback_ready = False
        self._path = None
        self._owner = None
        self._play_generation = 0
        self._frame_generation = 0
        self._awaiting_first_frame = False
        self._on_update.connect(self._request_update, Qt.ConnectionType.QueuedConnection)
        self._on_playback_ready.connect(self._handle_playback_ready, Qt.ConnectionType.QueuedConnection)
        self.player = player if player is not None else (self._create_player() if self._mpv else None)
        if self.player:
            self.player.register_event_callback(self._on_mpv_event)

    def set_volume(self, volume: int):
        if self.player:
            self.player.volume = volume

    @profiler.profile
    def initializeGL(self):
        if self.player is None:
            return
        if self._ctx is not None:
            self._ctx.update_cb = None
            self._ctx.free()
            self._ctx = None
        try:
            self._ctx = self._mpv.MpvRenderContext(
                self.player,
                "opengl",
                opengl_init_params={"get_proc_address": self._proc_addr_cb},
            )
            self._ctx.update_cb = self._on_mpv_frame
        except Exception as e:
            AppLogger.error(f"MpvRenderContext creation failed: {e}", exc=e)
            self._ctx = None

    def _on_mpv_event(self, event):
        if event.event_id.value == _MPV_EVENT_PLAYBACK_RESTART:
            self._on_playback_ready.emit(self._play_generation)

    @Slot(int)
    def _handle_playback_ready(self, generation):
        if generation == self._play_generation:
            self._playback_ready = True
            if self._frame_ready:
                self._show_first_frame()

    def _on_mpv_frame(self):
        self._frame_generation = self._play_generation
        self._frame_ready = True
        self._on_update.emit()

    @profiler.profile
    def _show_first_frame(self):
        if self._awaiting_first_frame:
            self._awaiting_first_frame = False
            gen = self._play_generation
            QTimer.singleShot(0, lambda: self._deferred_show(gen))

    def _deferred_show(self, generation):
        if generation != self._play_generation:
            return
        if not self.isVisible():
            self.show()
        self.update()

    @Slot()
    def _request_update(self):
        if not self._frame_ready:
            return
        if self._frame_generation != self._play_generation:
            self._frame_ready = False
            return
        if self._awaiting_first_frame:
            if self._playback_ready:
                self._show_first_frame()
            return
        if self.isVisible():
            self.update()

    def _clear_gl(self):
        f = self.context().functions()
        f.glClearColor(0.0, 0.0, 0.0, 1.0)
        f.glClear(GL_COLOR_BUFFER_BIT)

    @profiler.profile
    def paintGL(self):
        if self._ctx is None:
            return
        if self._awaiting_first_frame:
            self._clear_gl()
            return
        self._frame_ready = False
        ratio = self.devicePixelRatioF()
        w = int(self.width() * ratio)
        h = int(self.height() * ratio)
        fbo = self.defaultFramebufferObject()
        self._ctx.render(
            opengl_fbo={"w": w, "h": h, "fbo": fbo},
            flip_y=True,
        )

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._owner is not None:
            MpvCellWidget._on_overlay_leave(self._owner)

    @profiler.profile
    def activate(self, path, owner=None):
        self._owner = owner
        self._path = path
        self._play_generation += 1
        self._awaiting_first_frame = True
        self._frame_ready = False
        self._playback_ready = False
        self.hide()
        if owner is not None:
            self.setParent(owner)
            self.setGeometry(0, 0, owner.width(), owner.height())
        if self._ctx is None:
            self.show()
            self.raise_()
        if self.player:
            generation = self._play_generation
            QTimer.singleShot(0, lambda: self._deferred_play(path, generation))

    @profiler.profile
    def _deferred_play(self, path, generation):
        if generation != self._play_generation or self.player is None:
            return
        self.player.command_async("loadfile", path)

    @profiler.profile
    def deactivate(self):
        self._owner = None
        self._play_generation += 1
        self._awaiting_first_frame = False
        self._playback_ready = False
        if self.player:
            self.player.command_async("stop")
        self._path = None
        self._frame_ready = False
        self.hide()

    @profiler.profile
    def cleanup(self):
        self._play_generation += 1
        if self._ctx:
            self._ctx.update_cb = None
            self._ctx.free()
            self._ctx = None
        if self.player:
            self.player.unregister_event_callback(self._on_mpv_event)
            self.player.terminate()
            self.player = None


class PlaybackSlotManager:
    HOVER_DEBOUNCE_MS = 150
    PLAYER_POOL_TARGET = 2

    def __init__(self, parent, max_selected=3, max_appeared=6):
        self._parent = parent
        self._max_selected = max_selected
        self._max_appeared = max_appeared
        self.volume = DEFAULT_VOLUME
        self.hover_autoplay = True
        self.appear_autoplay = False
        self.select_autoplay = True
        self.pause_in_background = False
        self._paused_by_background = False
        self._mpv_available = MpvGLOverlay._ensure_mpv()
        self._pool: list[MpvGLOverlay] = []
        self._player_pool: list = []
        self._warming_count = 0
        self._warm_cancel = None
        self._dispatcher = None
        self._appeared_cells: set = set()
        self._appeared: OrderedDict = OrderedDict()
        self._selected: OrderedDict = OrderedDict()
        self._hover_cell = None
        self._hover_overlay: MpvGLOverlay | None = None
        self._pending_hover_cell = None
        self._pending_hover_path = None
        self._appear_queue: list[tuple] = []
        self._appear_flushing = False
        self._debounce_key = f"PlaybackSlotManager.hover.{id(self)}"
        if self._mpv_available:
            from wafer.core.qt.dispatcher import Dispatcher, CancelToken
            from wafer.core.qt.thread import utility_pool

            self._dispatcher = Dispatcher(pool=utility_pool)
            self._warm_cancel = CancelToken()
            overlay = MpvGLOverlay(parent)
            overlay.hide()
            self._pool.append(overlay)
            self._warm_players()

        app = QApplication.instance()
        if app:
            app.applicationStateChanged.connect(self._on_app_state_changed)

    def set_volume(self, volume: int):
        self.volume = max(0, min(100, int(volume)))
        for overlay in self._pool:
            overlay.set_volume(self.volume)
        if self._hover_overlay is not None:
            self._hover_overlay.set_volume(self.volume)
        for overlay in self._selected.values():
            overlay.set_volume(self.volume)

    def set_max_selected(self, count: int):
        self._max_selected = max(1, count)
        while len(self._selected) > self._max_selected:
            _, evicted = self._selected.popitem(last=False)
            self._release_overlay(evicted)

    def _on_app_state_changed(self, state):
        if state != Qt.ApplicationState.ApplicationActive:
            if self.pause_in_background and not self._paused_by_background:
                self._paused_by_background = True
                for overlay in self._iter_active_overlays():
                    if overlay.player:
                        overlay.player.pause = True
        else:
            if self._paused_by_background:
                self._paused_by_background = False
                for overlay in self._iter_active_overlays():
                    if overlay.player:
                        overlay.player.pause = False

    def _iter_active_overlays(self):
        if self._hover_overlay is not None:
            yield self._hover_overlay
        yield from self._selected.values()
        yield from self._appeared.values()

    def _warm_players(self):
        if self._dispatcher is None:
            return
        while self._warming_count + len(self._player_pool) < self.PLAYER_POOL_TARGET:
            self._warming_count += 1
            self._dispatcher.post(self._bg_create_player, cancel=self._warm_cancel)

    def _bg_create_player(self):
        try:
            player = MpvGLOverlay._create_player()
        except Exception:
            player = None
        self._dispatcher.invoke(lambda p=player: self._on_player_warmed(p))

    def _on_player_warmed(self, player):
        self._warming_count -= 1
        if self._warm_cancel and self._warm_cancel.is_cancelled():
            if player is not None:
                player.terminate()
            return
        if player is not None:
            self._player_pool.append(player)

    def _is_in_use(self, overlay) -> bool:
        if overlay is self._hover_overlay:
            return True
        for v in self._selected.values():
            if v is overlay:
                return True
        return any(v is overlay for v in self._appeared.values())

    @profiler.profile
    def _acquire(self) -> MpvGLOverlay | None:
        if not self._mpv_available:
            return None
        while self._pool:
            overlay = self._pool.pop()
            if not self._is_in_use(overlay):
                return overlay
        player = self._player_pool.pop() if self._player_pool else None
        overlay = MpvGLOverlay(self._parent, player=player)
        overlay.set_volume(self.volume)
        overlay.hide()
        self._warm_players()
        return overlay

    @profiler.profile
    def _release_overlay(self, overlay):
        overlay.deactivate()
        overlay.setParent(self._parent)
        if overlay not in self._pool:
            self._pool.append(overlay)

    def _cancel_pending(self):
        qt_debounce_manager.cancel(self._debounce_key)
        self._pending_hover_cell = None
        self._pending_hover_path = None

    @profiler.profile
    def activate_hover(self, cell, path):
        if cell in self._selected or cell in self._appeared_cells:
            return
        if self._hover_cell is cell:
            return
        if self._pending_hover_cell is cell:
            return
        self.deactivate_hover()
        self._pending_hover_cell = cell
        self._pending_hover_path = path
        qt_debounce_manager.debounce(self._debounce_key, self.HOVER_DEBOUNCE_MS, self._apply_hover)

    @profiler.profile
    def _apply_hover(self):
        cell = self._pending_hover_cell
        path = self._pending_hover_path
        self._pending_hover_cell = None
        self._pending_hover_path = None
        if cell is None or path is None:
            return
        if cell in self._selected or cell in self._appeared_cells:
            return
        overlay = self._acquire()
        if overlay is None:
            return
        self._hover_cell = cell
        self._hover_overlay = overlay
        overlay.activate(path, owner=cell)

    @profiler.profile
    def deactivate_hover(self):
        self._cancel_pending()
        overlay = self._hover_overlay
        self._hover_cell = None
        self._hover_overlay = None
        if overlay is not None:
            self._release_overlay(overlay)

    @profiler.profile
    def activate_select(self, cell, path):
        if cell in self._selected:
            return
        if self._pending_hover_cell is cell:
            self._cancel_pending()
        overlay = self._appeared.pop(cell, None)
        if overlay is not None:
            pass
        elif self._hover_cell is cell and self._hover_overlay is not None:
            overlay = self._hover_overlay
            self._hover_cell = None
            self._hover_overlay = None
            if not overlay.isVisible() or overlay._path != path:
                overlay.activate(path, owner=cell)
        else:
            overlay = self._acquire()
            if overlay is None:
                return
            overlay.activate(path, owner=cell)
        while len(self._selected) >= self._max_selected:
            _, evicted = self._selected.popitem(last=False)
            self._release_overlay(evicted)
        self._selected[cell] = overlay

    @profiler.profile
    def deactivate_select(self, cell):
        overlay = self._selected.pop(cell, None)
        if overlay is not None:
            if cell in self._appeared_cells:
                self._appeared[cell] = overlay
            else:
                self._release_overlay(overlay)

    def is_selected(self, cell) -> bool:
        return cell in self._selected

    def is_appeared(self, cell) -> bool:
        return cell in self._appeared_cells

    def overlay_for(self, cell) -> MpvGLOverlay | None:
        if cell in self._selected:
            return self._selected[cell]
        if cell in self._appeared:
            return self._appeared[cell]
        if self._hover_cell is cell:
            return self._hover_overlay
        return None

    def is_hovering(self, cell) -> bool:
        return self._hover_cell is cell or self._pending_hover_cell is cell

    def on_overlay_leave(self, cell):
        if cell in self._selected or cell in self._appeared_cells:
            return
        if self._hover_cell is cell:
            self.deactivate_hover()

    def resize_overlay(self, cell):
        overlay = self.overlay_for(cell)
        if overlay is not None:
            overlay.setGeometry(0, 0, cell.width(), cell.height())

    @profiler.profile
    def activate_appear(self, cell, path):
        if cell in self._appeared_cells:
            return
        self._appeared_cells.add(cell)
        if cell in self._selected:
            return
        self._appear_queue.append((cell, path))
        if not self._appear_flushing:
            self._appear_flushing = True
            QTimer.singleShot(0, self._flush_appear_queue)

    def _flush_appear_queue(self):
        if not self._appear_queue:
            self._appear_flushing = False
            return
        cell, path = self._appear_queue.pop(0)
        if cell not in self._appeared_cells or cell in self._selected:
            if self._appear_queue:
                QTimer.singleShot(0, self._flush_appear_queue)
            else:
                self._appear_flushing = False
            return
        self._activate_appear_overlay(cell, path)
        if self._appear_queue:
            QTimer.singleShot(0, self._flush_appear_queue)
        else:
            self._appear_flushing = False

    @profiler.profile
    def _activate_appear_overlay(self, cell, path):
        if self._pending_hover_cell is cell:
            self._cancel_pending()
        if self._hover_cell is cell and self._hover_overlay is not None:
            overlay = self._hover_overlay
            self._hover_cell = None
            self._hover_overlay = None
            if not overlay.isVisible() or overlay._path != path:
                overlay.activate(path, owner=cell)
        else:
            overlay = self._acquire()
            if overlay is None:
                return
            overlay.activate(path, owner=cell)
        while len(self._appeared) >= self._max_appeared:
            _, evicted = self._appeared.popitem(last=False)
            if evicted is not None:
                self._release_overlay(evicted)
        self._appeared[cell] = overlay

    @profiler.profile
    def deactivate_appear(self, cell):
        self._appeared_cells.discard(cell)
        self._appear_queue = [(c, p) for c, p in self._appear_queue if c is not cell]
        overlay = self._appeared.pop(cell, None)
        if overlay is not None:
            if cell not in self._selected:
                self._release_overlay(overlay)

    @profiler.profile
    def release_cell(self, cell):
        self.deactivate_select(cell)
        self.deactivate_appear(cell)
        if self._hover_cell is cell or self._pending_hover_cell is cell:
            self.deactivate_hover()

    @profiler.profile
    def cleanup(self):
        if self._warm_cancel:
            self._warm_cancel.cancel()
        self._cancel_pending()
        self._appear_queue.clear()
        self._appear_flushing = False
        self.deactivate_hover()
        for overlay in list(self._selected.values()):
            overlay.deactivate()
            overlay.cleanup()
        self._selected.clear()
        for overlay in list(self._appeared.values()):
            overlay.deactivate()
            overlay.cleanup()
        self._appeared.clear()
        self._appeared_cells.clear()
        for overlay in self._pool:
            overlay.cleanup()
        self._pool.clear()
        for player in self._player_pool:
            player.terminate()
        self._player_pool.clear()
        self._warming_count = 0


class MpvCellWidget(QWidget):
    _slot_manager: PlaybackSlotManager | None = None
    _shared_initialized = False
    _pending_grid_state: dict | None = None

    @classmethod
    def _init_shared(cls, parent):
        if cls._shared_initialized:
            return
        cls._shared_initialized = True
        cls._slot_manager = PlaybackSlotManager(parent)
        from wafer.core.commands.bridge import UI

        UI.register_instance("VideoSlotManager", cls._slot_manager)
        if cls._pending_grid_state is not None:
            from .grid import VideoGridPlugin

            VideoGridPlugin._apply_state(cls._slot_manager, cls._pending_grid_state)
            cls._pending_grid_state = None
        else:
            from wafer.core.commands.bridge import Command

            Command.set_checked("vgrid.toggle_hover_autoplay", cls._slot_manager.hover_autoplay)
            Command.set_checked("vgrid.toggle_appear_autoplay", cls._slot_manager.appear_autoplay)
            Command.set_checked("vgrid.toggle_select_autoplay", cls._slot_manager.select_autoplay)
            Command.set_checked("vgrid.toggle_pause_in_background", cls._slot_manager.pause_in_background)

    @classmethod
    def _on_overlay_leave(cls, cell):
        if cls._slot_manager is not None:
            cls._slot_manager.on_overlay_leave(cell)

    @profiler.profile
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)
        self._path = None
        self._thumbnail = None
        self._init_shared(parent)

    @profiler.profile
    def load(self, path, size=None):
        if self._path != path:
            self._thumbnail = None
        self._path = path
        self.update()

    def set_thumbnail(self, image):
        self._thumbnail = image
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._thumbnail and not self._thumbnail.isNull():
            ww, wh = self.width(), self.height()
            iw, ih = self._thumbnail.width(), self._thumbnail.height()
            if iw > 0 and ih > 0 and ww > 0 and wh > 0:
                scale = max(ww / iw, wh / ih)
                src_w = ww / scale
                src_h = wh / scale
                sx = (iw - src_w) / 2
                sy = (ih - src_h) / 2
                painter.fillRect(self.rect(), Qt.GlobalColor.black)
                painter.drawImage(
                    self.rect(),
                    self._thumbnail,
                    QRect(int(sx), int(sy), int(src_w), int(src_h)),
                )
            else:
                painter.drawImage(self.rect(), self._thumbnail)
        else:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)

    @profiler.profile
    def enterEvent(self, event):
        super().enterEvent(event)
        if self._path and self._slot_manager and self._slot_manager.hover_autoplay:
            self._slot_manager.activate_hover(self, self._path)

    @profiler.profile
    def leaveEvent(self, event):
        super().leaveEvent(event)
        if not self._slot_manager:
            return
        if self._slot_manager.is_selected(self):
            return
        overlay = self._slot_manager.overlay_for(self)
        if overlay and overlay.isVisible():
            local = self.mapFromGlobal(QCursor.pos())
            if overlay.geometry().contains(local):
                return
        self._slot_manager.deactivate_hover()

    @profiler.profile
    def moveEvent(self, event):
        super().moveEvent(event)
        if not self._slot_manager or not self._path or not self.isVisible():
            return
        if self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            self._slot_manager.activate_hover(self, self._path)
        elif self._slot_manager.is_hovering(self):
            self._slot_manager.deactivate_hover()

    @profiler.profile
    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._slot_manager:
            self._slot_manager.resize_overlay(self)

    @profiler.profile
    def on_appeared(self):
        if self._slot_manager and self._path and self._slot_manager.appear_autoplay:
            self._slot_manager.activate_appear(self, self._path)

    @profiler.profile
    def on_disappeared(self):
        if self._slot_manager:
            self._slot_manager.deactivate_appear(self)

    @profiler.profile
    def on_selected(self):
        if self._slot_manager and self._path and self._slot_manager.select_autoplay:
            self._slot_manager.activate_select(self, self._path)

    @profiler.profile
    def on_deselected(self):
        if self._slot_manager:
            self._slot_manager.deactivate_select(self)

    @profiler.profile
    def suspend(self):
        if self._slot_manager:
            self._slot_manager.release_cell(self)
        self._path = None
        self._thumbnail = None

    @profiler.profile
    def resume(self):
        pass

    @profiler.profile
    def cleanup(self):
        self.suspend()

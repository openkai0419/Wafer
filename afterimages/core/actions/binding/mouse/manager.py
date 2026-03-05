from PySide6 import QtCore, QtGui, QtWidgets

from ...command.core import CommandRegistry
from ...command.context import CommandContext
from afterimages.utils.logs import AppLogger
from .types import ClickType, MouseButton, ModifierKey, MouseActionKey
from .drag import DragContext, CommandDragContext, ExternalDropDynamicContext


class MouseStateManager:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        self._press_positions = {}
        self._double_click_buttons = {}
        self._suppress_buttons = set()
        self._drag_threshold = QtWidgets.QApplication.startDragDistance()
        self._processed_events = set()
        self._last_cleanup_time = QtCore.QTime.currentTime()
        self._internal_drag_contexts = {}
        self._external_drag_contexts = {}

    def _cleanup_old_events(self):
        current = QtCore.QTime.currentTime()
        if self._last_cleanup_time.msecsTo(current) > 10000:
            self._processed_events.clear()
            self._last_cleanup_time = current

    def is_event_processed(self, event):
        self._cleanup_old_events()
        timestamp = getattr(event, 'timestamp', None)
        if callable(timestamp):
            ts = timestamp()
        else:
            return False
        event_signature = (event.type(), ts)
        if event_signature in self._processed_events:
            return True
        self._processed_events.add(event_signature)
        return False

    def set_press_position(self, widget, pos):
        self._press_positions[id(widget)] = pos

    def get_press_position(self, widget):
        return self._press_positions.get(id(widget))

    def clear_press_position(self, widget):
        self._press_positions.pop(id(widget), None)

    def set_double_click_button(self, widget, button):
        self._double_click_buttons[id(widget)] = button

    def get_double_click_button(self, widget):
        return self._double_click_buttons.get(id(widget))

    def clear_double_click_button(self, widget):
        self._double_click_buttons.pop(id(widget), None)

    def check_drag_threshold(self, start_pos, current_pos):
        return (current_pos - start_pos).manhattanLength() >= self._drag_threshold

    def should_suppress_single(self, button):
        if button in self._suppress_buttons:
            self._suppress_buttons.discard(button)
            return True
        return False

    def add_suppress_group(self, buttons):
        if not buttons:
            return
        for b in buttons:
            self._suppress_buttons.add(b)

    def clear_suppress_groups(self):
        self._suppress_buttons.clear()

    def start_internal_drag(self, widget, context):
        self._internal_drag_contexts[id(widget)] = context

    def get_internal_drag_context(self, widget):
        return self._internal_drag_contexts.get(id(widget))

    def end_internal_drag(self, widget):
        return self._internal_drag_contexts.pop(id(widget), None)

    def start_external_drag(self, widget, context):
        self._external_drag_contexts[id(widget)] = context

    def get_external_drag_context(self, widget):
        return self._external_drag_contexts.get(id(widget))

    def end_external_drag(self, widget):
        return self._external_drag_contexts.pop(id(widget), None)


class MouseEventManager:

    def __init__(self):
        self._bindings = {}
        self._resolver = None
        self._state = MouseStateManager.instance()
        self._registry = None

    def set_registry(self, registry):
        self._registry = registry

    def bind(self, key, action):
        self._bindings[key] = action

    def clear(self):
        self._bindings.clear()
        self._resolver = None

    def set_resolver(self, resolver):
        self._resolver = resolver

    def execute_action(self, key, *args, **kwargs):
        if key.click_type == ClickType.SINGLE and not key.held_buttons:
            if self._state.should_suppress_single(key.button):
                return False
        action = self._bindings.get(key)
        handled = False
        result = None
        if action:
            result = action(*args, **kwargs)
            handled = True
        elif self._resolver:
            try:
                result = self._resolver(key, *args, **kwargs)
                handled = bool(result)
            except Exception as e:
                AppLogger.warning(f"Mouse resolver failed: {key}", exc=e)
                handled = False
        if handled:
            if key.held_buttons:
                self._state.add_suppress_group(list(key.held_buttons))
            event = args[0] if args else None
            if event is not None and hasattr(event, 'accept'):
                event.accept()
        return result

    def execute_drag_start(self, key, event, widget):
        if self._registry:
            from ..mixins import CommandBindingMixin
            if isinstance(widget, CommandBindingMixin):
                bindings = widget.get_mouse_bindings()
                payload = bindings.get(key)
                if payload:
                    base_id = payload.id
                    args = payload.args or {}
                    ctx = CommandDragContext(base_id, self._registry, widget, args)
                    cmd_class = self._registry.get_command(base_id)
                    meta = cmd_class.meta if cmd_class else None
                    if meta and "start" in (meta.drag_callbacks or {}):
                        cctx = CommandContext.create(widget, None, source="drag", event=event)
                        cctx.put("phase", "start")
                        self._registry.execute(base_id, ctx=cctx, **args)
                    return ctx
        result = self.execute_action(key, event)
        if isinstance(result, DragContext):
            return result
        return None

    @staticmethod
    def map_qt_button(qt_button):
        for b in MouseButton:
            if b.value == qt_button:
                return b
        return MouseButton.NONE

    @staticmethod
    def _qt_modifiers_for_event(event):
        m = getattr(event, "modifiers", None)
        if callable(m):
            try:
                return m()
            except Exception as e:
                AppLogger.warning("event.modifiers() failed", exc=e)
                return QtCore.Qt.NoModifier
        km = getattr(event, "keyboardModifiers", None)
        if callable(km):
            try:
                return km()
            except Exception as e:
                AppLogger.warning("event.keyboardModifiers() failed", exc=e)
                return QtCore.Qt.NoModifier
        return QtCore.Qt.NoModifier

    @staticmethod
    def get_modifiers(modifiers):
        r = []
        try:
            if modifiers & QtCore.Qt.ControlModifier:
                r.append(ModifierKey.CTRL)
            if modifiers & QtCore.Qt.ShiftModifier:
                r.append(ModifierKey.SHIFT)
            if modifiers & QtCore.Qt.AltModifier:
                r.append(ModifierKey.ALT)
            if modifiers & QtCore.Qt.MetaModifier:
                r.append(ModifierKey.META)
        except Exception as e:
            AppLogger.warning("MouseEventManager.get_modifiers failed", exc=e)
            return tuple()
        return tuple(r)

    @staticmethod
    def get_held_buttons(buttons, exclude=None):
        btns = []
        for qt_btn in [QtCore.Qt.LeftButton, QtCore.Qt.RightButton, QtCore.Qt.MiddleButton, QtCore.Qt.XButton1, QtCore.Qt.XButton2]:
            if buttons & qt_btn:
                mapped = MouseEventManager.map_qt_button(qt_btn)
                if mapped != exclude:
                    btns.append(mapped)
        return tuple(btns)

    @staticmethod
    def _make_click_key(event, is_double: bool) -> MouseActionKey:
        button = MouseEventManager.map_qt_button(event.button())
        held = MouseEventManager.get_held_buttons(event.buttons(), exclude=button)
        click_type = ClickType.DOUBLE if is_double else ClickType.SINGLE
        mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
        return MouseActionKey(button, click_type, held, mods)


class MouseEventDispatcher(QtCore.QObject):

    def __init__(self, target_widget, mouse_event_manager, enable_drag=True, use_existing_events: bool | None = None):
        super().__init__(target_widget)
        self._manager = mouse_event_manager
        self._target = target_widget
        self._watch_targets = self._collect_watch_targets(target_widget)
        self._watch_target_ids = {id(w) for w in self._watch_targets}
        self._state = MouseStateManager.instance()
        self._enable_drag = enable_drag
        self._use_existing_events = use_existing_events
        if enable_drag:
            for w in self._watch_targets:
                try:
                    w.setAcceptDrops(True)
                except Exception as e:
                    AppLogger.warning(f"setAcceptDrops failed for {type(w).__name__}", exc=e)
        for w in self._watch_targets:
            try:
                w.installEventFilter(self)
            except Exception as e:
                AppLogger.warning(f"installEventFilter failed for {type(w).__name__}", exc=e)
        self._dragging_button = None

    @staticmethod
    def _collect_watch_targets(widget):
        ws = []
        if widget is not None:
            ws.append(widget)
        vp = None
        try:
            vpf = getattr(widget, "viewport", None)
            vp = vpf() if callable(vpf) else None
        except Exception as e:
            AppLogger.debug(f"viewport() access failed for {type(widget).__name__}: {e}")
            vp = None
        if vp is not None and vp is not widget:
            ws.append(vp)
        out = []
        seen = set()
        for w in ws:
            if w is None:
                continue
            i = id(w)
            if i in seen:
                continue
            seen.add(i)
            out.append(w)
        return out

    def _event_pos_in_target(self, event):
        gp = self._get_global_pos(event)
        if gp is not None and hasattr(self._target, "mapFromGlobal"):
            try:
                return self._target.mapFromGlobal(gp)
            except Exception as e:
                AppLogger.debug(f"mapFromGlobal failed: {e}")
        try:
            return event.pos()
        except Exception as e:
            AppLogger.debug(f"event.pos() failed: {e}")
            return QtCore.QPoint()

    def _get_global_pos(self, event):
        gp = getattr(event, "globalPosition", None)
        if callable(gp):
            return gp().toPoint()
        return getattr(event, "globalPos", lambda: QtCore.QPoint())()

    def _handle_mouse_press(self, event):
        if self._state.is_event_processed(event):
            return
        self._state.set_press_position(self._target, self._event_pos_in_target(event))
        self._dragging_button = MouseEventManager.map_qt_button(event.button())

    def _handle_mouse_move(self, event):
        if self._state.is_event_processed(event):
            return

        ctx = self._state.get_internal_drag_context(self._target)

        if ctx is not None:
            if not ctx.cancelled:
                ctx.on_move(event)
        else:
            press_pos = self._state.get_press_position(self._target)
            if press_pos is not None and self._dragging_button is not None:
                pos = self._event_pos_in_target(event)
                if self._state.check_drag_threshold(press_pos, pos):
                    held = MouseEventManager.get_held_buttons(event.buttons(), exclude=self._dragging_button)
                    mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
                    key = MouseActionKey(self._dragging_button, ClickType.DRAG_START, held, mods)
                    ctx = self._manager.execute_drag_start(key, event, self._target)
                    if ctx:
                        self._state.start_internal_drag(self._target, ctx)
                        if not ctx.cancelled:
                            ctx.on_move(event)
                    self._state.clear_press_position(self._target)

    def _handle_double_click(self, event):
        if self._state.is_event_processed(event):
            return
        try:
            from ..manager import BindingManager
            gpt = self._get_global_pos(event)
            candidate = BindingManager.instance().find_binding_widget_at(gpt)
            if candidate == self._target:
                self._state.set_double_click_button(self._target, event.button())
        except Exception as e:
            AppLogger.warning("double click detection failed", exc=e)

    def _find_target_widget(self, event):
        try:
            from ..manager import BindingManager
            gpt = self._get_global_pos(event)
            return BindingManager.instance().find_binding_widget_at(gpt)
        except Exception as e:
            AppLogger.warning("find_binding_widget_at failed", exc=e)
            return None

    def _handle_mouse_release(self, event):
        if self._state.is_event_processed(event):
            return

        ctx = self._state.get_internal_drag_context(self._target)
        if ctx is not None:
            if not ctx.cancelled:
                released = MouseEventManager.map_qt_button(event.button())
                held = MouseEventManager.get_held_buttons(event.buttons(), exclude=released)
                if held:
                    self._state.add_suppress_group(held)
                ctx.on_end(event)
            self._state.end_internal_drag(self._target)
            self._state.clear_press_position(self._target)
            self._dragging_button = None
            return

        target_widget = self._find_target_widget(event)
        if target_widget is None or not hasattr(target_widget, "_mouse_manager"):
            self._state.clear_press_position(self._target)
            self._state.clear_double_click_button(self._target)
            self._dragging_button = None
            return
        is_double = self._state.get_double_click_button(target_widget) == event.button()
        if is_double:
            self._state.clear_double_click_button(target_widget)
        if target_widget is not self._target:
            lpt = target_widget.mapFromGlobal(self._get_global_pos(event))
            try:
                nev = QtGui.QMouseEvent(event.type(), QtCore.QPointF(lpt), event.button(), event.buttons(), event.modifiers())
            except TypeError:
                gpt = self._get_global_pos(event)
                nev = QtGui.QMouseEvent(event.type(), QtCore.QPointF(lpt), QtCore.QPointF(lpt), QtCore.QPointF(gpt), event.button(), event.buttons(), event.modifiers())
            key = MouseEventManager._make_click_key(nev, is_double)
            target_widget._mouse_manager.execute_action(key, nev)
        else:
            key = MouseEventManager._make_click_key(event, is_double)
            self._manager.execute_action(key, event)
        self._state.clear_press_position(self._target)
        self._dragging_button = None

    def _handle_wheel(self, event) -> bool:
        if self._state.is_event_processed(event):
            return False
        steps, click_type = self._normalize_wheel_steps(event)
        if steps <= 0:
            return False
        held = MouseEventManager.get_held_buttons(event.buttons())
        mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
        key = MouseActionKey(MouseButton.NONE, click_type, held, mods)
        payload = None
        try:
            if hasattr(self._target, "get_mouse_bindings") and callable(getattr(self._target, "get_mouse_bindings")):
                payload = self._target.get_mouse_bindings().get(key)
        except Exception as e:
            AppLogger.warning("get_mouse_bindings() failed for wheel event", exc=e)
            payload = None
        if payload is None:
            try:
                from .store import MouseBindingStore

                scope = self._target.binding_scope() if hasattr(self._target, "binding_scope") else "*"
                payload = MouseBindingStore.instance().resolve(scope, key)
            except Exception as e:
                AppLogger.warning("MouseBindingStore.resolve failed for wheel event", exc=e)
                payload = None
        if payload is None:
            return False
        self._manager.execute_action(key, event)
        return True

    @staticmethod
    def _normalize_wheel_steps(event) -> tuple[int, ClickType]:
        ay = 0
        ad = getattr(event, "angleDelta", None)
        if callable(ad):
            try:
                ay = int(ad().y())
            except Exception as e:
                AppLogger.debug(f"angleDelta().y() failed: {e}")
                ay = 0
        if ay:
            click_type = ClickType.WHEEL_UP if ay > 0 else ClickType.WHEEL_DOWN
            a = abs(ay)
            steps = max(1, int((a + 60) // 120))
            return steps, click_type
        py = 0
        pd = getattr(event, "pixelDelta", None)
        if callable(pd):
            try:
                py = int(pd().y())
            except Exception as e:
                AppLogger.debug(f"pixelDelta().y() failed: {e}")
                py = 0
        if py:
            click_type = ClickType.WHEEL_UP if py > 0 else ClickType.WHEEL_DOWN
            p = abs(py)
            steps = max(1, int((p + 50) // 100))
            return steps, click_type
        return 0, ClickType.WHEEL_UP

    def _handle_drop(self, event):
        if self._state.is_event_processed(event):
            return
        from ..mixins import CommandBindingMixin
        if not isinstance(self._target, CommandBindingMixin) or not self._target.drop_accept(event):
            event.ignore()
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            executed = bool(ctx.on_drop(event))
            self._state.end_external_drag(self._target)
            if executed:
                event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
                event.accept()
            else:
                event.ignore()
            return
        else:
            mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
            key = MouseActionKey(MouseButton.NONE, ClickType.DROP, frozenset(), mods)
            widget = self._target
            if isinstance(widget, CommandBindingMixin):
                bindings = widget.get_mouse_bindings()
                payload = bindings.get(key)
                if payload:
                    base_id = payload.id
                    args = payload.args or {}
                    registry = CommandRegistry.instance()
                    cmd_class = registry.get_command(base_id)
                    meta = cmd_class.meta if cmd_class else None
                    if meta and "drop" in (meta.drop_callbacks or {}):
                        ctx = CommandContext.create(widget, None, source="drop", event=event)
                        ctx.put("phase", "drop")
                        registry.execute(base_id, ctx=ctx, **args)
                        event.accept()
                        return
            executed = bool(self._manager.execute_action(key, event))
            if executed:
                event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
                event.accept()
            else:
                event.ignore()

    def _resolve_drop_payload(self, event):
        mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
        key = MouseActionKey(MouseButton.NONE, ClickType.DROP, (), mods)
        payload = None
        if hasattr(self._target, "get_mouse_bindings") and callable(getattr(self._target, "get_mouse_bindings")):
            try:
                payload = self._target.get_mouse_bindings().get(key)
            except Exception as e:
                AppLogger.warning("get_mouse_bindings() failed", exc=e)
        if payload is None:
            try:
                from .store import MouseBindingStore
                store = MouseBindingStore.instance()
                scope = self._target.binding_scope() if hasattr(self._target, "binding_scope") else "*"
                payload = store.resolve(scope, key)
            except Exception as e:
                AppLogger.warning("MouseBindingStore.resolve failed", exc=e)
        return payload, key

    def _handle_drag_enter(self, event):
        if self._state.is_event_processed(event):
            return
        from ..mixins import CommandBindingMixin
        if not isinstance(self._target, CommandBindingMixin) or not self._target.drop_accept(event):
            event.ignore()
            return

        payload, _ = self._resolve_drop_payload(event)
        if payload is None:
            event.ignore()
            return
        base_id = getattr(payload, "id", None)
        cmd_class = CommandRegistry.instance().get_command(base_id) if base_id else None
        meta = cmd_class.meta if cmd_class else None
        callbacks = (meta.drop_callbacks or {}) if meta else {}
        if not callbacks or "drop" not in callbacks:
            event.ignore()
            return
        ctx = None
        executed = False
        try:
            ctx = ExternalDropDynamicContext(self._target, CommandRegistry.instance(), self._resolve_drop_payload)
            executed = bool(ctx.on_enter(event))
        except Exception as e:
            AppLogger.warning("ExternalDropDynamicContext.on_enter failed", exc=e)
            ctx = None
        if ctx is None:
            event.ignore()
            return
        self._state.start_external_drag(self._target, ctx)
        event.accept() if executed else event.ignore()

    def _handle_drag_move(self, event):
        if self._state.is_event_processed(event):
            return
        from ..mixins import CommandBindingMixin
        if not isinstance(self._target, CommandBindingMixin) or not self._target.drop_accept(event):
            ctx = self._state.get_external_drag_context(self._target)
            if ctx:
                try:
                    ctx.on_leave(event)
                except Exception as e:
                    AppLogger.warning("ctx.on_leave failed during drag_move", exc=e)
                self._state.end_external_drag(self._target)
            event.ignore()
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            executed = bool(ctx.on_move(event))
            event.accept() if executed else event.ignore()
        else:
            event.ignore()

    def _handle_drag_leave(self, event):
        if self._state.is_event_processed(event):
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            ctx.on_leave(event)
            self._state.end_external_drag(self._target)

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        watch_ids = getattr(self, "_watch_target_ids", None)
        if not watch_ids or watched is None or id(watched) not in watch_ids:
            return super().eventFilter(watched, event)
        if isinstance(event, QtGui.QMouseEvent):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self._handle_mouse_press(event)
            elif event.type() == QtCore.QEvent.MouseMove:
                self._handle_mouse_move(event)
            elif event.type() == QtCore.QEvent.MouseButtonDblClick:
                self._handle_double_click(event)
            elif event.type() == QtCore.QEvent.MouseButtonRelease:
                self._handle_mouse_release(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
        elif isinstance(event, QtGui.QWheelEvent):
            handled = self._handle_wheel(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
            if handled:
                return True
        elif event.type() == QtCore.QEvent.DragEnter:
            self._handle_drag_enter(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
            return True
        elif event.type() == QtCore.QEvent.DragMove:
            self._handle_drag_move(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
            return True
        elif event.type() == QtCore.QEvent.DragLeave:
            self._handle_drag_leave(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
            return True
        elif event.type() == QtCore.QEvent.Drop:
            self._handle_drop(event)
            if self._use_existing_events is not None:
                return not self._use_existing_events
            return True
        return super().eventFilter(watched, event)

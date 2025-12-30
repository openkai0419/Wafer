from enum import Enum, auto
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.profiling import profiler
from ...command.core import CommandRegistry

class ClickType(Enum):
    SINGLE = auto()
    DOUBLE = auto()
    WHEEL_UP = auto()
    WHEEL_DOWN = auto()
    DRAG_START = auto()
    DROP = auto()

class MouseButton(Enum):
    LEFT = QtCore.Qt.LeftButton
    RIGHT = QtCore.Qt.RightButton
    MIDDLE = QtCore.Qt.MiddleButton
    X1 = QtCore.Qt.XButton1
    X2 = QtCore.Qt.XButton2
    NONE = 0

class ModifierKey(Enum):
    CTRL = auto()
    SHIFT = auto()
    ALT = auto()
    META = auto()

class DragContext:
    def __init__(self):
        self.cancelled = False
    
    def on_move(self, event):
        pass
    
    def on_end(self, event):
        pass
    
    def on_enter(self, event):
        pass
    
    def on_leave(self, event):
        pass
    
    def on_drop(self, event):
        pass


class ExternalDropDynamicContext(DragContext):
    def __init__(self, widget, registry, resolver):
        super().__init__()
        self.widget = widget
        self.registry = registry
        self.resolver = resolver
        self._active_payload = None
        self._active_key = None

    def _exec(self, payload, suffix: str, event, key):
        if not payload:
            return False
        base_id = getattr(payload, "id", None)
        if not base_id:
            return False
        cmd_id = f"{base_id}.{suffix}"
        if not self.registry.has_command(cmd_id):
            return False
        args = getattr(payload, "args", None) or {}
        self.registry.execute(cmd_id, event=event, widget=self.widget, key=key, context=self, **args)
        return True

    def _switch_if_needed(self, payload, key, event, allow_enter: bool):
        if self._active_payload is payload and self._active_key == key:
            return
        if self._active_payload is not None and self._active_key is not None:
            self._exec(self._active_payload, "leave", event, self._active_key)
        self._active_payload = payload
        self._active_key = key
        if allow_enter and self._active_payload is not None and self._active_key is not None:
            self._exec(self._active_payload, "enter", event, self._active_key)

    def on_enter(self, event):
        payload, key = self.resolver(event)
        self._active_payload = payload
        self._active_key = key
        return self._exec(payload, "enter", event, key)

    def on_move(self, event):
        payload, key = self.resolver(event)
        self._switch_if_needed(payload, key, event, allow_enter=True)
        return self._exec(self._active_payload, "move", event, self._active_key)

    def on_leave(self, event):
        if self._active_payload is None or self._active_key is None:
            return False
        ok = self._exec(self._active_payload, "leave", event, self._active_key)
        self._active_payload = None
        self._active_key = None
        return ok

    def on_drop(self, event):
        payload, key = self.resolver(event)
        if payload is not self._active_payload or key != self._active_key:
            if self._active_payload is not None and self._active_key is not None:
                self._exec(self._active_payload, "leave", event, self._active_key)
            self._active_payload = payload
            self._active_key = key
        ok = self._exec(self._active_payload, "drop", event, self._active_key)
        self._active_payload = None
        self._active_key = None
        return ok

class CommandDragContext(DragContext):
    def __init__(self, base_id, registry, widget, args=None):
        super().__init__()
        self.base_id = base_id
        self.registry = registry
        self.widget = widget
        self.args = args or {}
    
    def on_move(self, event):
        cmd_id = f"{self.base_id}.move"
        if self.registry.has_command(cmd_id):
            self.registry.execute(cmd_id, event=event, widget=self.widget, context=self, **self.args)
    
    def on_end(self, event):
        cmd_id = f"{self.base_id}.end"
        if self.registry.has_command(cmd_id):
            self.registry.execute(cmd_id, event=event, widget=self.widget, context=self, **self.args)
    
    def on_enter(self, event):
        cmd_id = f"{self.base_id}.enter"
        if self.registry.has_command(cmd_id):
            self.registry.execute(cmd_id, event=event, widget=self.widget, **self.args)
    
    def on_leave(self, event):
        cmd_id = f"{self.base_id}.leave"
        if self.registry.has_command(cmd_id):
            self.registry.execute(cmd_id, event=event, widget=self.widget, **self.args)
    
    def on_drop(self, event):
        cmd_id = f"{self.base_id}.drop"
        if self.registry.has_command(cmd_id):
            self.registry.execute(cmd_id, event=event, widget=self.widget, **self.args)

class MouseActionKey:

    def __init__(self, button, click_type, held_buttons, modifiers=()):
        self.button = button
        self.click_type = click_type
        self.held_buttons = frozenset(held_buttons)
        self.modifiers = frozenset(modifiers)

    def __hash__(self):
        return hash((self.button, self.click_type, self.held_buttons, self.modifiers))

    def __eq__(self, other):
        return self.button == other.button and self.click_type == other.click_type and (self.held_buttons == other.held_buttons) and (self.modifiers == other.modifiers)

    def __repr__(self):
        try:
            held_list = list(self.held_buttons)
            held_list.sort(key=lambda b: b.value)
            held = '+'.join((btn.name for btn in held_list))
        except Exception as e:
            held = f'[ERROR sorting held_buttons: {e}]'
        try:
            mods_list = list(self.modifiers)
            mods_list.sort(key=lambda m: m.value)
            mods = '+'.join((m.name for m in mods_list))
        except Exception as e:
            mods = f'[ERROR sorting modifiers: {e}]'
        prefix = '+'.join([p for p in (mods, held) if p])
        return f"{'+'.join([prefix, self.button.name])} {self.click_type.name}" if prefix else f'{self.button.name} {self.click_type.name}'

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
        self._suppress_groups = []
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
        for group in self._suppress_groups[:]:
            if button in group:
                self._suppress_groups.remove(group)
                return True
        return False

    def add_suppress_group(self, buttons):
        if buttons:
            self._suppress_groups.append(set(buttons))

    def clear_suppress_groups(self):
        self._suppress_groups.clear()

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
            except Exception:
                handled = False
        else:
            print(f"[DEBUG] No action or resolver found for key={key}")
        if handled:
            if key.click_type == ClickType.SINGLE and key.held_buttons:
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
                    if self._registry.has_command(f"{base_id}.start"):
                        self._registry.execute(f"{base_id}.start", event=event, widget=widget, **args)
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
            except Exception:
                return QtCore.Qt.NoModifier
        km = getattr(event, "keyboardModifiers", None)
        if callable(km):
            try:
                return km()
            except Exception:
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
        except Exception:
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

class MouseEventDispatcher(QtCore.QObject):

    def __init__(self, target_widget, mouse_event_manager, enable_drag=True):
        super().__init__(target_widget)
        self._manager = mouse_event_manager
        self._target = target_widget
        self._state = MouseStateManager.instance()
        self._enable_drag = enable_drag
        if enable_drag:
            self._target.setAcceptDrops(True)
        self._target.installEventFilter(self)
        self._dragging_button = None

    def _get_global_pos(self, event):
        gp = getattr(event, "globalPosition", None)
        if callable(gp):
            return gp().toPoint()
        return getattr(event, "globalPos", lambda: QtCore.QPoint())()

    def _handle_mouse_press(self, event):
        if self._state.is_event_processed(event):
            return
        self._state.set_press_position(self._target, event.pos())
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
                if self._state.check_drag_threshold(press_pos, event.pos()):
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
        except Exception:
            pass

    def _find_target_widget(self, event):
        try:
            from ..manager import BindingManager
            gpt = self._get_global_pos(event)
            return BindingManager.instance().find_binding_widget_at(gpt)
        except Exception:
            return None

    def _handle_mouse_release(self, event):
        if self._state.is_event_processed(event):
            return
        
        ctx = self._state.get_internal_drag_context(self._target)
        if ctx is not None:
            if not ctx.cancelled:
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
            button = MouseEventManager.map_qt_button(nev.button())
            held = MouseEventManager.get_held_buttons(nev.buttons(), exclude=button)
            click_type = ClickType.DOUBLE if is_double else ClickType.SINGLE
            mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(nev))
            key = MouseActionKey(button, click_type, held, mods)
            target_widget._mouse_manager.execute_action(key, nev)
        else:
            button = MouseEventManager.map_qt_button(event.button())
            held = MouseEventManager.get_held_buttons(event.buttons(), exclude=button)
            click_type = ClickType.DOUBLE if is_double else ClickType.SINGLE
            mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
            key = MouseActionKey(button, click_type, held, mods)
            self._manager.execute_action(key, event)
        self._state.clear_press_position(self._target)
        self._dragging_button = None

    def _handle_wheel(self, event):
        if self._state.is_event_processed(event):
            return
        delta = event.angleDelta().y()
        click_type = ClickType.WHEEL_UP if delta > 0 else ClickType.WHEEL_DOWN
        held = MouseEventManager.get_held_buttons(event.buttons())
        mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
        key = MouseActionKey(MouseButton.NONE, click_type, held, mods)
        self._manager.execute_action(key, event)

    def _handle_drop(self, event):
        if self._state.is_event_processed(event):
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            ctx.on_drop(event)
            self._state.end_external_drag(self._target)
        else:
            mods = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(event))
            key = MouseActionKey(MouseButton.NONE, ClickType.DROP, frozenset(), mods)
            from ..mixins import CommandBindingMixin
            widget = self._target
            if isinstance(widget, CommandBindingMixin):
                bindings = widget.get_mouse_bindings()
                payload = bindings.get(key)
                if payload:
                    base_id = payload.id
                    args = payload.args or {}
                    registry = CommandRegistry()
                    if registry.has_command(f"{base_id}.drop"):
                        registry.execute(f"{base_id}.drop", event=event, widget=widget, key=key, **args)
                        event.accept()
                        event.acceptProposedAction()
                        return
            self._manager.execute_action(key, event)
        event.accept()
        event.acceptProposedAction()

    def _handle_drag_enter(self, event):
        if self._state.is_event_processed(event):
            return
        def _resolve_drop(ev):
            m = MouseEventManager.get_modifiers(MouseEventManager._qt_modifiers_for_event(ev))
            k = MouseActionKey(MouseButton.NONE, ClickType.DROP, (), m)
            payload = None
            try:
                if hasattr(self._target, "get_mouse_bindings"):
                    payload = self._target.get_mouse_bindings().get(k)
            except Exception:
                payload = None
            if payload is None:
                try:
                    from .store import MouseBindingStore
                    store = MouseBindingStore()
                    scope = self._target.binding_scope() if hasattr(self._target, "binding_scope") else "*"
                    payload = store.resolve(scope, k)
                except Exception:
                    payload = None
            return payload, k

        payload, _ = _resolve_drop(event)
        ctx = None
        if payload is not None:
            try:
                ctx = ExternalDropDynamicContext(self._target, CommandRegistry(), _resolve_drop)
                ctx.on_enter(event)
            except Exception:
                ctx = None
        if ctx:
            self._state.start_external_drag(self._target, ctx)
        event.accept()
        event.acceptProposedAction()

    def _handle_drag_move(self, event):
        if self._state.is_event_processed(event):
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            ctx.on_move(event)
        event.accept()
        event.acceptProposedAction()

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
        if watched != self._target:
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
        elif isinstance(event, QtGui.QWheelEvent):
            self._handle_wheel(event)
        elif event.type() == QtCore.QEvent.DragEnter:
            self._handle_drag_enter(event)
            return True
        elif event.type() == QtCore.QEvent.DragMove:
            self._handle_drag_move(event)
            return True
        elif event.type() == QtCore.QEvent.DragLeave:
            self._handle_drag_leave(event)
            return True
        elif event.type() == QtCore.QEvent.Drop:
            self._handle_drop(event)
            return True
        return super().eventFilter(watched, event)

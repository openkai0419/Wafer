from enum import Enum, auto
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.profiling import profiler
from ...command.core import CommandRegistry
from ...command.context import CommandContext
from source.common.logs import AppLogger

class ClickType(Enum):
    SINGLE = auto()
    DOUBLE = auto()
    WHEEL_UP = auto()
    WHEEL_DOWN = auto()
    DRAG_START = auto()
    DROP = auto()

    @staticmethod
    def from_any(v):
        if isinstance(v, ClickType):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "WHEELUP": "WHEEL_UP",
                "WHEELDOWN": "WHEEL_DOWN",
                "DRAGSTART": "DRAG_START",
            }
            s = aliases.get(s, s)
            try:
                return ClickType[s]
            except KeyError as e:
                raise ValueError(f"invalid ClickType: {v}") from e
        raise TypeError("ClickType must be ClickType or str")

class MouseButton(Enum):
    LEFT = QtCore.Qt.LeftButton
    RIGHT = QtCore.Qt.RightButton
    MIDDLE = QtCore.Qt.MiddleButton
    X1 = QtCore.Qt.XButton1
    X2 = QtCore.Qt.XButton2
    NONE = 0

    @staticmethod
    def from_any(v):
        if isinstance(v, MouseButton):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "LMB": "LEFT",
                "RMB": "RIGHT",
                "MMB": "MIDDLE",
                "MB1": "X1",
                "MB2": "X2",
                "XBUTTON1": "X1",
                "XBUTTON2": "X2",
            }
            s = aliases.get(s, s)
            try:
                return MouseButton[s]
            except KeyError as e:
                raise ValueError(f"invalid MouseButton: {v}") from e
        raise TypeError("MouseButton must be MouseButton or str")

class ModifierKey(Enum):
    CTRL = auto()
    SHIFT = auto()
    ALT = auto()
    META = auto()

    @staticmethod
    def from_any(v):
        if isinstance(v, ModifierKey):
            return v
        if isinstance(v, str):
            s = v.strip().upper().replace("-", "_").replace(" ", "_")
            aliases = {
                "CONTROL": "CTRL",
                "CMD": "META",
                "COMMAND": "META",
                "WIN": "META",
                "WINDOWS": "META",
                "SUPER": "META",
                "OPTION": "ALT",
            }
            s = aliases.get(s, s)
            try:
                return ModifierKey[s]
            except KeyError as e:
                raise ValueError(f"invalid ModifierKey: {v}") from e
        raise TypeError("ModifierKey must be ModifierKey or str")

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
        cmd_class = self.registry.get_command(base_id)
        if not cmd_class:
            return False
        meta = getattr(cmd_class, "meta", None)
        callbacks = getattr(meta, "drop_callbacks", None) or {}
        if "drop" not in callbacks:
            return False
        args = dict(getattr(payload, "args", None) or {})
        ctx = CommandContext.create(self.widget, None, source="drop", event=event, extras={"context": self, "phase": str(suffix)})
        self.registry.execute(base_id, ctx=ctx, **args)
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

    def _dispatch(self, phase: str, source: str, callback_attr: str, event):
        cmd_class = self.registry.get_command(self.base_id)
        if cmd_class and phase in (getattr(getattr(cmd_class, "meta", None), callback_attr, None) or {}):
            ctx = CommandContext.create(self.widget, None, source=source, event=event, extras={"context": self, "phase": phase})
            self.registry.execute(self.base_id, ctx=ctx, **self.args)

    def on_move(self, event):
        self._dispatch("move", "drag", "drag_callbacks", event)

    def on_end(self, event):
        self._dispatch("end", "drag", "drag_callbacks", event)

    def on_enter(self, event):
        self._dispatch("enter", "drop", "drop_callbacks", event)

    def on_leave(self, event):
        self._dispatch("leave", "drop", "drop_callbacks", event)

    def on_drop(self, event):
        self._dispatch("drop", "drop", "drop_callbacks", event)

class MouseActionKey:
    def __init__(self, button, click_type=None, held_buttons=(), modifiers=()):
        if click_type is None:
            raise TypeError("MouseActionKey requires click_type")
        if held_buttons == {} or held_buttons is None:
            held_buttons = ()
        if modifiers == {} or modifiers is None:
            modifiers = ()
        self.button = MouseButton.from_any(button)
        self.click_type = ClickType.from_any(click_type)
        self.held_buttons = frozenset(MouseButton.from_any(b) for b in (held_buttons or ()))
        self.modifiers = frozenset(ModifierKey.from_any(m) for m in (modifiers or ()))

    def __hash__(self):
        return hash((self.button, self.click_type, self.held_buttons, self.modifiers))

    def __eq__(self, other):
        return self.button == other.button and self.click_type == other.click_type and (self.held_buttons == other.held_buttons) and (self.modifiers == other.modifiers)

    def __repr__(self):
        held = '+'.join((btn.name for btn in sorted(self.held_buttons, key=lambda b: b.name)))
        mods = '+'.join((m.name for m in sorted(self.modifiers, key=lambda m: m.name)))
        prefix = '+'.join([p for p in (mods, held) if p])
        return f"{'+'.join([prefix, self.button.name])} {self.click_type.name}" if prefix else f'{self.button.name} {self.click_type.name}'

    def to_dict(self):
        return {
            "button": self.button.name,
            "click": self.click_type.name,
            "held": [b.name for b in sorted(self.held_buttons, key=lambda x: x.name)],
            "modifiers": [m.name for m in sorted(self.modifiers, key=lambda x: x.name)],
        }

    @classmethod
    def from_dict(cls, d):
        if not isinstance(d, dict):
            raise TypeError("MouseActionKey dict required")
        btn = MouseButton.from_any(d.get("button"))
        clk = ClickType.from_any(d.get("click"))
        held = tuple(MouseButton.from_any(x) for x in (d.get("held") or ()))
        mods = tuple(ModifierKey.from_any(x) for x in (d.get("modifiers") or ()))
        return cls(btn, clk, held, mods)

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
                    if cmd_class and str("start") in (getattr(getattr(cmd_class, "meta", None), "drag_callbacks", None) or {}):
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
                except Exception:
                    pass
        for w in self._watch_targets:
            try:
                w.installEventFilter(self)
            except Exception:
                pass
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
        except Exception:
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
            except Exception:
                pass
        try:
            return event.pos()
        except Exception:
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
        except Exception:
            payload = None
        if payload is None:
            try:
                from .store import MouseBindingStore

                scope = self._target.binding_scope() if hasattr(self._target, "binding_scope") else "*"
                payload = MouseBindingStore().resolve(scope, key)
            except Exception:
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
            except Exception:
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
            except Exception:
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
            try:
                event.ignore()
            except Exception:
                pass
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            executed = bool(ctx.on_drop(event))
            self._state.end_external_drag(self._target)
            try:
                if executed:
                    event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
                    event.accept()
                else:
                    event.ignore()
            except Exception:
                pass
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
                    registry = CommandRegistry()
                    cmd_class = registry.get_command(base_id)
                    if cmd_class and str("drop") in (getattr(getattr(cmd_class, "meta", None), "drop_callbacks", None) or {}):
                        ctx = CommandContext.create(widget, None, source="drop", event=event)
                        ctx.put("phase", "drop")
                        registry.execute(base_id, ctx=ctx, **args)
                        try:
                            event.accept()
                        except Exception:
                            pass
                        return
            executed = bool(self._manager.execute_action(key, event))
            try:
                if executed:
                    event.setDropAction(QtCore.Qt.DropAction.IgnoreAction)
                    event.accept()
                else:
                    event.ignore()
            except Exception:
                pass

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
                store = MouseBindingStore()
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
            try:
                event.ignore()
            except Exception:
                pass
            return

        payload, _ = self._resolve_drop_payload(event)
        if payload is None:
            try:
                event.ignore()
            except Exception:
                pass
            return
        base_id = getattr(payload, "id", None)
        cmd_class = CommandRegistry().get_command(base_id) if base_id else None
        callbacks = (getattr(getattr(cmd_class, "meta", None), "drop_callbacks", None) or {}) if cmd_class else {}
        if not callbacks or "drop" not in callbacks:
            try:
                event.ignore()
            except Exception:
                pass
            return
        ctx = None
        executed = False
        try:
            ctx = ExternalDropDynamicContext(self._target, CommandRegistry(), self._resolve_drop_payload)
            executed = bool(ctx.on_enter(event))
        except Exception as e:
            AppLogger.warning("ExternalDropDynamicContext.on_enter failed", exc=e)
            ctx = None
        if ctx is None:
            try:
                event.ignore()
            except Exception:
                pass
            return
        self._state.start_external_drag(self._target, ctx)
        try:
            (event.accept() if executed else event.ignore())
        except Exception:
            pass

    def _handle_drag_move(self, event):
        if self._state.is_event_processed(event):
            return
        from ..mixins import CommandBindingMixin
        if not isinstance(self._target, CommandBindingMixin) or not self._target.drop_accept(event):
            ctx = self._state.get_external_drag_context(self._target)
            if ctx:
                try:
                    ctx.on_leave(event)
                except Exception:
                    pass
                self._state.end_external_drag(self._target)
            try:
                event.ignore()
            except Exception:
                pass
            return
        ctx = self._state.get_external_drag_context(self._target)
        if ctx:
            executed = bool(ctx.on_move(event))
            try:
                (event.accept() if executed else event.ignore())
            except Exception:
                pass
        else:
            try:
                event.ignore()
            except Exception:
                pass

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

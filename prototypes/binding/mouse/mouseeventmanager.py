from enum import Enum, auto
from PySide6 import QtCore, QtGui, QtWidgets
from source.common.profiling import profiler

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

class MouseActionKey:

    def __init__(self, button, click_type, held_buttons):
        self.button = button
        self.click_type = click_type
        self.held_buttons = frozenset(held_buttons)

    def __hash__(self):
        return hash((self.button, self.click_type, self.held_buttons))

    def __eq__(self, other):
        return self.button == other.button and self.click_type == other.click_type and (self.held_buttons == other.held_buttons)

    def __repr__(self):
        try:
            held_list = list(self.held_buttons)
            held_list.sort(key=lambda b: b.value if isinstance(b.value, int) else int(b.value))
            held = '+'.join((btn.name for btn in held_list))
        except Exception as e:
            held = f'[ERROR sorting held_buttons: {e}]'
        return f"{'+'.join([held, self.button.name])} {self.click_type.name}" if held else f'{self.button.name} {self.click_type.name}'

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

    def _cleanup_old_events(self):
        current = QtCore.QTime.currentTime()
        if self._last_cleanup_time.msecsTo(current) > 10000:
            self._processed_events.clear()
            self._last_cleanup_time = current

    def is_event_processed(self, event):
        self._cleanup_old_events()
        event_signature = (event.type(), event.timestamp())
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

class MouseEventManager:

    def __init__(self):
        self._bindings = {}
        self._resolver = None
        self._state = MouseStateManager.instance()

    def bind(self, key, action):
        self._bindings[key] = action

    def unbind(self, key):
        self._bindings.pop(key, None)

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
        if action:
            action(*args, **kwargs)
            handled = True
        elif self._resolver:
            try:
                res = self._resolver(key, *args, **kwargs)
                handled = bool(res)
            except Exception:
                handled = False
        if handled:
            if key.click_type == ClickType.SINGLE and key.held_buttons:
                self._state.add_suppress_group(list(key.held_buttons))
            event = args[0] if args else None
            if event is not None and hasattr(event, 'accept'):
                event.accept()
        return handled

    @staticmethod
    def map_qt_button(qt_button):
        for b in MouseButton:
            if b.value == qt_button:
                return b
        return MouseButton.NONE

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

    def __init__(self, target_widget, mouse_event_manager, enable_drag=False):
        super().__init__(target_widget)
        self._manager = mouse_event_manager
        self._target = target_widget
        self._state = MouseStateManager.instance()
        self._enable_drag = enable_drag
        self._target.setAcceptDrops(True)
        self._target.installEventFilter(self)

    def _get_global_pos(self, event):
        gp = getattr(event, "globalPosition", None)
        if callable(gp):
            return gp().toPoint()
        return getattr(event, "globalPos", lambda: QtCore.QPoint())()

    def _handle_mouse_press(self, event):
        if self._state.is_event_processed(event):
            return
        self._state.set_press_position(self._target, event.pos())

    def _handle_mouse_move(self, event):
        if not self._enable_drag:
            return
        if self._state.is_event_processed(event):
            return
        press_pos = self._state.get_press_position(self._target)
        if press_pos is not None:
            if self._state.check_drag_threshold(press_pos, event.pos()):
                button = MouseEventManager.map_qt_button(event.button())
                held = MouseEventManager.get_held_buttons(event.buttons(), exclude=button)
                key = MouseActionKey(button, ClickType.DRAG_START, held)
                self._manager.execute_action(key, event)
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
        target_widget = self._find_target_widget(event)
        if target_widget is None or not hasattr(target_widget, "_mouse_manager"):
            self._state.clear_press_position(self._target)
            self._state.clear_double_click_button(self._target)
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
            key = MouseActionKey(button, click_type, held)
            target_widget._mouse_manager.execute_action(key, nev)
        else:
            button = MouseEventManager.map_qt_button(event.button())
            held = MouseEventManager.get_held_buttons(event.buttons(), exclude=button)
            click_type = ClickType.DOUBLE if is_double else ClickType.SINGLE
            key = MouseActionKey(button, click_type, held)
            self._manager.execute_action(key, event)
        self._state.clear_press_position(self._target)

    def _handle_wheel(self, event):
        if self._state.is_event_processed(event):
            return
        delta = event.angleDelta().y()
        click_type = ClickType.WHEEL_UP if delta > 0 else ClickType.WHEEL_DOWN
        held = MouseEventManager.get_held_buttons(event.buttons())
        key = MouseActionKey(MouseButton.NONE, click_type, held)
        self._manager.execute_action(key, event)

    def _handle_drop(self, event):
        if self._state.is_event_processed(event):
            return
        key = MouseActionKey(MouseButton.NONE, ClickType.DROP, ())
        self._manager.execute_action(key, event)

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
        elif isinstance(event, QtGui.QDropEvent):
            if event.type() == QtCore.QEvent.Drop:
                self._handle_drop(event)
        return super().eventFilter(watched, event)

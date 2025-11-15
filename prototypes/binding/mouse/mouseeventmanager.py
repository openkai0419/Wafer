from enum import Enum, auto
from PySide6 import QtCore, QtGui, QtWidgets

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

class MouseEventManager:

    def __init__(self):
        self._bindings = {}
        self._resolver = None
        self._suppress_single = set()

    def bind(self, key, action):
        self._bindings[key] = action

    def unbind(self, key):
        self._bindings.pop(key, None)

    def clear(self):
        self._bindings.clear()
        self._resolver = None
        self._suppress_single.clear()

    def set_resolver(self, resolver):
        self._resolver = resolver

    def handle_mouse_event(self, event, double_click=False):
        button = self._map_qt_button(event.button())
        held = self._get_held_buttons(event.buttons(), exclude=button)
        click_type = ClickType.DOUBLE if double_click else ClickType.SINGLE
        key = MouseActionKey(button, click_type, held)
        self._trigger(key, event)

    def handle_wheel_event(self, event):
        delta = event.angleDelta().y()
        click_type = ClickType.WHEEL_UP if delta > 0 else ClickType.WHEEL_DOWN
        held = self._get_held_buttons(event.buttons())
        key = MouseActionKey(MouseButton.NONE, click_type, held)
        self._trigger(key, event)

    def handle_drag_start(self, event):
        button = self._map_qt_button(event.button())
        held = self._get_held_buttons(event.buttons(), exclude=button)
        key = MouseActionKey(button, ClickType.DRAG_START, held)
        self._trigger(key, event)

    def handle_drop(self, event):
        held = ()
        key = MouseActionKey(MouseButton.NONE, ClickType.DROP, held)
        self._trigger(key, event)

    def _get_held_buttons(self, buttons, exclude=None):
        btns = []
        for qt_btn in [QtCore.Qt.LeftButton, QtCore.Qt.RightButton, QtCore.Qt.MiddleButton, QtCore.Qt.XButton1, QtCore.Qt.XButton2]:
            if buttons & qt_btn:
                mapped = self._map_qt_button(qt_btn)
                if mapped != exclude:
                    btns.append(mapped)
        return tuple(btns)

    def _map_qt_button(self, qt_button):
        for b in MouseButton:
            if b.value == qt_button:
                return b
        return MouseButton.NONE

    def _trigger(self, key, *args, **kwargs):
        if key.click_type == ClickType.SINGLE and (not key.held_buttons) and key.button in self._suppress_single:
            try:
                self._suppress_single.remove(key.button)
            except KeyError:
                pass
            return
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
        if handled and key.click_type == ClickType.SINGLE and key.held_buttons:
            for b in set([key.button, *key.held_buttons]):
                self._suppress_single.add(b)

class MouseEventDispatcher(QtCore.QObject):

    def __init__(self, target_widget, mouse_event_manager):
        super().__init__(target_widget)
        self._manager = mouse_event_manager
        self._target = target_widget
        self._target.setAcceptDrops(True)
        self._target.installEventFilter(self)
        self._last_double_click_button = None
        self._press_pos = None
        self._drag_threshold = QtWidgets.QApplication.startDragDistance()

    def eventFilter(self, watched, event):
        if not isinstance(event, QtCore.QEvent):
            return False
        if watched != self._target:
            return super().eventFilter(watched, event)
        if isinstance(event, QtGui.QMouseEvent):
            if event.type() == QtCore.QEvent.MouseButtonPress:
                self._press_pos = event.pos()
            elif event.type() == QtCore.QEvent.MouseMove:
                if self._press_pos is not None:
                    if (event.pos() - self._press_pos).manhattanLength() >= self._drag_threshold:
                        self._manager.handle_drag_start(event)
                        self._press_pos = None
            elif event.type() == QtCore.QEvent.MouseButtonDblClick:
                self._last_double_click_button = event.button()
            elif event.type() == QtCore.QEvent.MouseButtonRelease:
                forwarded = False
                try:
                    from ..manager import BindingManager
                    gp = getattr(event, "globalPosition", None)
                    if callable(gp):
                        gpt = gp().toPoint()
                    else:
                        gpt = getattr(event, "globalPos", lambda: QtCore.QPoint())()
                    candidate = BindingManager.instance().find_binding_widget_at(gpt)
                    if candidate is not None and candidate is not self._target and hasattr(candidate, "_mouse_manager"):
                        lpt = candidate.mapFromGlobal(gpt)
                        btn = event.button()
                        btns = event.buttons()
                        mods = event.modifiers()
                        et = event.type()
                        try:
                            nev = QtGui.QMouseEvent(et, QtCore.QPointF(lpt), btn, btns, mods)
                        except TypeError:
                            nev = QtGui.QMouseEvent(et, QtCore.QPointF(lpt), QtCore.QPointF(lpt), QtCore.QPointF(gpt), btn, btns, mods)
                        candidate._mouse_manager.handle_mouse_event(nev, double_click=(self._last_double_click_button == event.button()))
                        forwarded = True
                except Exception:
                    forwarded = False
                if self._last_double_click_button == event.button():
                    if not forwarded:
                        self._manager.handle_mouse_event(event, double_click=True)
                    self._last_double_click_button = None
                else:
                    if not forwarded:
                        self._manager.handle_mouse_event(event, double_click=False)
                self._press_pos = None
        elif isinstance(event, QtGui.QWheelEvent):
            self._manager.handle_wheel_event(event)
            return True
        elif isinstance(event, QtGui.QDropEvent):
            if event.type() == QtCore.QEvent.Drop:
                self._manager.handle_drop(event)
                return True
            return True
        return super().eventFilter(watched, event)

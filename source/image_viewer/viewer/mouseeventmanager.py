from enum import Enum, auto
from typing import Callable, Dict, Optional, Tuple
from PySide6 import QtCore, QtGui

class ClickType(Enum):
    SINGLE = auto()
    DOUBLE = auto()
    WHEEL_UP = auto()
    WHEEL_DOWN = auto()


class MouseButton(Enum):
    LEFT = QtCore.Qt.LeftButton
    RIGHT = QtCore.Qt.RightButton
    MIDDLE = QtCore.Qt.MiddleButton
    X1 = QtCore.Qt.XButton1
    X2 = QtCore.Qt.XButton2
    NONE = 0  # e.g. for wheel events


class MouseActionKey:
    def __init__(self, button: MouseButton, click_type: ClickType, held_buttons: Tuple[MouseButton]):
        self.button = button
        self.click_type = click_type
        self.held_buttons = frozenset(held_buttons)

    def __hash__(self):
        return hash((self.button, self.click_type, self.held_buttons))

    def __eq__(self, other):
        return (
            self.button == other.button and
            self.click_type == other.click_type and
            self.held_buttons == other.held_buttons
        )

    def __repr__(self):
        held = '+'.join(btn.name for btn in sorted(self.held_buttons, key=lambda b: b.value))
        return f"{'+'.join([held, self.button.name])} {self.click_type.name}" if held else f"{self.button.name} {self.click_type.name}"


class MouseEventManager:
    def __init__(self):
        self._bindings: Dict[MouseActionKey, Callable] = {}

    def bind(self, key: MouseActionKey, action: Callable):
        self._bindings[key] = action

    def unbind(self, key: MouseActionKey):
        self._bindings.pop(key, None)

    def clear(self):
        self._bindings.clear()

    def handle_mouse_event(self, event: QtGui.QMouseEvent, double_click: bool = False):
        button = self._map_qt_button(event.button())
        held = self._get_held_buttons(event.buttons(), exclude=button)
        click_type = ClickType.DOUBLE if double_click else ClickType.SINGLE
        key = MouseActionKey(button, click_type, held)
        self._trigger(key, event)

    def handle_wheel_event(self, event: QtGui.QWheelEvent):
        delta = event.angleDelta().y()
        click_type = ClickType.WHEEL_UP if delta > 0 else ClickType.WHEEL_DOWN
        held = self._get_held_buttons(event.buttons())
        key = MouseActionKey(MouseButton.NONE, click_type, held)
        self._trigger(key, event)

    def _get_held_buttons(self, buttons: QtCore.Qt.MouseButtons, exclude: Optional[MouseButton] = None):
        btns = []
        for qt_btn in [QtCore.Qt.LeftButton, QtCore.Qt.RightButton, QtCore.Qt.MiddleButton, QtCore.Qt.XButton1, QtCore.Qt.XButton2]:
            if buttons & qt_btn:
                mapped = self._map_qt_button(qt_btn)
                if mapped != exclude:
                    btns.append(mapped)
        return tuple(btns)

    def _map_qt_button(self, qt_button: QtCore.Qt.MouseButton) -> MouseButton:
        for b in MouseButton:
            if b.value == qt_button:
                return b
        return MouseButton.NONE

    def _trigger(self, key: MouseActionKey, *args, **kwargs):
        action = self._bindings.get(key)
        if action:
            action(*args, **kwargs)
        else:
            pass

class MouseEventDispatcher(QtCore.QObject):
    def __init__(self, target_widget, mouse_event_manager: MouseEventManager):
        super().__init__(target_widget)
        self._manager = mouse_event_manager
        self._target = target_widget
        self._target.installEventFilter(self)

    def eventFilter(self, watched, event):
        if watched != self._target:
            return super().eventFilter(watched, event)

        if isinstance(event, QtGui.QMouseEvent):
            if event.type() == QtCore.QEvent.MouseButtonDblClick:
                self._manager.handle_mouse_event(event, double_click=True)
                return False
            elif event.type() == QtCore.QEvent.MouseButtonPress:
                self._manager.handle_mouse_event(event, double_click=False)
                return False

        elif isinstance(event, QtGui.QWheelEvent):
            self._manager.handle_wheel_event(event)
            return False

        return super().eventFilter(watched, event)

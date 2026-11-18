import time
from functools import wraps
from shiboken6 import isValid
from PySide6.QtCore import QObject, QTimer, Slot


class QtDebounceManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._timers: dict[object, QTimer] = {}
        self._callbacks: dict[object, tuple] = {}

    def debounce(self, key, delay_ms, callback, *args, **kwargs):
        if key in self._timers:
            self._timers[key].stop()
            self._timers[key].deleteLater()
            del self._timers[key]
        self._callbacks[key] = (callback, args, kwargs)
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setProperty("_debounce_key", key)
        timer.timeout.connect(self._on_timer_fired)
        timer.start(delay_ms)
        self._timers[key] = timer

    @Slot()
    def _on_timer_fired(self):
        timer = self.sender()
        key = timer.property("_debounce_key")
        self._timers.pop(key, None)
        entry = self._callbacks.pop(key, None)
        timer.deleteLater()
        if entry:
            cb, args, kwargs = entry
            if args and isinstance(args[0], QObject) and not isValid(args[0]):
                return
            cb(*args, **kwargs)

    def cancel(self, key):
        timer = self._timers.pop(key, None)
        self._callbacks.pop(key, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()


qt_debounce_manager = QtDebounceManager()


def qt_debounce(delay_ms):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = id(func)
            if args:
                obj = args[0]
                if hasattr(obj, "__dict__"):
                    key = (id(func), id(obj))
            qt_debounce_manager.debounce(key, delay_ms, func, *args, **kwargs)

        return wrapper

    return decorator


class ThrottleState:
    __slots__ = ("last_call", "pending", "timer")

    def __init__(self, timer: QTimer, last_call: float):
        self.timer = timer
        self.last_call = last_call
        self.pending: tuple | None = None


class QtThrottleManager(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._states: dict[object, ThrottleState] = {}

    def throttle(self, key, throttle_ms, idle_ms, callback, *args, **kwargs):
        now = time.monotonic() * 1000
        state = self._states.get(key)
        if state is None:
            timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda: self._on_idle(key, callback))
            state = self._states[key] = ThrottleState(timer, now - throttle_ms)
        state.timer.start(idle_ms)
        if now - state.last_call >= throttle_ms:
            state.last_call = now
            state.pending = None
            callback(*args, **kwargs)
        else:
            state.pending = (args, kwargs)

    def _on_idle(self, key, callback):
        state = self._states.pop(key, None)
        if state is None:
            return
        self._dispose_timer(state.timer)
        if state.pending is None:
            return
        args, kwargs = state.pending
        if args and isinstance(args[0], QObject) and not isValid(args[0]):
            return
        callback(*args, **kwargs)

    def cancel(self, key):
        state = self._states.pop(key, None)
        if state is not None:
            self._dispose_timer(state.timer)

    @staticmethod
    def _dispose_timer(timer: QTimer):
        timer.stop()
        timer.timeout.disconnect()
        timer.deleteLater()


_qt_throttle_manager = QtThrottleManager()


def qt_throttle(throttle_ms=100, idle_ms=200):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = id(func)
            if args:
                obj = args[0]
                if hasattr(obj, "__dict__"):
                    key = (id(func), id(obj))
            _qt_throttle_manager.throttle(key, throttle_ms, idle_ms, func, *args, **kwargs)

        return wrapper

    return decorator

import time
from functools import wraps
from PySide6.QtCore import QObject, QTimer, Slot

class QtDebounceManager(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._timers = {}

    def debounce(self, key, delay_ms, callback, *args, **kwargs):
        if key in self._timers:
            self._timers[key].stop()
            self._timers[key].deleteLater()
            self._timers.pop(key, None)
        timer = QTimer(self)
        timer.setSingleShot(True)

        @Slot()
        def on_timeout():
            callback(*args, **kwargs)
            timer.deleteLater()
            self._timers.pop(key, None)
        timer.timeout.connect(on_timeout)
        timer.start(delay_ms)
        self._timers[key] = timer

    def cancel(self, key):
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()
_qt_debounce_manager = QtDebounceManager()

def qt_debounce(delay_ms):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = id(func)
            if args:
                obj = args[0]
                if hasattr(obj, '__dict__'):
                    key = (id(func), id(obj))
            _qt_debounce_manager.debounce(key, delay_ms, func, *args, **kwargs)
        return wrapper
    return decorator

class QtThrottleManager(QObject):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._states = {}

    def throttle(self, key, throttle_ms, idle_ms, callback, *args, **kwargs):
        now = time.time() * 1000
        state = self._states.get(key)
        if state:
            last_call, idle_timer = state
            idle_timer.stop()
            idle_timer.start(idle_ms)
            if now - last_call >= throttle_ms:
                self._states[key] = (now, idle_timer)
                callback(*args, **kwargs)
        else:
            idle_timer = QTimer(self)
            idle_timer.setSingleShot(True)

            @Slot()
            def on_idle():
                callback(*args, **kwargs)
                self._states.pop(key, None)
            idle_timer.timeout.connect(on_idle)
            idle_timer.start(idle_ms)
            self._states[key] = (now, idle_timer)
            callback(*args, **kwargs)
_qt_throttle_manager = QtThrottleManager()

def qt_throttle(throttle_ms=100, idle_ms=200):

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            key = id(func)
            if args:
                obj = args[0]
                if hasattr(obj, '__dict__'):
                    key = (id(func), id(obj))
            _qt_throttle_manager.throttle(key, throttle_ms, idle_ms, func, *args, **kwargs)
        return wrapper
    return decorator

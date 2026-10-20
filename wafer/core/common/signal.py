import threading


class Signal:
    def __init__(self):
        self._callbacks = []
        self._lock = threading.Lock()

    def connect(self, callback):
        with self._lock:
            self._callbacks.append(callback)

    def disconnect(self, callback) -> bool:
        with self._lock:
            if callback not in self._callbacks:
                return False
            self._callbacks.remove(callback)
            return True

    def emit(self, *args, **kwargs):
        with self._lock:
            snapshot = list(self._callbacks)
        for callback in snapshot:
            callback(*args, **kwargs)

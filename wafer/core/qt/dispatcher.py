import threading
from collections.abc import Callable

from PySide6 import QtCore

from ...utils.logs import AppLogger


class CancelToken:
    __slots__ = ("_event",)

    def __init__(self):
        self._event = threading.Event()

    def cancel(self):
        self._event.set()

    def is_cancelled(self) -> bool:
        return self._event.is_set()


class CancelSlot:
    __slots__ = ("_token",)

    def __init__(self):
        self._token: CancelToken | None = None

    def renew(self) -> CancelToken:
        if self._token is not None:
            self._token.cancel()
        self._token = CancelToken()
        return self._token

    def cancel(self):
        if self._token is not None:
            self._token.cancel()
            self._token = None


class _DispatchSignals(QtCore.QObject):
    _to_main = QtCore.Signal(object)


class _PostRunnable(QtCore.QRunnable):
    __slots__ = ("_cancel", "_fn")

    def __init__(self, fn, cancel):
        super().__init__()
        self.setAutoDelete(True)
        self._fn = fn
        self._cancel = cancel

    def run(self):
        if self._cancel is not None and self._cancel.is_cancelled():
            return
        try:
            self._fn()
        except Exception as e:
            AppLogger.warning(f"[Dispatcher.post] task failed: {e}", exc=e)


class Dispatcher:
    def __init__(self, pool=None):
        self._signals = _DispatchSignals()
        self._signals._to_main.connect(self._execute, QtCore.Qt.QueuedConnection)
        if pool is None:
            from .thread import grid_thumb_pool

            pool = grid_thumb_pool
        self._pool = pool

    def post(self, fn: Callable, priority: int = 5, cancel: CancelToken | None = None):
        self._pool.submit(_PostRunnable(fn, cancel), priority)

    def invoke(self, fn: Callable):
        self._signals._to_main.emit(fn)

    @QtCore.Slot(object)
    def _execute(self, fn: Callable):
        try:
            fn()
        except Exception as e:
            AppLogger.warning(f"[Dispatcher.invoke] callback failed: {e}", exc=e)

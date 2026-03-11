import threading
from typing import Callable, Optional

from PySide6 import QtCore

from ...utils.logs import AppLogger


class CancelToken:
    __slots__ = ('_event',)

    def __init__(self):
        self._event = threading.Event()

    def set(self):
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()


class _DispatchSignals(QtCore.QObject):
    _to_main = QtCore.Signal(object)


class Dispatcher:

    def __init__(self, pool=None):
        self._signals = _DispatchSignals()
        self._signals._to_main.connect(self._execute, QtCore.Qt.QueuedConnection)
        if pool is None:
            from .thread import grid_thumb_pool
            pool = grid_thumb_pool
        self._pool = pool

    def post(self, fn: Callable, priority: int = 5, cancel: Optional[CancelToken] = None):
        class _Runnable(QtCore.QRunnable):
            def run(self_):
                if cancel is not None and cancel.is_set():
                    return
                try:
                    fn()
                except Exception as e:
                    AppLogger.warning(f'[Dispatcher.post] task failed: {e}', exc=e)
        self._pool.submit(_Runnable(), priority)

    def invoke(self, fn: Callable):
        self._signals._to_main.emit(fn)

    @QtCore.Slot(object)
    def _execute(self, fn: Callable):
        try:
            fn()
        except Exception as e:
            AppLogger.warning(f'[Dispatcher.invoke] callback failed: {e}', exc=e)

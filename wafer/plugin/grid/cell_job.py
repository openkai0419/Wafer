from typing import Callable, Optional

from PySide6 import QtCore

from ...core.qt.dispatcher import Dispatcher, CancelToken


class CellJob:
    __slots__ = (
        'index', 'path', 'size', 'image_cache',
        '_cancel', '_dispatcher', '_render_dispatcher', '_widget_lookup',
    )

    def __init__(
        self,
        index: int,
        path: str,
        size: QtCore.QSize,
        image_cache,
        cancel: CancelToken,
        dispatcher: Dispatcher,
        widget_lookup: Callable[[int], Optional[object]],
        render_dispatcher: Optional[Dispatcher] = None,
    ):
        self.index = index
        self.path = path
        self.size = size
        self.image_cache = image_cache
        self._cancel = cancel
        self._dispatcher = dispatcher
        self._render_dispatcher = render_dispatcher or dispatcher
        self._widget_lookup = widget_lookup

    def is_cancelled(self) -> bool:
        return self._cancel.is_set()

    def invoke(self, fn: Callable):
        index = self.index
        token = self._cancel
        lookup = self._widget_lookup

        def guarded():
            if token.is_set():
                return
            widget = lookup(index)
            if widget is not None:
                fn(widget)

        self._dispatcher.invoke(guarded)

    def invoke_raw(self, fn: Callable):
        token = self._cancel

        def guarded():
            if token.is_set():
                return
            fn()

        self._dispatcher.invoke(guarded)

    def post(self, fn: Callable, priority: int = 5):
        self._render_dispatcher.post(fn, priority=priority, cancel=self._cancel)

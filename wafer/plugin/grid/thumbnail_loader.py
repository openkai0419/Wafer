from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable

from PySide6 import QtCore, QtGui

from ...core.logs import AppLogger
from ...qt.common.dispatcher import CancelToken, Dispatcher
from ...qt.common.dpi import dpix
from ...qt.common.thread import utility_pool
from .handler import load_thumbnail


class ThumbnailLoader:
    def __init__(self, on_loaded: Callable[[str], None], *, size: int, cache_limit: int, dispatcher: Dispatcher | None = None):
        self._on_loaded = on_loaded
        self._size = size
        self.cache_limit = cache_limit
        self._cache: OrderedDict[str, QtGui.QPixmap] = OrderedDict()
        self._tokens: dict[str, CancelToken] = {}
        self._dispatcher = dispatcher or Dispatcher(pool=utility_pool)

    @property
    def size(self) -> int:
        return self._size

    def set_size(self, size: int) -> None:
        if size == self._size:
            return
        self._size = size
        self.clear()

    def __contains__(self, path: str) -> bool:
        return path in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def get(self, path: str) -> QtGui.QPixmap | None:
        pixmap = self._cache.get(path)
        if pixmap is not None:
            self._cache.move_to_end(path)
        return pixmap

    def pending(self, path: str) -> bool:
        return path in self._tokens

    def request(self, paths: Iterable[str]) -> None:
        jobs = []
        for path in paths:
            if path in self._cache or path in self._tokens:
                continue
            token = CancelToken()
            self._tokens[path] = token
            jobs.append((path, token))
        if not jobs:
            return
        size = QtCore.QSize(dpix(self._size), dpix(self._size))

        def task():
            for path, token in jobs:
                if token.is_cancelled():
                    continue
                try:
                    image = load_thumbnail(path, size)
                except (OSError, RuntimeError) as e:
                    AppLogger.warning(f"Thumbnail load failed: {path}", exc=e)
                    image = None
                if token.is_cancelled():
                    continue
                self._dispatcher.invoke(lambda p=path, im=image, t=token: t.is_cancelled() or self.store(p, im))

        self._dispatcher.post(task)

    def store(self, path: str, image: QtGui.QImage | None) -> None:
        self._tokens.pop(path, None)
        self._cache[path] = QtGui.QPixmap.fromImage(image) if image is not None and not image.isNull() else QtGui.QPixmap()
        self._cache.move_to_end(path)
        while len(self._cache) > self.cache_limit:
            self._cache.popitem(last=False)
        self._on_loaded(path)

    def cancel(self, paths: Iterable[str]) -> None:
        for path in paths:
            token = self._tokens.pop(path, None)
            if token is not None:
                token.cancel()

    def cancel_all(self) -> None:
        for token in self._tokens.values():
            token.cancel()
        self._tokens.clear()

    def clear(self) -> None:
        self.cancel_all()
        self._cache.clear()

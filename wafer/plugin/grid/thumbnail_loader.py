from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Iterable

from PySide6 import QtCore, QtGui

from ...core.files.image_cache import MemoryLimitedImageCache
from ...core.logs import AppLogger
from ...core.store.settings import app_settings
from ...qt.common.dispatcher import CancelToken, Dispatcher
from ...qt.common.dpi import dpix
from ...qt.common.thread import utility_pool
from .handler import load_thumbnail


def shared_image_cache() -> MemoryLimitedImageCache:
    return MemoryLimitedImageCache(app_settings.get("window/cache_size", 500))


def long_side(image: QtGui.QImage | QtGui.QPixmap | None) -> int:
    return 0 if image is None or image.isNull() else max(image.width(), image.height())


class ThumbnailLoader:
    def __init__(self, on_loaded: Callable[[str], None], *, size: int, cache_limit: int, dispatcher: Dispatcher | None = None):
        self._on_loaded = on_loaded
        self._size = size
        self.cache_limit = cache_limit
        self._cache: OrderedDict[str, QtGui.QPixmap] = OrderedDict()
        self._natural: dict[str, int] = {}
        self._tokens: dict[str, CancelToken] = {}
        self._images = shared_image_cache()
        self._dispatcher = dispatcher or Dispatcher(pool=utility_pool)

    @property
    def size(self) -> int:
        return self._size

    def set_size(self, size: int) -> None:
        self._size = size

    def __contains__(self, path: str) -> bool:
        return path in self._cache

    def __len__(self) -> int:
        return len(self._cache)

    def get(self, path: str) -> QtGui.QPixmap | None:
        pixmap = self._cache.get(path)
        image = self._images.get(path)
        if long_side(image) > long_side(pixmap):
            return self.remember(path, QtGui.QPixmap.fromImage(image))
        if pixmap is not None:
            self._cache.move_to_end(path)
        return pixmap

    def sufficient(self, path: str) -> bool:
        best = max(long_side(self._cache.get(path)), long_side(self._images.peek(path)))
        return best >= min(dpix(self._size), self._natural.get(path, best + 1))

    def pending(self, path: str) -> bool:
        return path in self._tokens

    def request(self, paths: Iterable[str]) -> None:
        jobs = []
        for path in paths:
            if path in self._tokens or self.sufficient(path):
                continue
            token = CancelToken()
            self._tokens[path] = token
            jobs.append((path, token))
        if not jobs:
            return
        side = dpix(self._size)
        size = QtCore.QSize(side, side)

        def task():
            for path, token in jobs:
                if token.is_cancelled():
                    continue
                try:
                    image = load_thumbnail(path, size)
                except Exception as e:
                    AppLogger.warning(f"Thumbnail load failed: {path}", exc=e)
                    image = None
                if token.is_cancelled():
                    continue
                self._dispatcher.invoke(lambda p=path, im=image, t=token: t.is_cancelled() or self.store(p, im, side))

        self._dispatcher.post(task)

    def store(self, path: str, image: QtGui.QImage | None, requested: int | None = None) -> None:
        self._tokens.pop(path, None)
        loaded = long_side(image)
        if loaded < (requested or dpix(self._size)):
            self._natural[path] = loaded
        if loaded:
            if long_side(self._images.peek(path)) < loaded:
                self._images[path] = image
            if long_side(self._cache.get(path)) < loaded:
                self.remember(path, QtGui.QPixmap.fromImage(image))
        elif path not in self._cache:
            self.remember(path, QtGui.QPixmap())
        self._on_loaded(path)

    def remember(self, path: str, pixmap: QtGui.QPixmap) -> QtGui.QPixmap:
        self._cache[path] = pixmap
        self._cache.move_to_end(path)
        while len(self._cache) > self.cache_limit:
            self._cache.popitem(last=False)
        return pixmap

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
        self._natural.clear()

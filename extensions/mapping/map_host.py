from __future__ import annotations

from functools import partial

from PySide6 import QtCore, QtGui

from wafer.plugin.grid.thumbnail_loader import ThumbnailLoader
from wafer.qt.common.dispatcher import Dispatcher
from wafer.qt.common.dpi import dpix
from wafer.qt.common.thread import utility_pool

from .hover_preview import HoverPreview

THUMB_BUCKETS = (64, 128, 256)
HOVER_BUCKETS = (128, 256, 512, 1024)
MEGABYTE = 1024 * 1024
THUMB_BUDGET = 256 * MEGABYTE
HOVER_BUDGET = 64 * MEGABYTE
BYTES_PER_PIXEL = 4


def thumb_bucket(size: float) -> int:
    return next((bucket for bucket in THUMB_BUCKETS if bucket >= size), THUMB_BUCKETS[-1])


def hover_bucket(size: int) -> int:
    return next((bucket for bucket in HOVER_BUCKETS if bucket >= size), HOVER_BUCKETS[-1])


def cache_limit(budget: int, bucket: int) -> int:
    side = dpix(bucket)
    return max(1, budget // (side * side * BYTES_PER_PIXEL))


def resize_loader(loader: ThumbnailLoader, bucket: int, budget: int) -> None:
    loader.set_size(bucket)
    loader.cache_limit = cache_limit(budget, bucket)


def cancel_loaders(thumbs: ThumbnailLoader, hover: ThumbnailLoader) -> None:
    thumbs.cancel_all()
    hover.cancel_all()


class MapHost(QtCore.QObject):
    def __init__(self, parent):
        super().__init__(parent)
        self.dispatcher = Dispatcher(pool=utility_pool, parent=self)
        thumb_size, hover_size = THUMB_BUCKETS[0], hover_bucket(256)
        self.thumbs = ThumbnailLoader(self.on_thumbnail, size=thumb_size, cache_limit=cache_limit(THUMB_BUDGET, thumb_size), dispatcher=self.dispatcher)
        self.hover_thumbs = ThumbnailLoader(self.on_hover_thumbnail, size=hover_size, cache_limit=cache_limit(HOVER_BUDGET, hover_size), dispatcher=self.dispatcher)
        self.preview = HoverPreview()
        self.sources: dict[str, str] = {}
        self.views: list = []
        self.hover_size = 256
        self.hover_path: str | None = None
        self.hover_cursor = QtCore.QPoint()
        self.hover_key = 0
        self.destroyed.connect(partial(cancel_loaders, self.thumbs, self.hover_thumbs))
        self.destroyed.connect(self.preview.deleteLater)

    def thumbnail(self, path: str) -> QtGui.QPixmap | None:
        pixmap = self.thumbs.get(path)
        if pixmap is None:
            self.thumbs.request([path])
        return pixmap

    def set_display_size(self, size: float) -> None:
        resize_loader(self.thumbs, thumb_bucket(size), THUMB_BUDGET)

    def set_hover_size(self, size: int) -> None:
        self.hover_size = size
        if size:
            resize_loader(self.hover_thumbs, hover_bucket(size), HOVER_BUDGET)
        else:
            self.hide_hover()

    def show_hover(self, path: str, global_pos: QtCore.QPoint) -> None:
        if not self.hover_size:
            return
        pixmap = self.hover_thumbs.get(path)
        if pixmap is None:
            self.hover_thumbs.request([path])
            pixmap = self.thumbs.get(path) or QtGui.QPixmap()
        same = path == self.hover_path and pixmap.cacheKey() == self.hover_key and self.preview.isVisible()
        self.hover_path, self.hover_cursor, self.hover_key = path, global_pos, pixmap.cacheKey()
        if same:
            self.preview.place(global_pos)
            return
        self.preview.show_image(pixmap, path.replace("\\", "/").split("/")[-1], global_pos, self.hover_size)

    def hide_hover(self) -> None:
        self.hover_path = None
        self.hover_key = 0
        self.preview.hide()

    def on_hover_thumbnail(self, path: str) -> None:
        if path == self.hover_path:
            self.show_hover(path, self.hover_cursor)

    def on_thumbnail(self, path: str) -> None:
        for view in self.views:
            view.update_path(path)

    def context_for(self, paths: list[str]) -> dict:
        if not paths:
            return {}
        sources = list(dict.fromkeys(self.sources.get(path, path) for path in paths))
        return {"path": paths[-1], "paths": paths, "source": sources[-1], "sources": sources}

    def cancel_all(self) -> None:
        cancel_loaders(self.thumbs, self.hover_thumbs)
        self.hide_hover()

    def clear(self) -> None:
        self.cancel_all()
        self.thumbs.clear()
        self.hover_thumbs.clear()
        self.sources = {}

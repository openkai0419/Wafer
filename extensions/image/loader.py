from __future__ import annotations

from typing import TYPE_CHECKING

from wafer.plugin import BaseImageLoader
from wafer.core.profiling import profiler

if TYPE_CHECKING:
    import numpy as np
    from PySide6 import QtGui


class ImageFileLoader(BaseImageLoader):
    NAME = "image"
    EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
    PRIORITY = 100
    DEFAULT_ENABLED = True
    SCOPE = "*"

    @classmethod
    def preload(cls):
        from . import _decode  # noqa: F401

    @profiler.profile
    def load(self, path: str, size: int | None = None) -> np.ndarray | None:
        from ._decode import decode_numpy

        return decode_numpy(path, size)

    @profiler.profile
    def load_qimage(self, path: str, size: int | None = None) -> QtGui.QImage | None:
        from ._qimage import load_image

        return load_image(path, size)

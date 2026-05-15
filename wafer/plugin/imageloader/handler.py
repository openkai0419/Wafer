import numpy as np
from PIL import Image
from PySide6 import QtGui

from ...core.qt.image import numpy_to_qimage, pil_to_qimage
from ...utils.profiling import profiler
from ..registry import FilePluginRegistry
from .base import BaseImageLoader


class ImageLoaderResolver:
    def __init__(self):
        self.registry = FilePluginRegistry()

    def resolve(self, path: str) -> type[BaseImageLoader] | None:
        return self.registry.resolve(path)

    def resolve_chain(self, path: str) -> list[type[BaseImageLoader]]:
        return self.registry.resolve_chain(path)

    @profiler.profile
    def load(self, path: str, size: int | None = None) -> np.ndarray | None:
        for plugin_cls in self.registry.resolve_chain(path):
            if not plugin_cls.can_handle(path):
                continue
            instance = self.registry.instance(plugin_cls.NAME)
            if instance is None:
                continue
            result = instance.load(path, size)
            if result is not None:
                return result
            pil = instance.load_pil(path, size)
            if pil is not None:
                if pil.mode not in ("RGB", "RGBA", "L"):
                    pil = pil.convert("RGB")
                return np.asarray(pil)
        return None

    @profiler.profile
    def load_pil(self, path: str, size: int | None = None) -> Image.Image | None:
        for plugin_cls in self.registry.resolve_chain(path):
            if not plugin_cls.can_handle(path):
                continue
            instance = self.registry.instance(plugin_cls.NAME)
            if instance is None:
                continue
            pil = instance.load_pil(path, size)
            if pil is not None:
                return pil
            arr = instance.load(path, size)
            if arr is not None:
                mode = "L" if arr.ndim == 2 else ("RGBA" if arr.ndim == 3 and arr.shape[2] == 4 else "RGB")
                return Image.fromarray(arr, mode=mode)
        return None

    @profiler.profile
    def load_qimage(self, path: str, size: int | None = None) -> QtGui.QImage | None:
        for plugin_cls in self.registry.resolve_chain(path):
            if not plugin_cls.can_handle(path):
                continue
            instance = self.registry.instance(plugin_cls.NAME)
            if instance is None:
                continue
            image = instance.load_qimage(path, size)
            if image is not None and not image.isNull():
                return image
            pil = instance.load_pil(path, size)
            if pil is not None:
                return pil_to_qimage(pil)
            arr = instance.load(path, size)
            if arr is not None:
                return numpy_to_qimage(arr)
        return None


image_loader_resolver = ImageLoaderResolver()

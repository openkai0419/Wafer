import numpy as np
from PIL import Image
from PySide6 import QtGui

from wafer.plugin.imageloader.base import BaseImageLoader
from wafer.plugin.imageloader.handler import ImageLoaderResolver


def _resolver_with(plugin_cls):
    resolver = ImageLoaderResolver()
    resolver.registry.register(plugin_cls)
    return resolver


class _BrokenPreloadLoader(BaseImageLoader):
    NAME = "broken_preload"
    EXTENSIONS = (".png",)

    @classmethod
    def preload(cls):
        raise ImportError("DLL load failed while importing cv2")


class _CountingPreloadLoader(BaseImageLoader):
    NAME = "counting_preload"
    EXTENSIONS = (".png",)
    preloaded = 0

    @classmethod
    def preload(cls):
        cls.preloaded += 1


def test_a_failing_preload_is_logged_and_the_other_loaders_still_preload(monkeypatch):
    logged = []
    monkeypatch.setattr("wafer.plugin.imageloader.handler.AppLogger.warning", lambda message, **kwargs: logged.append(message))
    monkeypatch.setattr(_CountingPreloadLoader, "preloaded", 0)
    resolver = ImageLoaderResolver()
    resolver.registry.register(_BrokenPreloadLoader)
    resolver.registry.register(_CountingPreloadLoader)

    resolver.preload()

    assert _CountingPreloadLoader.preloaded == 1
    assert len(logged) == 1 and "broken_preload" in logged[0] and "Plugin Manager" in logged[0]


class _DirectQImageLoader(BaseImageLoader):
    NAME = "direct_qimage"
    EXTENSIONS = (".png",)

    def load_qimage(self, path: str, size: int | None = None):
        image = QtGui.QImage(3, 4, QtGui.QImage.Format_RGB32)
        image.fill(QtGui.QColor("red"))
        return image

    def load_pil(self, path: str, size: int | None = None):
        raise AssertionError("load_pil should not be called when load_qimage succeeds")

    def load(self, path: str, size: int | None = None):
        raise AssertionError("load should not be called when load_qimage succeeds")


class _PilFallbackLoader(BaseImageLoader):
    NAME = "pil_fallback"
    EXTENSIONS = (".png",)

    def load_pil(self, path: str, size: int | None = None):
        return Image.new("RGB", (5, 6), "blue")


class _NumpyFallbackLoader(BaseImageLoader):
    NAME = "numpy_fallback"
    EXTENSIONS = (".png",)

    def load(self, path: str, size: int | None = None):
        return np.zeros((7, 8, 3), dtype=np.uint8)


def test_load_qimage_prefers_direct_qimage():
    image = _resolver_with(_DirectQImageLoader).load_qimage("sample.png")

    assert isinstance(image, QtGui.QImage)
    assert image.width() == 3
    assert image.height() == 4


def test_load_qimage_falls_back_to_pil():
    image = _resolver_with(_PilFallbackLoader).load_qimage("sample.png")

    assert isinstance(image, QtGui.QImage)
    assert image.width() == 5
    assert image.height() == 6


def test_load_qimage_falls_back_to_numpy():
    image = _resolver_with(_NumpyFallbackLoader).load_qimage("sample.png")

    assert isinstance(image, QtGui.QImage)
    assert image.width() == 8
    assert image.height() == 7

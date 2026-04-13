from __future__ import annotations

import hashlib
import sys
import time
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from wafer.core.platform.thumbnails import FileThumbnailer
from wafer.plugin import BaseSingletonCollector, CollectorResult
from wafer.utils.logs import AppLogger

if TYPE_CHECKING:
    from ._inference import BlipInference

from ._downloader import ensure_model

_CACHE_MAX = 5000
_ENGINE_IDLE_TIMEOUT = 120.0
_TORCH_CUDA_INDEX = "https://download.pytorch.org/whl/cu124"


class BlipCaptionerCollector(BaseSingletonCollector):
    NAME = "blip"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 100
    DEFAULT_ENABLED = False

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None):
        from wafer.plugin.installer import install_packages

        gpu_ok = False
        if sys.platform == "win32":
            gpu_ok = install_packages(
                plugin_dir,
                ["torch==2.11.0", "torchvision==0.26.0"],
                on_progress,
                extra_args=["--index-url", _TORCH_CUDA_INDEX],
            )
        else:
            gpu_ok = install_packages(
                plugin_dir,
                ["torch==2.11.0", "torchvision==0.26.0"],
                on_progress,
            )

        if not gpu_ok:
            AppLogger.warning("BLIP: CUDA torch unavailable, falling back to CPU torch")
            install_packages(
                plugin_dir,
                ["torch==2.11.0", "torchvision==0.26.0"],
                on_progress,
                extra_args=["--index-url", "https://download.pytorch.org/whl/cpu"],
            )

        install_packages(plugin_dir, ["transformers==4.57.6", "safetensors==0.7.0"], on_progress)
        ensure_model()
        cls._verify_device()

    @staticmethod
    def _verify_device():
        try:
            import torch

            if torch.cuda.is_available():
                AppLogger.info(f"BLIP GPU verified: {torch.cuda.get_device_name(0)}")
            else:
                AppLogger.warning("BLIP: CUDA not available. Inference will run on CPU and be significantly slower")
        except ImportError as err:
            raise RuntimeError("BLIP: torch not importable after install") from err

    def __init__(self):
        self._engine: BlipInference | None = None
        self._engine_lock = threading.Lock()
        self._thumbnailer = FileThumbnailer()
        self._hash_cache: OrderedDict[str, str] = OrderedDict()
        self._pixel_cache: OrderedDict[str, str] = OrderedDict()
        self._last_used: float = 0.0
        self._idle_timer: threading.Timer | None = None

    def _ensure_engine(self):
        if self._engine is not None:
            return
        with self._engine_lock:
            if self._engine is not None:
                return
            from ._inference import BlipInference

            model_dir = ensure_model()
            self._engine = BlipInference(model_dir)

    def _touch(self):
        self._last_used = time.monotonic()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        t = threading.Timer(_ENGINE_IDLE_TIMEOUT, self._check_idle)
        t.daemon = True
        t.start()
        self._idle_timer = t

    def _check_idle(self):
        elapsed = time.monotonic() - self._last_used
        if elapsed < _ENGINE_IDLE_TIMEOUT:
            return
        with self._engine_lock:
            if self._engine is None:
                return
            if time.monotonic() - self._last_used < _ENGINE_IDLE_TIMEOUT:
                return
            self._engine = None
            AppLogger.info("BLIP engine unloaded (idle timeout)")

    @staticmethod
    def _cache_put(cache: OrderedDict, key: str, value: str):
        cache[key] = value
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        file_hash = file_info[2] if len(file_info) >= 3 else None

        if file_hash and file_hash in self._hash_cache:
            self._hash_cache.move_to_end(file_hash)
            return CollectorResult(
                source=path,
                status=True,
                meta_info={"caption": self._hash_cache[file_hash]},
            )

        self._ensure_engine()
        self._touch()

        thumb = self._thumbnailer.get_thumbnail(path, size=384)
        if thumb is None:
            return CollectorResult(source=path, status=False)

        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        if pixel_hash in self._pixel_cache:
            self._pixel_cache.move_to_end(pixel_hash)
            caption = self._pixel_cache[pixel_hash]
            if file_hash:
                self._cache_put(self._hash_cache, file_hash, caption)
            return CollectorResult(source=path, status=True, meta_info={"caption": caption})

        try:
            caption = self._engine.predict(thumb)
        except Exception as e:
            AppLogger.warning(f"BLIP inference failed: {path}", exc=e)
            return CollectorResult(source=path, status=False)

        self._cache_put(self._pixel_cache, pixel_hash, caption)
        if file_hash:
            self._cache_put(self._hash_cache, file_hash, caption)

        return CollectorResult(source=path, status=True, meta_info={"caption": caption})

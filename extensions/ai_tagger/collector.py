from __future__ import annotations

import hashlib
import time
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from wafer.plugin import BaseSingletonCollector, CollectorResult
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.utils.logs import AppLogger

if TYPE_CHECKING:
    from ._inference import WD14Inference

from ._downloader import ensure_model

GENERAL_THRESHOLD = 0.057
CHARACTER_THRESHOLD = 0.8
_CACHE_MAX = 5000
_ENGINE_IDLE_TIMEOUT = 120.0


class WD14TaggerCollector(BaseSingletonCollector):
    NAME = "wd14"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 150

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None):
        from wafer.plugin.installer import install_packages

        model_error: list[Exception] = []
        model_thread = threading.Thread(target=cls._download_model, args=(model_error,), daemon=True)
        model_thread.start()

        success, _ = install_packages(plugin_dir, ["onnxruntime-gpu==1.23.2"], on_progress, is_cancelled=is_cancelled)
        if not success:
            AppLogger.warning("onnxruntime-gpu install failed, falling back to CPU-only onnxruntime")
            install_packages(plugin_dir, ["onnxruntime==1.23.2"], on_progress, is_cancelled=is_cancelled)
        else:
            install_packages(
                plugin_dir,
                ["nvidia-cudnn-cu12==9.5.1.17"],
                on_progress,
                no_deps=True,
                is_cancelled=is_cancelled,
            )

        model_thread.join()
        if model_error:
            raise model_error[0]

    @staticmethod
    def _download_model(errors: list[Exception]):
        try:
            ensure_model()
        except Exception as e:
            AppLogger.warning(f"WD14 model download failed: {e}", exc=e)
            errors.append(e)

    def __init__(self):
        self._engine: WD14Inference | None = None
        self._engine_lock = threading.Lock()
        self._hash_cache: OrderedDict[str, dict] = OrderedDict()
        self._pixel_cache: OrderedDict[str, dict] = OrderedDict()
        self._last_used: float = 0.0
        self._idle_timer: threading.Timer | None = None

    def _ensure_engine(self):
        if self._engine is not None:
            return
        with self._engine_lock:
            if self._engine is not None:
                return
            from ._inference import WD14Inference

            model_dir = ensure_model()
            self._engine = WD14Inference(model_dir)
            AppLogger.info(f"WD14 engine loaded: {self._engine.session.get_providers()[0]}")

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
        unloaded = False
        with self._engine_lock:
            if self._engine is None:
                return
            if time.monotonic() - self._last_used < _ENGINE_IDLE_TIMEOUT:
                return
            self._engine = None
            unloaded = True
        if unloaded:
            AppLogger.info("WD14 engine unloaded (idle timeout)")

    @staticmethod
    def _cache_put(cache: OrderedDict, key: str, value: dict):
        cache[key] = value
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)

    @staticmethod
    def _build_tags(result: dict) -> dict:
        ratings = result["ratings"]
        top_rating = max(ratings, key=ratings.get)

        tags = {
            "rating": top_rating,
        }
        if result["character"]:
            tags["character"] = ", ".join(result["character"].keys())
        if result["general"]:
            tags["tags"] = ", ".join(result["general"].keys())
        return tags

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        file_hash = file_info[2] if len(file_info) >= 3 else None

        if file_hash and file_hash in self._hash_cache:
            self._hash_cache.move_to_end(file_hash)
            return CollectorResult(
                source=path,
                status=True,
                tags=self._hash_cache[file_hash],
            )

        self._ensure_engine()
        self._touch()

        thumb = image_loader_resolver.load_pil(path, size=self._engine.input_height)
        if thumb is None:
            return CollectorResult(source=path, status=False)

        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        if pixel_hash in self._pixel_cache:
            self._pixel_cache.move_to_end(pixel_hash)
            tags = self._pixel_cache[pixel_hash]
            if file_hash:
                self._cache_put(self._hash_cache, file_hash, tags)
            return CollectorResult(source=path, status=True, tags=tags)

        try:
            result = self._engine.predict(thumb, general_threshold=GENERAL_THRESHOLD, character_threshold=CHARACTER_THRESHOLD)
        except Exception as e:
            AppLogger.warning(f"WD14 inference failed: {path}", exc=e)
            return CollectorResult(source=path, status=False)

        tags = self._build_tags(result)
        self._cache_put(self._pixel_cache, pixel_hash, tags)
        if file_hash:
            self._cache_put(self._hash_cache, file_hash, tags)

        return CollectorResult(source=path, status=True, tags=tags)

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
    from ._inference import FlorenceInference

from ._downloader import ensure_model
from .settings import TAG_MAP, enabled_tasks, florence_config

_CACHE_MAX = 5000
_ENGINE_IDLE_TIMEOUT = 120.0

POST_INSTALL_VERSION = "1"


class FlorenceCollector(BaseSingletonCollector):
    NAME = "florence"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 50
    MAX_WORKERS = 1
    MAX_TIMEOUT = 1200.0
    DEFAULT_ENABLED = False

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        if on_progress:
            on_progress(phase="Downloading Florence-2 model…")
        ensure_model(version=POST_INSTALL_VERSION)

    def __init__(self):
        self._engine: FlorenceInference | None = None
        self._engine_lock = threading.Lock()
        self._loaded_variant: str | None = None
        self._engine_failed: bool = False
        self._hash_cache: OrderedDict[str, dict] = OrderedDict()
        self._pixel_cache: OrderedDict[str, dict] = OrderedDict()
        self._last_used: float = 0.0
        self._idle_timer: threading.Timer | None = None
        self._settings = florence_config.load()

    def _ensure_engine(self):
        variant = self._settings.get("model_variant", "base")
        if self._engine is not None and self._loaded_variant == variant:
            return
        with self._engine_lock:
            if self._engine_failed:
                raise RuntimeError("Florence-2 engine initialization previously failed")
            if self._engine is not None and self._loaded_variant == variant:
                return
            if self._engine is not None:
                self._engine = None
                AppLogger.info(f"Florence-2 engine unloaded for variant switch: {self._loaded_variant} -> {variant}")
            from ._inference import FlorenceInference

            try:
                model_dir = ensure_model(variant, version=POST_INSTALL_VERSION)
                self._engine = FlorenceInference(model_dir)
                self._loaded_variant = variant
            except Exception as exc:
                self._engine_failed = True
                AppLogger.error(f"Florence-2 engine initialization failed: {exc}")
                raise

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
            self._loaded_variant = None
            unloaded = True
        if unloaded:
            AppLogger.info("Florence-2 engine unloaded (idle timeout)")

    @staticmethod
    def _cache_put(cache: OrderedDict, key: str, value: dict):
        cache[key] = value
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)

    def _run_tasks(self, image, settings: dict | None = None) -> dict:
        engine = self._engine
        if engine is None:
            raise RuntimeError("Florence-2 engine is not loaded")
        s = settings or self._settings
        tasks = enabled_tasks(s)
        max_new_tokens = s.get("max_new_tokens", 1024)
        num_beams = s.get("num_beams", 3)
        tags = {}
        for task in tasks:
            result = engine.predict(image, task, max_new_tokens=max_new_tokens, num_beams=num_beams)
            tags[TAG_MAP[task]] = result
        return tags

    def on_notify(self, payload=None) -> None:
        old_variant = self._settings.get("model_variant")
        self._settings = florence_config.load()
        new_variant = self._settings.get("model_variant")
        self._hash_cache.clear()
        self._pixel_cache.clear()
        if old_variant != new_variant:
            with self._engine_lock:
                self._engine = None
                self._loaded_variant = None
            AppLogger.info(f"Florence-2 engine unloaded for variant switch: {old_variant} -> {new_variant}")
        AppLogger.info(f"Florence-2 settings reloaded (caches cleared): {self._settings}")

    def shutdown(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._engine_lock:
            self._engine = None
            self._loaded_variant = None
        self._hash_cache.clear()
        self._pixel_cache.clear()

    def on_request(self, action, payload, msg):
        if action == "florence.preview":
            return self._handle_preview(payload)
        if action == "florence.device_info":
            return self._get_device_info()
        return None

    def _handle_preview(self, payload):
        path = payload.get("path", "")
        settings = payload.get("settings", {})
        if not path:
            return {"error": "no_path"}
        self._ensure_engine()
        self._touch()
        thumb = image_loader_resolver.load_pil(path, size=384)
        if thumb is None:
            return {"error": "thumbnail_failed"}
        try:
            tags = self._run_tasks(thumb, settings)
        except Exception as e:
            AppLogger.warning(f"Florence-2 preview failed: {path}", exc=e)
            return {"error": str(e)}
        return {"tags": tags, "path": path}

    @staticmethod
    def _get_device_info():
        try:
            import torch

            if torch.cuda.is_available():
                return {"device": "cuda", "device_name": torch.cuda.get_device_name(0)}
            return {"device": "cpu", "device_name": "CPU"}
        except ImportError:
            return {"device": "unknown", "device_name": "torch not available"}

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

        thumb = image_loader_resolver.load_pil(path, size=384)
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
            tags = self._run_tasks(thumb)
        except Exception as e:
            AppLogger.warning(f"Florence-2 inference failed: {path}", exc=e)
            return CollectorResult(source=path, status=False)

        self._cache_put(self._pixel_cache, pixel_hash, tags)
        if file_hash:
            self._cache_put(self._hash_cache, file_hash, tags)

        return CollectorResult(source=path, status=True, tags=tags)

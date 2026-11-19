from __future__ import annotations

import hashlib
import threading
import time
from abc import abstractmethod
from collections import OrderedDict
from typing import TYPE_CHECKING, Any, ClassVar

from ...core.logs import AppLogger
from ..imageloader.handler import image_loader_resolver
from .base import BaseSingletonCollector, CollectorResult

if TYPE_CHECKING:
    from PIL import Image

    from ..config import PluginConfig


class BaseInferenceCollector(BaseSingletonCollector):
    CACHE_MAX: int = 5000
    ENGINE_IDLE_TIMEOUT: float = 30.0
    KEEP_ACTIVE_ENGINE: bool = True
    MODEL_KEY: str = "model"
    DEFAULT_MODEL: str = ""

    plugin_config: ClassVar[PluginConfig]

    def __init__(self):
        self._engines: dict[str, Any] = {}
        self._last_used: dict[str, float] = {}
        self._engine_lock = threading.Lock()
        self._idle_timer: threading.Timer | None = None
        self._hash_cache: OrderedDict[str, dict] = OrderedDict()
        self._pixel_cache: OrderedDict[str, dict] = OrderedDict()
        self._settings = self.plugin_config.load()

    @abstractmethod
    def load_engine(self, model: str) -> Any: ...

    @abstractmethod
    def infer(self, engine, thumb: Image.Image, model: str) -> dict: ...

    @abstractmethod
    def preview(self, engine, thumb: Image.Image, settings: dict) -> dict: ...

    @abstractmethod
    def device_info(self) -> dict: ...

    @property
    def model(self) -> str:
        return self._settings.get(self.MODEL_KEY) or self.DEFAULT_MODEL

    def engine(self, model: str):
        with self._engine_lock:
            self._last_used[model] = time.monotonic()
            engine = self._engines.get(model)
            if engine is None:
                keep = self.model if self.KEEP_ACTIVE_ENGINE else None
                for loaded in [m for m in self._engines if m != keep]:
                    del self._engines[loaded]
                    AppLogger.info(f"{self.NAME} engine '{loaded}' unloaded for '{model}'")
                engine = self.load_engine(model)
                self._engines[model] = engine
            if self._idle_timer is None:
                self._start_idle_timer(self.ENGINE_IDLE_TIMEOUT)
        return engine

    def _start_idle_timer(self, delay: float):
        self._idle_timer = threading.Timer(delay, self.unload_idle_engines)
        self._idle_timer.daemon = True
        self._idle_timer.start()

    def unload_idle_engines(self):
        now = time.monotonic()
        with self._engine_lock:
            self._idle_timer = None
            idle = [m for m in self._engines if now - self._last_used.get(m, 0.0) >= self.ENGINE_IDLE_TIMEOUT]
            for model in idle:
                del self._engines[model]
            if self._engines:
                oldest = min(self._last_used.get(m, now) for m in self._engines)
                self._start_idle_timer(oldest + self.ENGINE_IDLE_TIMEOUT - now)
        for model in idle:
            AppLogger.info(f"{self.NAME} engine '{model}' unloaded (idle timeout)")

    def unload_engines(self, keep: str | None = None):
        with self._engine_lock:
            for model in [m for m in self._engines if m != keep]:
                del self._engines[model]
            if not self._engines and self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None

    def cache_put(self, cache: OrderedDict, key: str, value: dict):
        cache[key] = value
        if len(cache) > self.CACHE_MAX:
            cache.popitem(last=False)

    def on_notify(self, payload=None) -> None:
        old_model = self.model
        self._settings = self.plugin_config.load()
        self._hash_cache.clear()
        self._pixel_cache.clear()
        if self.model != old_model:
            self.unload_engines(keep=self.model)
        AppLogger.info(f"{self.NAME} settings reloaded (caches cleared): {self._settings}")

    def shutdown(self):
        self.unload_engines()
        self._hash_cache.clear()
        self._pixel_cache.clear()

    def on_request(self, action, payload, msg):
        if action == f"{self.NAME}.preview":
            return self._handle_preview(payload)
        if action == f"{self.NAME}.device_info":
            return self.device_info()
        return None

    def _handle_preview(self, payload):
        path = payload.get("path", "")
        settings = payload.get("settings", {})
        if not path:
            return {"error": "no_path"}
        model = settings.get(self.MODEL_KEY) or self.model
        engine = self.engine(model)
        thumb = image_loader_resolver.load_pil(path, size=engine.input_size)
        if thumb is None:
            return {"error": "thumbnail_failed"}
        started = time.perf_counter()
        try:
            result = self.preview(engine, thumb, settings)
        except Exception as e:
            AppLogger.warning(f"{self.NAME} '{model}' preview failed: {path}", exc=e)
            return {"error": str(e)}
        return {**result, "path": path, "model": model, "elapsed_ms": round((time.perf_counter() - started) * 1000)}

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        file_hash = file_info[2] if len(file_info) >= 3 else None
        if file_hash and file_hash in self._hash_cache:
            self._hash_cache.move_to_end(file_hash)
            return CollectorResult(source=path, status=True, tags=self._hash_cache[file_hash])

        model = self.model
        engine = self.engine(model)
        thumb = image_loader_resolver.load_pil(path, size=engine.input_size)
        if thumb is None:
            return CollectorResult(source=path, status=False)

        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        tags = self._pixel_cache.get(pixel_hash)
        if tags is not None:
            self._pixel_cache.move_to_end(pixel_hash)
        else:
            try:
                tags = self.infer(engine, thumb, model)
            except Exception as e:
                AppLogger.warning(f"{self.NAME} '{model}' inference failed: {path}", exc=e)
                return CollectorResult(source=path, status=False)
            self.cache_put(self._pixel_cache, pixel_hash, tags)
        if file_hash:
            self.cache_put(self._hash_cache, file_hash, tags)
        return CollectorResult(source=path, status=True, tags=tags)

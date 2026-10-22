from __future__ import annotations

import hashlib
import time
import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

from wafer.plugin import BaseSingletonCollector, CollectorResult
from wafer.plugin.imageloader.handler import image_loader_resolver
from wafer.core.logs import AppLogger

if TYPE_CHECKING:
    from ._inference import TaggerInference

from ._downloader import DEFAULT_MODEL, ensure_default_model
from ._models import NAMED_CATEGORIES, load_spec
from .settings import parse_blacklist, wd14_config

_CACHE_MAX = 5000
_ENGINE_IDLE_TIMEOUT = 30.0

POST_INSTALL_VERSION = "1"


class WD14TaggerCollector(BaseSingletonCollector):
    NAME = "wd14"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 150
    MAX_WORKERS = 1
    MAX_TIMEOUT = 1800.0

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        if on_progress:
            on_progress(phase="Downloading WD14 model…")
        ensure_default_model(version=POST_INSTALL_VERSION)

    def __init__(self):
        self._engines: dict[str, TaggerInference] = {}
        self._last_used: dict[str, float] = {}
        self._engine_lock = threading.Lock()
        self._hash_cache: OrderedDict[str, dict] = OrderedDict()
        self._pixel_cache: OrderedDict[str, dict] = OrderedDict()
        self._idle_timer: threading.Timer | None = None
        self._settings = wd14_config.load()

    @property
    def model(self) -> str:
        return self._settings.get("model") or DEFAULT_MODEL

    def engine(self, model: str) -> TaggerInference:
        with self._engine_lock:
            self._last_used[model] = time.monotonic()
            engine = self._engines.get(model)
            if engine is None:
                from ._inference import TaggerInference

                for loaded in [m for m in self._engines if m != self.model]:
                    del self._engines[loaded]
                if model == DEFAULT_MODEL:
                    ensure_default_model(version=POST_INSTALL_VERSION)
                engine = TaggerInference(load_spec(model))
                self._engines[model] = engine
            if self._idle_timer is None:
                self._idle_timer = threading.Timer(_ENGINE_IDLE_TIMEOUT, self.unload_idle_engines)
                self._idle_timer.daemon = True
                self._idle_timer.start()
        return engine

    def unload_idle_engines(self):
        now = time.monotonic()
        with self._engine_lock:
            self._idle_timer = None
            idle = [m for m in self._engines if now - self._last_used.get(m, 0.0) >= _ENGINE_IDLE_TIMEOUT]
            for model in idle:
                del self._engines[model]
            if self._engines:
                self._idle_timer = threading.Timer(_ENGINE_IDLE_TIMEOUT, self.unload_idle_engines)
                self._idle_timer.daemon = True
                self._idle_timer.start()
        for model in idle:
            AppLogger.info(f"Tagger '{model}' unloaded (idle timeout)")

    @staticmethod
    def _cache_put(cache: OrderedDict, key: str, value: dict):
        cache[key] = value
        if len(cache) > _CACHE_MAX:
            cache.popitem(last=False)

    def _build_tags(self, result: dict, settings: dict | None = None) -> dict:
        s = settings or self._settings
        ratings = result.get("rating", {})
        blacklist = set(parse_blacklist(s.get("tag_blacklist", ""))) if s.get("enable_blacklist", True) else set()

        tags = {}
        if s.get("enable_rating", True) and ratings:
            mode = s.get("rating_mode", "top")
            top_rating = max(ratings, key=ratings.get)
            if mode == "name":
                tags["rating"] = top_rating
            elif mode == "top":
                tags["rating"] = top_rating
                tags["rating_score"] = str(round(ratings[top_rating], 4))
            elif mode == "all":
                for name, score in ratings.items():
                    tags[f"rating_{name}"] = str(round(score, 4))

        if s.get("enable_character", True):
            for category in NAMED_CATEGORIES:
                if result.get(category):
                    tags[category] = ", ".join(result[category])
        if s.get("enable_tags", True):
            for category, key in (("general", "tags"), ("meta", "meta")):
                filtered = [k for k in result.get(category, {}) if k not in blacklist]
                if filtered:
                    tags[key] = ", ".join(filtered)
        return tags

    def on_notify(self, payload=None) -> None:
        self._settings = wd14_config.load()
        self._hash_cache.clear()
        self._pixel_cache.clear()
        AppLogger.info(f"WD14 settings reloaded (caches cleared): {self._settings}")

    def shutdown(self):
        with self._engine_lock:
            if self._idle_timer is not None:
                self._idle_timer.cancel()
                self._idle_timer = None
            self._engines.clear()
        self._hash_cache.clear()
        self._pixel_cache.clear()

    def on_request(self, action, payload, msg):
        if action == "wd14.preview":
            return self._handle_preview(payload)
        if action == "wd14.device_info":
            return self._get_device_info()
        return None

    def _handle_preview(self, payload):
        path = payload.get("path", "")
        settings = payload.get("settings", {})
        if not path:
            return {"error": "no_path"}
        model = settings.get("model") or self.model
        engine = self.engine(model)
        thumb = image_loader_resolver.load_pil(path, size=engine.input_size)
        if thumb is None:
            return {"error": "thumbnail_failed"}
        general_th = settings.get("general_threshold", self._settings.get("general_threshold", 0.057))
        character_th = settings.get("character_threshold", self._settings.get("character_threshold", 0.8))
        started = time.perf_counter()
        try:
            result = engine.predict(thumb, general_threshold=general_th, character_threshold=character_th)
        except Exception as e:
            AppLogger.warning(f"Tagger '{model}' preview failed: {path}", exc=e)
            return {"error": str(e)}
        return {**result, "path": path, "model": model, "elapsed_ms": round((time.perf_counter() - started) * 1000)}

    @staticmethod
    def _get_device_info():
        try:
            import onnxruntime as ort

            from ._inference import GPU_PROVIDERS

            providers = ort.get_available_providers()
            for p in GPU_PROVIDERS:
                if p in providers:
                    return {"device": p.replace("ExecutionProvider", ""), "device_name": p}
            return {"device": "CPU", "device_name": "CPUExecutionProvider"}
        except ImportError:
            return {"device": "unknown", "device_name": "onnxruntime not available"}

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        file_hash = file_info[2] if len(file_info) >= 3 else None

        if file_hash and file_hash in self._hash_cache:
            self._hash_cache.move_to_end(file_hash)
            return CollectorResult(
                source=path,
                status=True,
                tags=self._hash_cache[file_hash],
            )

        model = self.model
        engine = self.engine(model)
        thumb = image_loader_resolver.load_pil(path, size=engine.input_size)
        if thumb is None:
            return CollectorResult(source=path, status=False)

        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        if pixel_hash in self._pixel_cache:
            self._pixel_cache.move_to_end(pixel_hash)
            tags = self._pixel_cache[pixel_hash]
            if file_hash:
                self._cache_put(self._hash_cache, file_hash, tags)
            return CollectorResult(source=path, status=True, tags=tags)

        general_th = self._settings.get("general_threshold", 0.057)
        character_th = self._settings.get("character_threshold", 0.8)
        try:
            result = engine.predict(thumb, general_threshold=general_th, character_threshold=character_th)
        except Exception as e:
            AppLogger.warning(f"Tagger '{model}' inference failed: {path}", exc=e)
            return CollectorResult(source=path, status=False)

        tags = {**self._build_tags(result), "model": model}
        self._cache_put(self._pixel_cache, pixel_hash, tags)
        if file_hash:
            self._cache_put(self._hash_cache, file_hash, tags)

        return CollectorResult(source=path, status=True, tags=tags)

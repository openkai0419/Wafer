from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from wafer.plugin import BaseInferenceCollector, CollectorResult
from wafer.core.logs import AppLogger

if TYPE_CHECKING:
    from PIL import Image

    from ._inference import FlorenceInference

from ._downloader import DEFAULT_VARIANT, ensure_model
from .settings import TAG_MAP, enabled_tasks, florence_config

POST_INSTALL_VERSION = "1"
INFER_BATCH = 4


class FlorenceCollector(BaseInferenceCollector):
    NAME = "florence"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 12
    MAX_WORKERS = 1
    MAX_TIMEOUT = 1200.0
    DEFAULT_ENABLED = False
    ENGINE_IDLE_TIMEOUT = 120.0
    KEEP_ACTIVE_ENGINE = False
    MODEL_KEY = "model_variant"
    DEFAULT_MODEL = DEFAULT_VARIANT
    plugin_config = florence_config

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        if on_progress:
            on_progress(phase="Downloading Florence-2 model…")
        ensure_model(version=POST_INSTALL_VERSION)

    def __init__(self):
        super().__init__()
        self._engine_failed = False
        self.stopping = threading.Event()

    def load_engine(self, model: str) -> FlorenceInference:
        if self.stopping.is_set():
            raise RuntimeError("Florence-2 engine is not loaded while stopping")
        if self._engine_failed:
            raise RuntimeError("Florence-2 engine initialization previously failed")
        from ._inference import FlorenceInference

        try:
            return FlorenceInference(ensure_model(model, version=POST_INSTALL_VERSION))
        except Exception as exc:
            self._engine_failed = True
            AppLogger.error(f"Florence-2 engine initialization failed: {exc}")
            raise

    def run_tasks(self, engine: FlorenceInference, image, settings: dict) -> dict:
        max_new_tokens = settings.get("max_new_tokens", 1024)
        num_beams = settings.get("num_beams", 3)
        return {TAG_MAP[task]: engine.predict(image, task, max_new_tokens=max_new_tokens, num_beams=num_beams) for task in enabled_tasks(settings)}

    def run_tasks_batch(self, model: str, images: list, settings: dict) -> list[dict] | None:
        max_new_tokens = settings.get("max_new_tokens", 1024)
        num_beams = settings.get("num_beams", 3)
        texts = {}
        for task in enabled_tasks(settings):
            if self.stopping.is_set():
                return None
            texts[TAG_MAP[task]] = self.engine(model).predict_batch(images, task, max_new_tokens=max_new_tokens, num_beams=num_beams)
        return [{key: values[i] for key, values in texts.items()} for i in range(len(images))]

    def infer_each(self, model: str, waiting: dict) -> list[dict | None] | None:
        inferred = []
        for thumb, owners in waiting.values():
            if self.stopping.is_set():
                return None
            inferred.append(self.infer_or_none(self.engine(model), thumb, model, owners[0][0]))
        return inferred

    def process_batch(self, paths: list[str], file_info: dict[str, tuple]) -> list[CollectorResult]:
        results: dict[str, CollectorResult] = {}
        pending: list[tuple[str, str | None]] = []
        for path in paths:
            info = file_info[path]
            file_hash = info[2] if len(info) >= 3 else None
            tags = self.cached_tags(file_hash)
            if tags is None:
                pending.append((path, file_hash))
            else:
                results[path] = CollectorResult(source=path, status=True, tags=tags)
        for start in range(0, len(pending), INFER_BATCH):
            if self.stopping.is_set():
                break
            group = pending[start : start + INFER_BATCH]
            try:
                results.update(self.process_group(group))
            except Exception as e:
                if self.stopping.is_set():
                    break
                AppLogger.warning(f"{self.NAME} group failed: {[path for path, _ in group]}", exc=e)
                results.update({path: CollectorResult(source=path, status=False) for path, _ in group})
        return [results[path] for path in paths if path in results]

    def process_group(self, group: list[tuple[str, str | None]]) -> dict[str, CollectorResult]:
        model = self.model
        engine = self.engine(model)
        results: dict[str, CollectorResult] = {}
        waiting: dict[str, tuple[Image.Image, list[tuple[str, str | None]]]] = {}
        for path, file_hash in group:
            thumb = self.load_thumb(path, engine)
            if thumb is None:
                results[path] = CollectorResult(source=path, status=False)
                continue
            pixel_hash = self.pixel_key(thumb)
            tags = self.pixel_tags(pixel_hash)
            if tags is not None:
                self.remember(file_hash, pixel_hash, tags)
                results[path] = CollectorResult(source=path, status=True, tags=tags)
            else:
                waiting.setdefault(pixel_hash, (thumb, []))[1].append((path, file_hash))
        if not waiting:
            return results
        thumbs = [thumb for thumb, _ in waiting.values()]
        try:
            inferred = self.run_tasks_batch(model, thumbs, self._settings)
        except Exception as e:
            if self.stopping.is_set():
                return results
            AppLogger.warning(f"{self.NAME} '{model}' batch inference failed, retrying one by one: {[path for _, owners in waiting.values() for path, _ in owners]}", exc=e)
            inferred = self.infer_each(model, waiting)
        if inferred is None:
            return results
        for (pixel_hash, (_, owners)), tags in zip(waiting.items(), inferred):
            for path, file_hash in owners:
                if tags is None:
                    results[path] = CollectorResult(source=path, status=False)
                else:
                    self.remember(file_hash, pixel_hash, tags)
                    results[path] = CollectorResult(source=path, status=True, tags=tags)
        return results

    def infer_or_none(self, engine: FlorenceInference, thumb, model: str, path: str) -> dict | None:
        try:
            return self.infer(engine, thumb, model)
        except Exception as e:
            AppLogger.warning(f"{self.NAME} '{model}' inference failed: {path}", exc=e)
            return None

    def infer(self, engine: FlorenceInference, thumb, model: str) -> dict:
        return self.run_tasks(engine, thumb, self._settings)

    def preview(self, engine: FlorenceInference, thumb, settings: dict) -> dict:
        return {"tags": self.run_tasks(engine, thumb, settings or self._settings)}

    def shutdown(self):
        self.stopping.set()
        super().shutdown()

    def on_notify(self, payload=None) -> None:
        self._engine_failed = False
        super().on_notify(payload)

    def device_info(self) -> dict:
        try:
            import torch

            if torch.cuda.is_available():
                return {"device": "cuda", "device_name": torch.cuda.get_device_name(0)}
            return {"device": "cpu", "device_name": "CPU"}
        except ImportError:
            return {"device": "unknown", "device_name": "torch not available"}

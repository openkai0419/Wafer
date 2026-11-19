from __future__ import annotations

from typing import TYPE_CHECKING

from wafer.plugin import BaseInferenceCollector
from wafer.core.logs import AppLogger

if TYPE_CHECKING:
    from ._inference import FlorenceInference

from ._downloader import DEFAULT_VARIANT, ensure_model
from .settings import TAG_MAP, enabled_tasks, florence_config

POST_INSTALL_VERSION = "1"


class FlorenceCollector(BaseInferenceCollector):
    NAME = "florence"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 50
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

    def load_engine(self, model: str) -> FlorenceInference:
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

    def infer(self, engine: FlorenceInference, thumb, model: str) -> dict:
        return self.run_tasks(engine, thumb, self._settings)

    def preview(self, engine: FlorenceInference, thumb, settings: dict) -> dict:
        return {"tags": self.run_tasks(engine, thumb, settings or self._settings)}

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

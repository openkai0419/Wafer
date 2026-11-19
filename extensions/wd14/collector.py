from __future__ import annotations

from typing import TYPE_CHECKING

from wafer.plugin import BaseInferenceCollector

if TYPE_CHECKING:
    from ._inference import TaggerInference

from ._downloader import DEFAULT_MODEL, ensure_default_model
from ._models import NAMED_CATEGORIES, load_spec
from .settings import parse_blacklist, wd14_config

POST_INSTALL_VERSION = "1"


class WD14TaggerCollector(BaseInferenceCollector):
    NAME = "wd14"
    EXTENSIONS = ()
    PRIORITY = 50
    BATCH_SIZE = 150
    MAX_WORKERS = 1
    MAX_TIMEOUT = 1800.0
    ENGINE_IDLE_TIMEOUT = 30.0
    DEFAULT_MODEL = DEFAULT_MODEL
    plugin_config = wd14_config

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        if on_progress:
            on_progress(phase="Downloading WD14 model…")
        ensure_default_model(version=POST_INSTALL_VERSION)

    def load_engine(self, model: str) -> TaggerInference:
        from ._inference import TaggerInference

        if model == DEFAULT_MODEL:
            ensure_default_model(version=POST_INSTALL_VERSION)
        return TaggerInference(load_spec(model))

    def infer(self, engine: TaggerInference, thumb, model: str) -> dict:
        result = engine.predict(
            thumb,
            general_threshold=self._settings.get("general_threshold", 0.057),
            character_threshold=self._settings.get("character_threshold", 0.8),
        )
        return {**self._build_tags(result), "model": model}

    def preview(self, engine: TaggerInference, thumb, settings: dict) -> dict:
        return engine.predict(
            thumb,
            general_threshold=settings.get("general_threshold", self._settings.get("general_threshold", 0.057)),
            character_threshold=settings.get("character_threshold", self._settings.get("character_threshold", 0.8)),
        )

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

    def device_info(self) -> dict:
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

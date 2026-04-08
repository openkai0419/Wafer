import json

from wafer.plugin import BaseSingletonDetacher, DetacherResult
from wafer.utils.logs import AppLogger

using_keywords = ["noise_schedule", "prompt", "steps", "uc", "sampler", "seed", "cfg", "model"]


class NovelAiImageDetacher(BaseSingletonDetacher):
    NAME = "novelai"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("exif.Comment",)

    def process(self, path: str, file_info: tuple, metadata: dict) -> DetacherResult:
        raw = metadata.get("exif.Comment")
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            AppLogger.debug(f"NovelAiImageDetacher failed to parse JSON: {raw}")
            return DetacherResult(source=path, status=False)
        if not isinstance(parsed, dict):
            AppLogger.debug(f"NovelAiImageDetacher JSON was not dict: {raw}")
            return DetacherResult(source=path, status=False)
        meta_info = {k: str(v) for k, v in parsed.items() if k in using_keywords}
        return DetacherResult(source=path, status=True, meta_info=meta_info, delete_keys=["exif.Comment", "exif.Description"])

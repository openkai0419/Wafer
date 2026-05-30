import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.utils.logs import AppLogger

using_keywords = ["noise_schedule", "prompt", "steps", "uc", "sampler", "seed", "cfg", "model"]


class NovelAiImageParser(BaseSingletonParser):
    NAME = "novelai"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("exiftool.PNG:Comment",)
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        raw = metadata.get("exiftool.PNG:Comment")
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            AppLogger.debug(f"NovelAiImageParser failed to parse JSON: {raw}")
            return ParserResult(source=path, status=False)
        if not isinstance(parsed, dict):
            AppLogger.debug(f"NovelAiImageParser JSON was not dict: {raw}")
            return ParserResult(source=path, status=False)
        meta_info = {k: str(v) for k, v in parsed.items() if k in using_keywords}
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=["exiftool.PNG:Comment", "exiftool.PNG:Description"])

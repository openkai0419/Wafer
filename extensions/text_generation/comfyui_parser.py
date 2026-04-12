import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.utils.logs import AppLogger


class ComfyUiParser(BaseSingletonParser):
    NAME = "comfyui"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("ffmpeg.Tag/comment",)

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        raw = metadata.get("ffmpeg.Tag/comment")
        if raw is None:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            AppLogger.debug(f"ComfyUiParser failed to parse JSON: {raw}")
            return ParserResult(source=path, status=False)
        if not isinstance(parsed, dict):
            return ParserResult(source=path, status=False)
        meta_info = {k: str(v) for k, v in parsed.items()}
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=["ffmpeg.Tag/comment"])

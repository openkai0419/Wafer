import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.utils.logs import AppLogger

from ._common import stringify_meta_info


class NovelAiImageParser(BaseSingletonParser):
    NAME = "novelai"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("exiftool.PNG:Comment", "exiftool.ExifIFD:UserComment")
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        for key in self.TRIGGER_KEYS:
            raw = metadata.get(key)
            if raw:
                break
        else:
            return None
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            AppLogger.debug(f"NovelAiImageParser failed to parse JSON: {raw}")
            return ParserResult(source=path, status=False)
        if not isinstance(parsed, dict):
            AppLogger.debug(f"NovelAiImageParser JSON was not dict: {raw}")
            return ParserResult(source=path, status=False)
        meta_info = stringify_meta_info(parsed)
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=[key])

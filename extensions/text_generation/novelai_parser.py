import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.core.logs import AppLogger

from ._common import join_list_field, stringify_meta_info

CHARACTER_CAPTION_KEYS = ("v4_prompt/caption/char_captions", "v4_negative_prompt/caption/char_captions")


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
        if not isinstance(raw, str) or not raw.lstrip().startswith("{"):
            return ParserResult(source=path, status=False)
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            AppLogger.debug(f"NovelAiImageParser failed to parse JSON in {path}: {exc}")
            return ParserResult(source=path, status=False)
        meta_info = stringify_meta_info(parsed)
        for caption_key in CHARACTER_CAPTION_KEYS:
            join_list_field(meta_info, caption_key, "char_caption")
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_meta_keys=[key])

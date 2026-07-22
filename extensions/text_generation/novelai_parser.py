import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.utils.logs import AppLogger


def _as_json_dict(value) -> dict | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def stringify_meta_info(data: dict, prefix: str = "") -> dict[str, str]:
    meta_info: dict[str, str] = {}
    for key, value in data.items():
        current_key = f"{prefix}/{key}" if prefix else str(key)
        if isinstance(value, dict):
            meta_info.update(stringify_meta_info(value, current_key))
            continue
        embedded = _as_json_dict(value)
        if embedded is not None:
            meta_info.update(stringify_meta_info(embedded, prefix))
            continue
        meta_info[current_key] = str(value)
    return meta_info


class NovelAiImageParser(BaseSingletonParser):
    NAME = "novelai"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = ("exiftool.PNG:Comment", "exiftool.ExifIFD:UserComment")
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        raw = metadata.get("exiftool.PNG:Comment") or metadata.get("exiftool.ExifIFD:UserComment")
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
        meta_info = stringify_meta_info(parsed)
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=["exiftool.PNG:Comment", "exiftool.ExifIFD:UserComment"])

import json

from wafer.plugin import BaseSingletonParser, ParserResult
from wafer.core.logs import AppLogger

from ._common import as_json_dict, stringify_meta_info

CHARACTER_PROMPT_KEYS = ("v4_prompt", "v4_negative_prompt")


def format_centers(centers) -> str:
    if not isinstance(centers, list):
        return str(centers)
    return "; ".join(f"{center.get('x')},{center.get('y')}" if isinstance(center, dict) else str(center) for center in centers)


def character_caption_meta(fields: dict) -> dict[str, str]:
    meta_info: dict[str, str] = {}
    for prompt_key in CHARACTER_PROMPT_KEYS:
        prompt = fields.get(prompt_key)
        caption = prompt.get("caption") if isinstance(prompt, dict) else None
        characters = caption.get("char_captions") if isinstance(caption, dict) else None
        if not isinstance(characters, list):
            continue
        characters_key = f"{prompt_key}/caption/char_captions"
        meta_info[characters_key] = "\n".join(str(character["char_caption"]) for character in characters if isinstance(character, dict) and "char_caption" in character)
        for index, character in enumerate(characters):
            if not isinstance(character, dict):
                continue
            character_key = f"{characters_key}/{index}"
            meta_info.update(stringify_meta_info(character, character_key))
            if "centers" in character:
                meta_info[f"{character_key}/centers"] = format_centers(character["centers"])
    return meta_info


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
        meta_info.update(character_caption_meta(as_json_dict(parsed.get("Comment")) or parsed))
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_meta_keys=[key])

import json
import re

from wafer.plugin import BaseSingletonParser, ParserResult

from ._common import as_json_dict, stringify_meta_info

TRIGGER_KEYS = ("exiftool.PNG:Parameters", "exiftool.ExifIFD:UserComment")

re_param = re.compile(r'\s*(\w[\w \-/]+):\s*("(?:\\.|[^\\"])+"|[^,]*)(?:,|$)')
re_imagesize = re.compile(r"^(\d+)x(\d+)$")


def _unquote(text: str):
    if len(text) < 2 or text[0] != '"' or text[-1] != '"':
        return text
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text


def parse_infotext(raw: str) -> dict[str, str]:
    if as_json_dict(raw) is not None:
        return {}
    *lines, lastline = raw.strip().split("\n")
    if len(re_param.findall(lastline)) < 3:
        return {}

    prompt_lines: list[str] = []
    negative_lines: list[str] = []
    done_with_prompt = False
    for line in lines:
        line = line.strip()
        if line.startswith("Negative prompt:"):
            done_with_prompt = True
            line = line[len("Negative prompt:") :].strip()
        (negative_lines if done_with_prompt else prompt_lines).append(line)

    prompt = "\n".join(prompt_lines).strip()
    negative_prompt = "\n".join(negative_lines).strip()

    meta: dict[str, str] = {}
    if prompt:
        meta["prompt"] = prompt
    if negative_prompt:
        meta["negative_prompt"] = negative_prompt

    for key, value in re_param.findall(lastline):
        value = _unquote(value)
        if isinstance(value, dict):
            meta.update(stringify_meta_info(value, key))
            continue
        if key == "Size":
            size = re_imagesize.match(value)
            if size:
                meta["width"], meta["height"] = size.group(1), size.group(2)
                continue
        embedded = as_json_dict(value)
        if embedded is not None:
            meta.update(stringify_meta_info(embedded, key))
            continue
        meta[key] = str(value)
    return meta


class WebUiImageParser(BaseSingletonParser):
    NAME = "webui"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = TRIGGER_KEYS
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        for key in TRIGGER_KEYS:
            raw = metadata.get(key)
            if raw:
                break
        else:
            return None
        meta_info = parse_infotext(raw)
        if not meta_info:
            return ParserResult(source=path, status=False)
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=[key])

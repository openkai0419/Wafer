import json

from wafer.plugin import BaseSingletonParser, ParserResult

from ._common import as_json_dict, stringify_meta_info

TRIGGER_KEYS = (
    "exiftool.PNG:Prompt",
    "exiftool.PNG:Workflow",
    "exiftool.IFD0:Model",
    "exiftool.IFD0:Make",
    "ffmpeg.Tag/prompt",
    "ffmpeg.Tag/workflow",
    "ffmpeg.Tag/comment",
)


def _strip_webp_exif(value):
    if isinstance(value, str):
        _, sep, rest = value.partition(":")
        if sep and rest.lstrip()[:1] in ("{", "["):
            return rest
    return None


def _as_dict(value) -> dict | None:
    if isinstance(value, dict):
        return value
    return as_json_dict(value)


def _extract(metadata: dict) -> tuple[object, object, list[str]]:
    used: list[str] = []

    def take(key: str, value):
        if value:
            used.append(key)
            return value
        return None

    prompt = (
        take("exiftool.PNG:Prompt", metadata.get("exiftool.PNG:Prompt"))
        or take("exiftool.IFD0:Model", _strip_webp_exif(metadata.get("exiftool.IFD0:Model")))
        or take("ffmpeg.Tag/prompt", metadata.get("ffmpeg.Tag/prompt"))
    )
    workflow = (
        take("exiftool.PNG:Workflow", metadata.get("exiftool.PNG:Workflow"))
        or take("exiftool.IFD0:Make", _strip_webp_exif(metadata.get("exiftool.IFD0:Make")))
        or take("ffmpeg.Tag/workflow", metadata.get("ffmpeg.Tag/workflow"))
    )

    comment = as_json_dict(metadata.get("ffmpeg.Tag/comment"))
    if comment is not None:
        if "prompt" in comment or "workflow" in comment:
            if not prompt:
                prompt = take("ffmpeg.Tag/comment", comment.get("prompt"))
            if not workflow:
                workflow = take("ffmpeg.Tag/comment", comment.get("workflow"))
        elif not workflow:
            workflow = take("ffmpeg.Tag/comment", comment)
    return prompt, workflow, used


def _node_sort_key(node_id: str):
    return (0, int(node_id)) if node_id.isdigit() else (1, node_id)


def flatten_graph(graph: dict) -> dict[str, str]:
    by_type: dict[str, list[str]] = {}
    for node_id, node in graph.items():
        if isinstance(node, dict):
            by_type.setdefault(str(node.get("class_type") or node_id), []).append(node_id)

    meta_info: dict[str, str] = {}
    for class_type, node_ids in by_type.items():
        for ordinal, node_id in enumerate(sorted(node_ids, key=_node_sort_key)):
            inputs = graph[node_id].get("inputs")
            if not isinstance(inputs, dict):
                continue
            widgets = {name: value for name, value in inputs.items() if not isinstance(value, list)}
            if not widgets:
                continue
            meta_info.update(stringify_meta_info(widgets, f"{class_type}#{ordinal}"))
    return meta_info


class ComfyUiParser(BaseSingletonParser):
    NAME = "comfyui"
    PRIORITY = 100
    DEFAULT_ENABLED = False
    TRIGGER_KEYS = TRIGGER_KEYS
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    def process(self, path: str, file_info: tuple, metadata: dict) -> ParserResult:
        prompt, workflow, used = _extract(metadata)
        if prompt is None and workflow is None:
            if any(key in metadata for key in TRIGGER_KEYS):
                return ParserResult(source=path, status=False)
            return None

        meta_info: dict[str, str] = {}
        graph = _as_dict(prompt)
        if graph:
            meta_info.update(flatten_graph(graph))
        if workflow is not None:
            meta_info["workflow"] = workflow if isinstance(workflow, str) else json.dumps(workflow, ensure_ascii=False)

        if not meta_info:
            return ParserResult(source=path, status=False)
        delete_keys = list(dict.fromkeys(used))
        return ParserResult(source=path, status=True, meta_info=meta_info, delete_keys=delete_keys)

import json


def as_json_dict(value) -> dict | None:
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
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            value = dict(enumerate(value))
        if isinstance(value, dict):
            meta_info.update(stringify_meta_info(value, current_key))
            continue
        embedded = as_json_dict(value)
        if embedded is not None:
            meta_info.update(stringify_meta_info(embedded, prefix))
            continue
        meta_info[current_key] = str(value)
    return meta_info


def join_list_field(meta_info: dict[str, str], list_key: str, field: str) -> None:
    prefix, suffix = f"{list_key}/", f"/{field}"
    values = [value for key, value in meta_info.items() if key.startswith(prefix) and key.endswith(suffix) and key[len(prefix) : -len(suffix)].isdigit()]
    if values:
        meta_info[list_key] = "\n".join(values)

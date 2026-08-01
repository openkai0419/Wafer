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
        if isinstance(value, dict):
            meta_info.update(stringify_meta_info(value, current_key))
            continue
        embedded = as_json_dict(value)
        if embedded is not None:
            meta_info.update(stringify_meta_info(embedded, prefix))
            continue
        meta_info[current_key] = str(value)
    return meta_info

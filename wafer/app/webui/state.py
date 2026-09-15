from __future__ import annotations

import json
from pathlib import Path

from ...core.logs import AppLogger
from ...core.common.paths import resolve_temp_path


def _state_path():
    return Path(resolve_temp_path("webui.json"))


def write_state(url: str) -> None:
    try:
        _state_path().write_text(json.dumps({"url": url}), encoding="utf-8")
    except OSError as e:
        AppLogger.warning(f"WebUI state write failed: {e}")


def read_url() -> str:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str(data.get("url", ""))

from __future__ import annotations

from pathlib import Path
from typing import Any
import json

from ..logs import AppLogger
from ..profiling import profiler
from .atomic_file import retry_while_in_use, write_text_atomic


def _load(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


@profiler.profile
def read_json_file(path: str | Path, default: Any = None) -> Any:
    try:
        p = Path(path)
        if not p.exists():
            return default
        return retry_while_in_use(lambda: _load(p))
    except Exception as e:
        AppLogger.warning(f"read_json_file failed: {path}", exc=e)
        return default


@profiler.profile
def write_json_file(
    path: str | Path,
    data: Any,
    *,
    indent: int = 2,
    ensure_ascii: bool = False,
) -> bool:
    try:
        write_text_atomic(path, json.dumps(data, ensure_ascii=ensure_ascii, indent=indent))
        return True
    except Exception as e:
        AppLogger.warning(f"write_json_file failed: {path}", exc=e)
        return False

from __future__ import annotations

import os
import threading
import time
from pathlib import Path

_REPLACE_TIMEOUT = 1.0
_REPLACE_RETRY = 0.01


def _replace(src: str, dst: str) -> None:
    deadline = time.monotonic() + _REPLACE_TIMEOUT
    while True:
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_REPLACE_RETRY)


def write_text_atomic(path: str | Path, text: str) -> None:
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace(temp, path)
    except BaseException:
        if os.path.exists(temp):
            os.remove(temp)
        raise

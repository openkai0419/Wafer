from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import TypeVar

_IN_USE_TIMEOUT = 1.0
_IN_USE_RETRY = 0.01

T = TypeVar("T")


def retry_while_in_use(fn: Callable[[], T]) -> T:
    deadline = time.monotonic() + _IN_USE_TIMEOUT
    while True:
        try:
            return fn()
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(_IN_USE_RETRY)


def write_text_atomic(path: str | Path, text: str) -> None:
    path = os.fspath(path)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    temp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    try:
        with open(temp, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        retry_while_in_use(lambda: os.replace(temp, path))
    except BaseException:
        if os.path.exists(temp):
            os.remove(temp)
        raise

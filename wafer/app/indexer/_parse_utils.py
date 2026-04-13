from __future__ import annotations

import threading
import time
from typing import Any
from collections.abc import Callable
from datetime import UTC

BATCH_SIZE = 900
FLUSH_DELAY = 4.0

_DATETIME_FORMATS = (
    "%Y:%m:%d %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y:%m:%d",
    "%Y-%m-%d",
)


def try_parse_datetime(s: str):
    from datetime import datetime

    for fmt in _DATETIME_FORMATS:
        try:
            dt = datetime.strptime(s.strip(), fmt)
            return dt.replace(tzinfo=UTC).timestamp()
        except ValueError:
            continue
    return None


def try_float(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        pass
    if isinstance(v, str):
        ts = try_parse_datetime(v)
        if ts is not None:
            return ts
    return None


class ResultBuffer:
    def __init__(self, merge_fn: Callable[[list[dict[str, Any]]], dict[str, Any]]):
        self._merge_fn = merge_fn
        self._lock = threading.Lock()
        self._entries: list[dict[str, Any]] = []
        self._count = 0
        self._flush_scheduled = False
        self._first_append: float = 0.0

    def append(self, parsed: dict, count: int) -> bool:
        with self._lock:
            self._entries.append(parsed)
            self._count += count
            if not self._flush_scheduled:
                self._flush_scheduled = True
                self._first_append = time.monotonic()
                return True
            return False

    def drain(self) -> tuple[dict | None, int]:
        with self._lock:
            if not self._count:
                self._flush_scheduled = False
                return None, 0
            merged = self._merge_fn(self._entries)
            count = self._count
            self._entries.clear()
            self._count = 0
            self._flush_scheduled = False
            return merged, count

    def time_since_first(self) -> float:
        with self._lock:
            if not self._first_append:
                return 0.0
            return time.monotonic() - self._first_append

    def has_pending(self) -> bool:
        with self._lock:
            if self._count > 0 and not self._flush_scheduled:
                self._flush_scheduled = True
                return True
            return False

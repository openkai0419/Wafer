from __future__ import annotations

import threading
from collections.abc import Iterable

from ..core.logs import AppLogger


class RetryCounter:
    def __init__(self, name: str):
        self.name = name
        self._lock = threading.Lock()
        self._failures: dict[str, int] = {}
        self._paused: set[str] = set()

    def count_failure(self, path: str, *, pause_after: int | None = None, fail_after: int | None = None) -> bool:
        limit = limit_of(pause_after, fail_after)
        with self._lock:
            failures = self._failures.get(path, 0) + 1
            if failures < limit:
                self._failures[path] = failures
                return False
            self._failures.pop(path, None)
            if pause_after is not None:
                self._paused.add(path)
        if fail_after is not None:
            AppLogger.warning(f"[{self.name}] Failed {failures} times; not collected again until the file changes: {path}")
            return True
        AppLogger.warning(f"[{self.name}] Failed {failures} times; paused until the next restart: {path}")
        return False

    def is_paused(self, path: str) -> bool:
        return path in self._paused

    def forget(self, paths: Iterable[str]) -> None:
        if not self._failures:
            return
        with self._lock:
            for path in paths:
                self._failures.pop(path, None)


def limit_of(pause_after: int | None, fail_after: int | None) -> int:
    if (pause_after is None) == (fail_after is None):
        raise ValueError("retry_later() needs exactly one of pause_after or fail_after")
    limit = pause_after if pause_after is not None else fail_after
    if not isinstance(limit, int) or limit < 1:
        raise ValueError(f"retry_later() limit must be a positive int: {limit!r}")
    return limit


class RetryLater:
    RESULT_TYPE: type

    @property
    def retries(self) -> RetryCounter:
        counter = self.__dict__.get("retry_counter")
        if counter is None:
            counter = self.__dict__.setdefault("retry_counter", RetryCounter(self.NAME))
        return counter

    def retry_later(self, path: str, *, pause_after: int | None = None, fail_after: int | None = None):
        if self.retries.count_failure(path, pause_after=pause_after, fail_after=fail_after):
            return self.RESULT_TYPE(source=path, status=False)
        return None

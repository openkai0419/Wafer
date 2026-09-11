from __future__ import annotations

import hashlib
import os
import tempfile
import threading
import time
from pathlib import Path
from collections.abc import Callable

from ...utils.logs import AppLogger


class DiskCache:
    def __init__(
        self,
        root: str | os.PathLike,
        *,
        size_limit_bytes: int,
        idle_seconds: float | None = None,
        sweep_interval_seconds: float = 300.0,
    ):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.size_limit_bytes = size_limit_bytes
        self.idle_seconds = idle_seconds
        self.sweep_interval_seconds = sweep_interval_seconds
        self._sweep_lock = threading.Lock()
        self._last_sweep = time.monotonic()

    def path_for(self, key: str, suffix: str = "") -> Path:
        digest = hashlib.blake2b(key.encode("utf-8"), digest_size=20).hexdigest()
        return self.root / digest[:2] / f"{digest}{suffix}"

    def get_or_create(self, key: str, produce: Callable[[str], bool], suffix: str = "") -> Path | None:
        target = self.path_for(key, suffix)
        if target.is_file():
            _touch(target)
            return target
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=target.parent, suffix=".tmp")
        os.close(fd)
        try:
            if not produce(tmp):
                return None
            os.replace(tmp, target)
            tmp = ""
        finally:
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass
        _touch(target)
        self._maybe_sweep()
        return target

    def _maybe_sweep(self) -> None:
        now = time.monotonic()
        with self._sweep_lock:
            if now - self._last_sweep < self.sweep_interval_seconds:
                return
            self._last_sweep = now
        self.sweep()

    def sweep(self) -> int:
        cutoff = time.time() - self.idle_seconds if self.idle_seconds is not None else None
        removed = 0
        entries: list[tuple[float, int, Path]] = []
        for dirpath, _dirs, filenames in os.walk(self.root, onerror=lambda _e: None):
            base = Path(dirpath)
            for name in filenames:
                if name.endswith(".tmp"):
                    continue
                path = base / name
                try:
                    st = path.stat()
                except OSError:
                    continue
                if cutoff is not None and st.st_mtime < cutoff:
                    removed += _unlink(path)
                else:
                    entries.append((st.st_mtime, st.st_size, path))
        total = sum(size for _, size, _ in entries)
        if total > self.size_limit_bytes:
            entries.sort(key=lambda e: e[0])
            for _, size, path in entries:
                if total <= self.size_limit_bytes:
                    break
                if _unlink(path):
                    total -= size
                    removed += 1
        if removed:
            AppLogger.info(f"[disk_cache] {self.root.name}: swept {removed} entries")
        return removed


def _touch(path: Path) -> None:
    try:
        now = time.time()
        os.utime(path, (now, now))
    except OSError:
        pass


def _unlink(path: Path) -> int:
    try:
        path.unlink()
        return 1
    except FileNotFoundError:
        return 1
    except OSError as e:
        AppLogger.debug(f"[disk_cache] unlink failed: {path} ({e})")
        return 0

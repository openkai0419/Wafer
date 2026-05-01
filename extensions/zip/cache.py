from __future__ import annotations

import errno
import hashlib
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from pathlib import Path, PurePosixPath

from wafer.utils.logs import AppLogger
from wafer.utils.paths import normalize_path, resolve_data_path
from wafer.utils.virtual_paths import child_path, display_name, source_path

from . import settings as cache_settings

_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')


def _is_sharing_violation(e: OSError) -> bool:
    return e.errno == errno.EACCES or getattr(e, "winerror", None) in (5, 32)


class ZipCache:
    def __init__(self, root: str | os.PathLike | None = None):
        self.root = Path(root or resolve_data_path("cache/zip/"))
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._sweep_timer: threading.Timer | None = None
        self._sweep_lock = threading.Lock()

    def materialize(self, logical_path: str, purpose: str = "render") -> str:
        self.start_idle_sweep()
        source = source_path(logical_path)
        member = child_path(logical_path)
        if not member:
            raise ValueError(f"not a zip virtual path: {logical_path}")
        st = os.stat(source)
        signature = f"{st.st_mtime_ns}:{st.st_size}"
        digest = self._digest(source, member, signature, purpose)
        suffix = PurePosixPath(member.replace("\\", "/")).suffix
        filename = f"{digest}_{self._safe_stem(display_name(logical_path), suffix)}{suffix}"
        target = self.root / digest[:2] / filename
        with self._lock:
            if target.is_file():
                self._touch(target)
                return normalize_path(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp_name = None
            try:
                with zipfile.ZipFile(source) as zf, self._open_member(zf, member) as src, tempfile.NamedTemporaryFile("wb", delete=False, dir=target.parent, suffix=".tmp") as tmp:
                    tmp_name = tmp.name
                    shutil.copyfileobj(src, tmp, length=1024 * 1024)
                os.replace(tmp_name, target)
                tmp_name = None
                self._touch(target)
                return normalize_path(target)
            finally:
                if tmp_name:
                    try:
                        os.remove(tmp_name)
                    except FileNotFoundError:
                        pass

    @staticmethod
    def _touch(path: Path) -> None:
        try:
            now = time.time()
            os.utime(path, (now, now))
        except OSError as e:
            AppLogger.debug(f"[zip_cache] touch failed: {path} ({e})")

    def start_idle_sweep(self, interval_seconds: float | None = None) -> None:
        if interval_seconds is None:
            interval_seconds = cache_settings.SWEEP_INTERVAL_SECONDS
        with self._sweep_lock:
            if self._sweep_timer is not None:
                return
            self._schedule_sweep(interval_seconds)

    def stop_idle_sweep(self) -> None:
        with self._sweep_lock:
            if self._sweep_timer is not None:
                self._sweep_timer.cancel()
                self._sweep_timer = None

    def _schedule_sweep(self, interval_seconds: float) -> None:
        timer = threading.Timer(interval_seconds, self._sweep_tick, kwargs={"interval_seconds": interval_seconds})
        timer.daemon = True
        timer.name = "zip-cache-sweep"
        timer.start()
        self._sweep_timer = timer

    def _sweep_tick(self, interval_seconds: float) -> None:
        try:
            self.sweep()
        except Exception as e:
            AppLogger.warning(f"[zip_cache] sweep failed: {e}", exc=e)
        finally:
            with self._sweep_lock:
                if self._sweep_timer is not None:
                    self._schedule_sweep(interval_seconds)

    def sweep(
        self,
        idle_seconds: float | None = None,
        size_limit_bytes: int | None = None,
    ) -> tuple[int, int]:
        idle_seconds = cache_settings.ENTRY_IDLE_SECONDS if idle_seconds is None else idle_seconds
        size_limit_bytes = cache_settings.TOTAL_SIZE_LIMIT_BYTES if size_limit_bytes is None else size_limit_bytes
        cutoff = time.time() - idle_seconds
        idle_removed = 0
        lru_removed = 0
        with self._lock:
            entries: list[tuple[float, int, Path]] = []
            dirs: list[Path] = []
            for dirpath, _dirnames, filenames in os.walk(self.root, onerror=lambda _e: None):
                base = Path(dirpath)
                if base != self.root:
                    dirs.append(base)
                for name in filenames:
                    path = base / name
                    try:
                        st = path.stat()
                    except OSError:
                        continue
                    if st.st_mtime < cutoff:
                        try:
                            path.unlink()
                            idle_removed += 1
                        except FileNotFoundError:
                            pass
                        except OSError as e:
                            if not _is_sharing_violation(e):
                                AppLogger.debug(f"[zip_cache] unlink failed: {path} ({e})")
                    else:
                        entries.append((st.st_mtime, st.st_size, path))
            total_size = sum(size for _, size, _ in entries)
            if total_size > size_limit_bytes:
                entries.sort(key=lambda e: e[0])
                for _, size, path in entries:
                    if total_size <= size_limit_bytes:
                        break
                    try:
                        path.unlink()
                        total_size -= size
                        lru_removed += 1
                    except FileNotFoundError:
                        total_size -= size
                    except OSError as e:
                        if not _is_sharing_violation(e):
                            AppLogger.debug(f"[zip_cache] LRU unlink failed: {path} ({e})")
            for path in sorted(dirs, reverse=True):
                try:
                    path.rmdir()
                except OSError:
                    pass
        if idle_removed or lru_removed:
            AppLogger.info(f"[zip_cache] sweep removed idle={idle_removed} lru={lru_removed}")
        return idle_removed, lru_removed

    @staticmethod
    def _open_member(zf: zipfile.ZipFile, member: str):
        try:
            return zf.open(member, "r")
        except KeyError:
            return zf.open(member.replace("/", "\\"), "r")

    @staticmethod
    def _digest(source: str, member: str, signature: str, purpose: str) -> str:
        h = hashlib.sha256(usedforsecurity=False)
        for part in (source, member, signature, purpose):
            h.update(str(part).encode("utf-8", "surrogatepass"))
            h.update(b"\0")
        return h.hexdigest()[:32]

    @staticmethod
    def _safe_stem(name: str, suffix: str) -> str:
        if suffix and name.lower().endswith(suffix.lower()):
            name = name[: -len(suffix)]
        stem = _INVALID_FILENAME.sub("_", name).strip(" ._")
        return (stem or "entry")[:80]


zip_cache = ZipCache()

import time
import threading
import weakref

from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger
from wafer.utils.logs import debug_non_recursive

_IDLE_TIMEOUT = 120.0

POST_INSTALL_VERSION = "1"


class ExifToolCollectorPlugin(BaseCollectorPlugin):
    NAME = "exiftool"
    EXTENSIONS = (
        ".jpg",
        ".jpeg",
        ".png",
        ".bmp",
        ".gif",
        ".webp",
        ".tiff",
        ".tif",
        ".heic",
        ".heif",
        ".avif",
        ".jxl",
        ".cr2",
        ".cr3",
        ".nef",
        ".arw",
        ".orf",
        ".rw2",
        ".dng",
        ".raf",
        ".pef",
        ".srw",
        ".psd",
        ".ico",
        ".apng",
    )
    PRIORITY = 100
    DEFAULT_ENABLED = True
    MAX_WORKERS = 1
    MAX_TIMEOUT = 300.0

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        from ._downloader import ensure_exiftool

        ensure_exiftool(version=POST_INSTALL_VERSION)

    def __init__(self):
        super().__init__()
        self._process = None
        self._process_lock = threading.Lock()
        self._exe_path: str | None = None
        self._last_used: float = 0.0
        self._idle_timer: threading.Timer | None = None
        from .settings import migrate_legacy_filter

        migrate_legacy_filter()

    def shutdown(self):
        self._close_process()

    def _touch(self):
        self._last_used = time.monotonic()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        t = threading.Timer(_IDLE_TIMEOUT, _run_weak_method, args=(weakref.WeakMethod(self._check_idle),))
        t.daemon = True
        t.start()
        self._idle_timer = t

    def _check_idle(self):
        elapsed = time.monotonic() - self._last_used
        if elapsed < _IDLE_TIMEOUT:
            return
        with self._process_lock:
            if self._process is None:
                return
            if time.monotonic() - self._last_used < _IDLE_TIMEOUT:
                return
            self._process.stop()
            self._process = None
            AppLogger.info("[ExifToolCollector] Process stopped (idle timeout)")

    def _close_process(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._process_lock:
            process = self._process
            self._process = None
        if process is None:
            return
        try:
            process.stop()
        except Exception as e:
            AppLogger.warning("[ExifToolCollector] Process shutdown failed", exc=e)

    def _ensure_process(self):
        from .parser import ExifToolProcess

        if self._process and self._process.alive:
            return self._process
        with self._process_lock:
            if self._process and self._process.alive:
                return self._process
            if self._exe_path is None:
                from ._downloader import get_exiftool_path

                self._exe_path = get_exiftool_path()
            if self._exe_path is None:
                return None
            old = self._process
            self._process = ExifToolProcess(self._exe_path)
            self._process.start()
            if old is not None:
                old.stop()
            return self._process

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        proc = self._ensure_process()
        if proc is None:
            return CollectorResult(source=path, status=False)
        self._touch()

        data = proc.query(path)
        if data is None:
            return CollectorResult(source=path, status=False)

        try:
            from .parser import flatten

            meta, aspect = flatten(data)
            return CollectorResult(
                source=path,
                status=True,
                aspect=aspect,
                meta_info=meta if meta else None,
            )
        except Exception as e:
            AppLogger.debug(f"[exiftool] flatten failed for {path}: {e}")
            return CollectorResult(source=path, status=False)

    def __del__(self):
        try:
            self.shutdown()
        except Exception as e:
            debug_non_recursive(f"[ExifToolCollector] Cleanup failed: {e}")


def _run_weak_method(method_ref: weakref.WeakMethod):
    method = method_ref()
    if method is not None:
        method()

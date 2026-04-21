import time
import threading

from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger

_IDLE_TIMEOUT = 120.0


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

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None, is_cancelled=None, on_log=None):
        from ._downloader import ensure_exiftool

        ensure_exiftool()

    def __init__(self):
        super().__init__()
        self._process = None
        self._process_lock = threading.Lock()
        self._exe_path: str | None = None
        self._last_used: float = 0.0
        self._idle_timer: threading.Timer | None = None
        self._filter_mode: str = "blacklist"
        self._filter_keys: set[str] = set()
        self._load_filter()

    def on_notify(self, payload=None) -> None:
        if self._idle_timer is not None:
            self._idle_timer.cancel()
            self._idle_timer = None
        with self._process_lock:
            if self._process:
                self._process.stop()
                self._process = None
        self._exe_path = None
        self._load_filter()
        AppLogger.info(f"[ExifToolCollector] Reloaded: mode={self._filter_mode}, {len(self._filter_keys)} keys")

    def _touch(self):
        self._last_used = time.monotonic()
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        t = threading.Timer(_IDLE_TIMEOUT, self._check_idle)
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
            if meta and self._filter_keys:
                if self._filter_mode == "whitelist":
                    meta = {k: v for k, v in meta.items() if k in self._filter_keys}
                else:
                    meta = {k: v for k, v in meta.items() if k not in self._filter_keys}
            return CollectorResult(
                source=path,
                status=True,
                aspect=aspect,
                meta_info=meta if meta else None,
            )
        except Exception as e:
            AppLogger.debug(f"[exiftool] flatten failed for {path}: {e}")
            return CollectorResult(source=path, status=False)

    def _load_filter(self):
        try:
            from .settings import read_filter_config

            self._filter_mode, self._filter_keys = read_filter_config()
        except Exception as e:
            AppLogger.warning(f"[ExifToolCollector] Failed to load filter config: {e}", exc=e)
            self._filter_mode = "blacklist"
            self._filter_keys = set()

    def __del__(self):
        if self._idle_timer is not None:
            self._idle_timer.cancel()
        if self._process:
            self._process.stop()

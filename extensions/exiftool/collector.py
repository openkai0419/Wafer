from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger


class ExifToolCollectorPlugin(BaseCollectorPlugin):
    NAME = "exiftool"
    EXTENSIONS = (
        ".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".tiff", ".tif",
        ".heic", ".heif", ".avif", ".jxl",
        ".cr2", ".cr3", ".nef", ".arw", ".orf", ".rw2", ".dng", ".raf", ".pef", ".srw",
        ".psd", ".ico",
    )
    PRIORITY = 100
    DEFAULT_ENABLED = True

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None):
        from ._downloader import ensure_exiftool

        ensure_exiftool()

    def __init__(self):
        super().__init__()
        self._process = None
        self._exe_path: str | None = None
        self._filter_mode: str = "blacklist"
        self._filter_keys: set[str] = set()
        self._load_filter()

    def on_notify(self) -> None:
        if self._process:
            self._process.stop()
            self._process = None
        self._exe_path = None
        self._load_filter()
        AppLogger.info(f"[ExifToolCollector] Reloaded: mode={self._filter_mode}, {len(self._filter_keys)} keys")

    def _ensure_process(self):
        from .parser import ExifToolProcess

        if self._process and self._process.alive:
            return self._process
        if self._exe_path is None:
            from ._downloader import get_exiftool_path

            self._exe_path = get_exiftool_path()
        if self._exe_path is None:
            return None
        self._process = ExifToolProcess(self._exe_path)
        self._process.start()
        return self._process

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        proc = self._ensure_process()
        if proc is None:
            return CollectorResult(source=path, status=False)

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
        if self._process:
            self._process.stop()

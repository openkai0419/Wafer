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

    def on_notify(self) -> None:
        if self._process:
            self._process.stop()
            self._process = None
        self._exe_path = None

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
        if self._process:
            self._process.stop()

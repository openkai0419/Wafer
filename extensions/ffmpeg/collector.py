from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger


class FfmpegCollectorPlugin(BaseCollectorPlugin):
    NAME = "ffmpeg"
    EXTENSIONS = (
        ".mp4", ".mkv", ".webm", ".avi", ".mov", ".wmv", ".flv", ".ts", ".m4v",
        ".mp3", ".flac", ".wav", ".ogg", ".m4a", ".aac", ".wma", ".opus",
    )
    PRIORITY = 100
    DEFAULT_ENABLED = True
    BATCH_SIZE = 600

    @classmethod
    def post_install(cls, plugin_dir, on_progress=None):
        from ._downloader import ensure_ffmpeg

        ensure_ffmpeg()

    def __init__(self):
        super().__init__()
        self._ffprobe_path: str | None = None

    def on_notify(self) -> None:
        self._ffprobe_path = None

    def _resolve_ffprobe(self) -> str | None:
        if self._ffprobe_path:
            return self._ffprobe_path
        from ._downloader import get_ffprobe_path

        self._ffprobe_path = get_ffprobe_path()
        return self._ffprobe_path

    def process(self, path: str, file_info: tuple) -> CollectorResult:
        ffprobe = self._resolve_ffprobe()
        if ffprobe is None:
            return CollectorResult(source=path, status=False)

        from .parser import probe, flatten

        data = probe(path, ffprobe)
        if data is None:
            return CollectorResult(source=path, status=False)

        try:
            meta, aspect = flatten(data)
            return CollectorResult(
                source=path,
                status=True,
                aspect=aspect,
                meta_info=meta if meta else None,
            )
        except Exception as e:
            AppLogger.debug(f"[ffmpeg] flatten failed for {path}: {e}")
            return CollectorResult(source=path, status=False)

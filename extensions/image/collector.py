import os
from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger


class ExifCollectorPlugin(BaseCollectorPlugin):
    NAME = "exif"
    EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
    PRIORITY = 100
    DEFAULT_ENABLED = True

    def __init__(self):
        super().__init__()
        self._filter_mode: str = "blacklist"
        self._filter_keys: set[str] = set()
        self._load_filter()

    def on_notify(self) -> None:
        self._load_filter()
        AppLogger.info(f"[ExifCollector] Filter reloaded: mode={self._filter_mode}, {len(self._filter_keys)} keys")

    def process(self, path: str, file_info: tuple):
        from PIL import Image
        from .exif_parser import ExifParser

        try:
            with Image.open(path) as img:
                res = ExifParser.parse_img(img)
                if res["error"]:
                    raise RuntimeError(res["error"])
            raw = {k: v for k, v in {**res["exif"], **res["info_items"]}.items() if v is not None}
            if self._filter_keys:
                if self._filter_mode == "whitelist":
                    raw = {k: v for k, v in raw.items() if k in self._filter_keys}
                else:
                    raw = {k: v for k, v in raw.items() if k not in self._filter_keys}
            return CollectorResult(
                source=path,
                status=True,
                aspect=res["aspect"] or None,
                meta_info=raw,
            )
        except Exception as e:
            AppLogger.debug(f"ExifCollectorPlugin failed: {path} ({e})")
            return CollectorResult(
                source=path,
                status=False,
            )

    def _load_filter(self):
        try:
            from .settings import read_filter_config

            self._filter_mode, self._filter_keys = read_filter_config()
        except Exception as e:
            AppLogger.warning(f"[ExifCollector] Failed to load filter config: {e}", exc=e)
            self._filter_mode = "blacklist"
            self._filter_keys = set()

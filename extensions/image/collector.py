import os
from wafer.plugin import BaseCollectorPlugin, CollectorResult
from wafer.utils.logs import AppLogger


class ExifCollectorPlugin(BaseCollectorPlugin):
    NAME = "exif"
    EXTENSIONS = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
    PRIORITY = 100
    DEFAULT_ENABLED = True

    def process(self, path: str, file_info: tuple):
        from PIL import Image
        from .exif_parser import ExifParser

        try:
            with Image.open(path) as img:
                res = ExifParser.parse_img(img)
                if res["error"]:
                    raise RuntimeError(res["error"])
            return CollectorResult(
                source=path,
                status=True,
                aspect=res["aspect"] or None,
                meta_info={k: v for k, v in {**res["exif"], **res["info_items"]}.items() if v is not None},
            )
        except Exception as e:
            AppLogger.debug(f"ExifCollectorPlugin failed: {path} ({e})")
            return CollectorResult(
                source=path,
                status=False,
            )

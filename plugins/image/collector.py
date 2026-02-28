import os
from source.utils.logs import AppLogger
from afterimages import BaseCollectorPlugin, CollectorResult


class ExifCollectorPlugin(BaseCollectorPlugin):
    NAME = 'exif'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    @staticmethod
    def _prefixed_meta(raw: dict) -> dict:
        return {f'exif.{k}': v for k, v in raw.items() if v is not None}

    def process(self, path: str, file_info: tuple):
        from PIL import Image
        from .exif_parser import ExifParser
        try:
            with Image.open(path) as img:
                res = ExifParser.parse_img(img)
                if res['error']:
                    raise RuntimeError(res['error'])
            return CollectorResult(
                source=path,
                status=True,
                aspect=res['aspect'] or None,
                meta_info=self._prefixed_meta({**res['exif'], **res['info_items']}),
            )
        except Exception as e:
            AppLogger.debug(f'ExifCollectorPlugin failed: {path} ({e})')
            return CollectorResult(
                source=path,
                status=False,
            )

import os
from ...common.logs import AppLogger
from ...common.hashes import fast_sig_hash
from .base import BaseCollectorPlugin, CollectorResult


class ImageCollectorPlugin(BaseCollectorPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')
    PRIORITY = 100

    def process(self, path: str, file_info: tuple):
        from PIL import Image
        from ..exif_parser import ExifParser
        try:
            with Image.open(path) as img:
                res = ExifParser.parse_img(img)
                if res['error']:
                    raise RuntimeError(res['error'])
            mtime, fsize, ctime = file_info
            return CollectorResult(
                source=path,
                status=True,
                name=os.path.basename(path),
                aspect=res['aspect'] or None,
                file_hash=fast_sig_hash(path, fsize, 256),
                meta_info={**res['exif'], **res['info_items']},
            )
        except Exception as e:
            AppLogger.debug(f'ImageCollectorPlugin failed: {path} ({e})')
            return CollectorResult(
                source=path,
                status=False,
                name=os.path.basename(path),
            )

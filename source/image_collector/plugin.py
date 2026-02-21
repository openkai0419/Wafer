import os
from abc import ABC, abstractmethod
from ..common.logs import AppLogger
from ..common.hashes import fast_sig_hash


class BaseCollectorPlugin(ABC):
    NAME: str = ''
    EXTENSIONS: tuple[str, ...] = ()

    @abstractmethod
    def process(self, path: str, file_info: tuple) -> dict:
        ...


class ImageCollectorPlugin(BaseCollectorPlugin):
    NAME = 'image'
    EXTENSIONS = ('.jpg', '.jpeg', '.png', '.bmp', '.gif', '.webp')

    def process(self, path: str, file_info: tuple) -> dict:
        from PIL import Image
        from ..io.exif_parser import ExifParser
        try:
            with Image.open(path) as img:
                res = ExifParser.parse_img(img)
                if res['error']:
                    raise RuntimeError(res['error'])
            aspect = res['aspect'] or 1.0
            meta_info = {**res['exif'], **res['info_items']}
            mtime, fsize, ctime = file_info
            return {
                'source': path,
                'info': {
                    'source': path,
                    'path': path,
                    'name': os.path.basename(path),
                    'aspect': aspect,
                    'file_hash': fast_sig_hash(path, fsize, 256),
                },
                'meta_info': meta_info,
                'tags': {},
                'status': 'ok',
            }
        except Exception as e:
            AppLogger.debug(f'ImageCollectorPlugin failed: {path} ({e})')
            return {
                'source': path,
                'info': {
                    'source': path,
                    'path': path,
                    'name': os.path.basename(path),
                    'aspect': 1.0,
                },
                'meta_info': {},
                'tags': {},
                'status': 'fail',
            }


BUILTIN_PLUGINS = {
    ImageCollectorPlugin.NAME: ImageCollectorPlugin,
}


def get_collector_names():
    return list(BUILTIN_PLUGINS.keys())


def get_collector_info():
    return [(cls.NAME, cls.EXTENSIONS) for cls in BUILTIN_PLUGINS.values()]


def get_collectors_for_path(path):
    ext = os.path.splitext(path)[1].lower()
    return [
        name for name, cls in BUILTIN_PLUGINS.items()
        if not cls.EXTENSIONS or ext in cls.EXTENSIONS
    ]

from PIL import Image

from ..plugin.imageloader.base import BaseImageLoader
from ..utils.logs import AppLogger
from ..utils.profiling import profiler


class SystemImageLoader(BaseImageLoader):
    NAME = "system_thumbnail"
    EXTENSIONS = ()
    PRIORITY = -100
    SCOPE = "*"

    def __init__(self):
        from ..core.platform.thumbnails import FileThumbnailer

        self._thumbnailer = FileThumbnailer()

    @profiler.profile
    def load_pil(self, path: str, size: int | None = None) -> Image.Image | None:
        try:
            thumb_size = size if size is not None else 256
            pil_img = self._thumbnailer.get_thumbnail(path, size=thumb_size)
            if pil_img is None:
                return None
            if pil_img.mode not in ("RGB", "RGBA", "L"):
                pil_img = pil_img.convert("RGB")
            return pil_img
        except Exception as e:
            AppLogger.debug(f"[SystemImageLoader] load failed: {path} ({e})")
            return None

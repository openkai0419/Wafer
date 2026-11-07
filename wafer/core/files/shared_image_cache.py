from ..store.settings import app_settings
from .image_cache import MemoryLimitedImageCache

IMAGE_CACHE_KEY = "window/cache_size"
IMAGE_CACHE_DEFAULT_MB = 512

_follows_setting = False


def image_cache_limit_mb() -> int:
    return app_settings.get(IMAGE_CACHE_KEY, IMAGE_CACHE_DEFAULT_MB, int)


def shared_image_cache() -> MemoryLimitedImageCache:
    global _follows_setting
    cache = MemoryLimitedImageCache(image_cache_limit_mb())
    if not _follows_setting:
        _follows_setting = True
        app_settings.key_changed.connect(_on_setting_changed)
    return cache


def set_image_cache_limit(limit_mb: int) -> None:
    app_settings.save_immediate(IMAGE_CACHE_KEY, limit_mb)
    shared_image_cache().set_limit(limit_mb)


def _on_setting_changed(key: str) -> None:
    if key == IMAGE_CACHE_KEY:
        shared_image_cache().set_limit(image_cache_limit_mb())

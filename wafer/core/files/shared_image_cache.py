from ..store.settings import app_settings
from .image_cache import MemoryLimitedImageCache

IMAGE_CACHE_KEY = "window/cache_size"
IMAGE_CACHE_DEFAULT_MB = 512


def image_cache_limit_mb() -> int:
    return app_settings.get(IMAGE_CACHE_KEY, IMAGE_CACHE_DEFAULT_MB, int)


_cache = MemoryLimitedImageCache(image_cache_limit_mb())


def shared_image_cache() -> MemoryLimitedImageCache:
    return _cache


def set_image_cache_limit(limit_mb: int) -> None:
    app_settings.save_immediate(IMAGE_CACHE_KEY, limit_mb)
    _cache.set_limit(limit_mb)


def _on_setting_changed(key: str) -> None:
    if key == IMAGE_CACHE_KEY:
        _cache.set_limit(image_cache_limit_mb())


app_settings.key_changed.connect(_on_setting_changed)

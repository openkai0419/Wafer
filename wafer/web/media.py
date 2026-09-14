from __future__ import annotations

import os

from wafer.core.files.disk_cache import DiskCache
from wafer.utils.logs import AppLogger
from wafer.utils.paths import resolve_cache_path

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif", ".jfif"})
VIDEO_EXTS = frozenset({".mp4", ".webm", ".m4v", ".ogv", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".ts"})
NATIVE_VIDEO_EXTS = frozenset({".mp4", ".webm", ".m4v", ".ogv"})

THUMB_SIZE_DEFAULT = 256
THUMB_SIZE_MAX = 1024
THUMB_CACHE_SIZE_LIMIT_BYTES = 512 * 1024 * 1024


def classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in NATIVE_VIDEO_EXTS:
        return "video"
    if ext in VIDEO_EXTS:
        return "video-unsupported"
    return "other"


def thumb_cache_dir() -> str:
    return str(resolve_cache_path("web_thumbs/"))


_thumb_cache: DiskCache | None = None
_thumb_cache_dir: str | None = None


def thumb_cache() -> DiskCache:
    global _thumb_cache, _thumb_cache_dir
    directory = thumb_cache_dir()
    if _thumb_cache is None or _thumb_cache_dir != directory:
        _thumb_cache = DiskCache(directory, size_limit_bytes=THUMB_CACHE_SIZE_LIMIT_BYTES)
        _thumb_cache_dir = directory
    return _thumb_cache


def build_thumbnail(path: str, size: int, out_path: str) -> bool:
    from wafer.plugin.imageloader.handler import image_loader_resolver

    img = image_loader_resolver.load_pil(path, size)
    if img is None:
        AppLogger.warning(f"WebUI thumbnail failed for {path}: no image loader could decode it")
        return False
    try:
        img.thumbnail((size, size))
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "transparency" in img.info or img.mode in ("P", "LA") else "RGB")
        img.save(out_path, "WEBP", quality=80, method=4)
        return True
    except OSError as e:
        AppLogger.warning(f"WebUI thumbnail failed for {path}: {e}")
        return False


def resolve_image_source(path: str) -> str | None:
    from wafer.plugin.imageloader.handler import image_loader_resolver

    plan = image_loader_resolver.resolve_plan(path)
    if plan is None or not os.path.isfile(plan.resolved_path):
        return None
    return plan.resolved_path

from __future__ import annotations

import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

from wafer.constants import VIRTUAL_PATH_SEPARATOR
from wafer.core.files.disk_cache import DiskCache
from wafer.utils.logs import AppLogger
from wafer.utils.paths import resolve_cache_path

from .session import QUERY_SERVICE

IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".tif", ".avif", ".jfif"})
VIDEO_EXTS = frozenset({".mp4", ".webm", ".m4v", ".ogv", ".mov", ".mkv", ".avi", ".wmv", ".flv", ".ts"})
NATIVE_VIDEO_EXTS = frozenset({".mp4", ".webm", ".m4v", ".ogv"})

THUMB_SIZE_DEFAULT = 256
THUMB_SIZE_MAX = 1024
THUMB_CACHE_SIZE_LIMIT_BYTES = 512 * 1024 * 1024

MEDIA_EXECUTOR = web.AppKey("media_executor", ThreadPoolExecutor)

routes = web.RouteTableDef()


def classify(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in NATIVE_VIDEO_EXTS:
        return "video"
    if ext in VIDEO_EXTS:
        return "video-unsupported"
    return "other"


async def lookup_db_row(request: web.Request) -> tuple[str, str]:
    db = request.query.get("db", "")
    path = request.query.get("path", "")
    if not db or not path:
        raise web.HTTPBadRequest(reason="db and path are required")
    query_service = request.app[QUERY_SERVICE]
    try:
        service = query_service.db(db)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {db}") from None
    found = await service.run(service.lookup_file, path)
    if found is None:
        raise web.HTTPNotFound(reason="file is not registered in the database")
    logical, source = found[0], found[1]
    if not os.path.isfile(source):
        raise web.HTTPNotFound(reason="file does not exist on disk")
    return logical, source


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


@routes.get("/api/thumb")
async def get_thumb(request: web.Request):
    logical, source = await lookup_db_row(request)
    try:
        size = int(request.query.get("size", THUMB_SIZE_DEFAULT))
    except ValueError:
        raise web.HTTPBadRequest(reason="invalid size") from None
    if size <= 0:
        raise web.HTTPBadRequest(reason="size must be positive")
    size = min(size, THUMB_SIZE_MAX)
    stat = os.stat(source)
    key = f"{logical}|{stat.st_mtime_ns}|{stat.st_size}|{size}"
    cache = thumb_cache()
    executor = request.app[MEDIA_EXECUTOR]
    produce = functools.partial(build_thumbnail, logical, size)
    cache_path = await asyncio.get_running_loop().run_in_executor(
        executor, functools.partial(cache.get_or_create, key, produce, ".webp")
    )
    if cache_path is None:
        raise web.HTTPUnprocessableEntity(reason="thumbnail generation failed")
    return web.FileResponse(str(cache_path), headers={"Content-Type": "image/webp", "Cache-Control": "max-age=86400"})


@routes.get("/api/file")
async def get_file(request: web.Request):
    logical, source = await lookup_db_row(request)
    if VIRTUAL_PATH_SEPARATOR in logical:
        executor = request.app[MEDIA_EXECUTOR]
        resolved = await asyncio.get_running_loop().run_in_executor(executor, resolve_image_source, logical)
        if resolved is None:
            raise web.HTTPNotFound(reason="virtual file could not be materialized")
        return web.FileResponse(resolved, headers={"Accept-Ranges": "bytes"})
    return web.FileResponse(source, headers={"Accept-Ranges": "bytes"})

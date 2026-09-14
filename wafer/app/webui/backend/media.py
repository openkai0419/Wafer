from __future__ import annotations

import asyncio
import functools
import os
from concurrent.futures import ThreadPoolExecutor

from aiohttp import web

from wafer.constants import VIRTUAL_PATH_SEPARATOR
from wafer.web.media import (
    THUMB_SIZE_DEFAULT,
    THUMB_SIZE_MAX,
    build_thumbnail,
    resolve_image_source,
    thumb_cache,
)

from .session import QUERY_SERVICE

MEDIA_EXECUTOR = web.AppKey("media_executor", ThreadPoolExecutor)

routes = web.RouteTableDef()


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
    cache_path = await asyncio.get_running_loop().run_in_executor(executor, functools.partial(cache.get_or_create, key, produce, ".webp"))
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

from __future__ import annotations

import asyncio
import os
import re
import sqlite3
from array import array

from aiohttp import web

from wafer.core.common.folder_scan import scan_children, scan_roots
from wafer.core.db.path_scope import compile_ignore_patterns, path_in_scope
from wafer.core.db.setting_db import SettingDB
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.core.logs import AppLogger
from wafer.core.common.formatting import format_file_entries, format_source_entries
from wafer.core.common.paths import normalize_path, safe_is_dir, setting_db_path
from wafer.web.media import classify

from .session import QUERY_SERVICE

ITEMS_LIMIT_MAX = 5000

routes = web.RouteTableDef()


def get_session_or_404(request: web.Request):
    session = request.app[QUERY_SERVICE].session(request.match_info["query_id"])
    if session is None:
        raise web.HTTPNotFound(reason="query session not found or expired")
    return session


@routes.get("/api/dbs")
async def get_dbs(request: web.Request):
    return web.json_response({"dbs": request.app[QUERY_SERVICE].list_dbs()})


@routes.post("/api/query")
async def post_query(request: web.Request):
    try:
        body = await request.json()
    except ValueError:
        raise web.HTTPBadRequest(reason="invalid JSON body") from None
    if not isinstance(body, dict):
        raise web.HTTPBadRequest(reason="request body must be a JSON object")
    db = body.get("db", "")
    filters = body.get("filters") or []
    sort = body.get("sort", "none")
    ascending = bool(body.get("ascending", True))
    if not db:
        raise web.HTTPBadRequest(reason="db is required")
    if not isinstance(filters, list):
        raise web.HTTPBadRequest(reason="filters must be a list")
    if not isinstance(sort, str):
        raise web.HTTPBadRequest(reason="sort must be a string")
    try:
        session = await request.app[QUERY_SERVICE].execute(db, filters, sort, ascending)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {db}") from None
    except ValueError as e:
        raise web.HTTPBadRequest(reason=str(e)) from None
    return web.json_response({"query_id": session.query_id, "total": session.total})


@routes.get("/api/query/{query_id}/aspects")
async def get_aspects(request: web.Request):
    session = get_session_or_404(request)
    data = array("f", session.aspects).tobytes()
    return web.Response(body=data, content_type="application/octet-stream")


def read_source_modified(engine, sources: list[str]) -> dict[str, float]:
    unique = list(dict.fromkeys(sources))
    if not unique or not engine._connect_if_needed():
        return {}
    placeholders = ",".join("?" * len(unique))
    return {row[0]: row[1] for row in engine.fetch(f"SELECT source, modified FROM sources WHERE source IN ({placeholders})", unique)}


@routes.get("/api/query/{query_id}/items")
async def get_items(request: web.Request):
    session = get_session_or_404(request)
    try:
        offset = max(int(request.query.get("offset", 0)), 0)
        limit = min(max(int(request.query.get("limit", 200)), 1), ITEMS_LIMIT_MAX)
    except ValueError:
        raise web.HTTPBadRequest(reason="invalid offset/limit") from None
    indices = range(offset, min(offset + limit, session.total))
    try:
        service = request.app[QUERY_SERVICE].db(session.db)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {session.db}") from None
    modified = await service.run(read_source_modified, service.engine, [session.sources[i] for i in indices])
    items = []
    for i in indices:
        path = session.paths[i]
        source = session.sources[i]
        items.append(
            {
                "i": i,
                "path": path,
                "source": source,
                "name": os.path.basename(path),
                "kind": classify(path),
                "mtime": modified.get(source),
            }
        )
    return web.json_response({"items": items, "db": session.db})


def read_metadata(engine, path: str):
    return engine.get_all_metadata_with_locks(path), engine.get_collection_status(path)


@routes.get("/api/meta")
async def get_meta(request: web.Request):
    db = request.query.get("db", "")
    path = request.query.get("path", "")
    if not db or not path:
        raise web.HTTPBadRequest(reason="db and path are required")
    try:
        service = request.app[QUERY_SERVICE].db(db)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {db}") from None
    (source, file_record, _, tags, meta), collectors = await service.run(read_metadata, service.engine, path)
    return web.json_response(
        {
            "file": format_file_entries(file_record),
            "source": format_source_entries(source),
            "collectors": sorted(collectors),
            "meta": {k: {"value": v, "locked": locked} for k, (v, locked) in meta.items()},
            "tags": {k: {"value": v, "locked": locked} for k, (v, locked) in tags.items()},
        }
    )


def read_setting_folders(db_name: str) -> tuple[list[str], set[str], re.Pattern[str] | None]:
    db_file = str(setting_db_path(db_name))
    if not os.path.isfile(db_file):
        return [], set(), None
    try:
        roots, ignored, patterns = SettingDB(db_file).get_all_folder_settings()
    except sqlite3.Error as e:
        AppLogger.warning(f"WebUI failed to read setting DB for {db_name}: {e}")
        return [], set(), None
    return roots, {normalize_path(p) for p in ignored}, compile_ignore_patterns(patterns)


def folder_entries(entries: list[tuple[str, bool]]) -> list[dict]:
    return [{"path": path, "has_children": has_children} for path, has_children in entries]


@routes.get("/api/folders")
async def get_folders(request: web.Request):
    db = request.query.get("db", "")
    if not db:
        raise web.HTTPBadRequest(reason="db is required")
    if db not in request.app[QUERY_SERVICE].list_dbs():
        raise web.HTTPNotFound(reason=f"unknown db: {db}")
    loop = asyncio.get_running_loop()
    roots, ignored, pattern = await loop.run_in_executor(None, read_setting_folders, db)
    parent = request.query.get("path", "")
    if not parent:
        return web.json_response({"folders": folder_entries(await loop.run_in_executor(None, scan_roots, roots, ignored, pattern))})
    parent = normalize_path(parent)
    if not path_in_scope(parent, roots, ignored, pattern):
        raise web.HTTPForbidden(reason="path is outside of indexed folders")
    if not await loop.run_in_executor(None, safe_is_dir, parent):
        raise web.HTTPNotFound(reason="folder not found")
    return web.json_response({"folders": folder_entries(await loop.run_in_executor(None, scan_children, parent, ignored, pattern))})


@routes.get("/api/keys")
async def get_keys(request: web.Request):
    db = request.query.get("db", "")
    if not db:
        raise web.HTTPBadRequest(reason="db is required")
    try:
        keys = await request.app[QUERY_SERVICE].keys(db)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {db}") from None
    return web.json_response({"keys": [[key, count] for key, count in keys]})


@routes.get("/api/filters")
async def get_filters(request: web.Request):
    filters = [{"name": cls.NAME, "display_name": cls.DISPLAY_NAME or cls.NAME} for cls in filter_registry.list_all() if not cls.INTERNAL_FILTER]
    return web.json_response({"filters": filters})


@routes.get("/api/sorts")
async def get_sorts(request: web.Request):
    return web.json_response({"sorts": sort_registry.names()})

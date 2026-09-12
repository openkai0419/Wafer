from __future__ import annotations

import os
import sqlite3
from array import array

from aiohttp import web

from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.utils.logs import AppLogger
from wafer.utils.paths import normalize_path, safe_is_dir, setting_db_path
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


@routes.get("/api/query/{query_id}/items")
async def get_items(request: web.Request):
    session = get_session_or_404(request)
    try:
        offset = max(int(request.query.get("offset", 0)), 0)
        limit = min(max(int(request.query.get("limit", 200)), 1), ITEMS_LIMIT_MAX)
    except ValueError:
        raise web.HTTPBadRequest(reason="invalid offset/limit") from None
    items = []
    for i in range(offset, min(offset + limit, session.total)):
        path = session.paths[i]
        items.append(
            {
                "i": i,
                "path": path,
                "source": session.sources[i],
                "name": os.path.basename(path),
                "kind": classify(path),
            }
        )
    return web.json_response({"items": items, "db": session.db})


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
    meta = await service.run(service.engine.get_meta_info_with_lock_by_path, path)
    file_hash, tags = await service.run(service.engine.get_tags_with_lock_by_path, path)
    return web.json_response(
        {
            "meta": {k: {"value": v, "locked": locked} for k, (v, locked) in meta.items()},
            "tags": {k: {"value": v, "locked": locked} for k, (v, locked) in tags.items()},
            "file_hash": file_hash,
        }
    )


def read_setting_folders(db_name: str) -> tuple[list[str], list[str]]:
    db_file = str(setting_db_path(db_name))
    if not os.path.isfile(db_file):
        return [], []
    try:
        con = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
        try:
            roots = [r[0] for r in con.execute("SELECT path FROM parent_folders ORDER BY path")]
            ignored = [r[0] for r in con.execute("SELECT path FROM ignore_folders ORDER BY path")]
        finally:
            con.close()
        return roots, ignored
    except sqlite3.Error as e:
        AppLogger.warning(f"WebUI failed to read setting DB for {db_name}: {e}")
        return [], []


def list_subfolders(parent: str, ignored: list[str]) -> list[str]:
    result = []
    try:
        with os.scandir(parent) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    p = normalize_path(entry.path)
                    if p not in ignored:
                        result.append(p)
    except OSError as e:
        AppLogger.warning(f"WebUI folder scan failed for {parent}: {e}")
    result.sort()
    return result


def is_under_roots(path: str, roots: list[str]) -> bool:
    p = path.casefold() if os.name == "nt" else path
    for root in roots:
        r = normalize_path(root)
        r = r.casefold() if os.name == "nt" else r
        if p == r or p.startswith(r + "/"):
            return True
    return False


@routes.get("/api/folders")
async def get_folders(request: web.Request):
    db = request.query.get("db", "")
    if not db:
        raise web.HTTPBadRequest(reason="db is required")
    if db not in request.app[QUERY_SERVICE].list_dbs():
        raise web.HTTPNotFound(reason=f"unknown db: {db}")
    roots, ignored = read_setting_folders(db)
    parent = request.query.get("path", "")
    if not parent:
        return web.json_response({"folders": roots})
    parent = normalize_path(parent)
    if not is_under_roots(parent, roots):
        raise web.HTTPForbidden(reason="path is outside of indexed folders")
    if not safe_is_dir(parent):
        raise web.HTTPNotFound(reason="folder not found")
    return web.json_response({"folders": list_subfolders(parent, ignored)})


@routes.get("/api/keys")
async def get_keys(request: web.Request):
    db = request.query.get("db", "")
    if not db:
        raise web.HTTPBadRequest(reason="db is required")
    service_hub = request.app[QUERY_SERVICE]
    try:
        service = service_hub.db(db)
    except KeyError:
        raise web.HTTPNotFound(reason=f"unknown db: {db}") from None
    keys = await service.run(service_hub.composer.list_all_keys, service.engine, [], True)
    return web.json_response({"keys": [[key, count] for key, count in keys]})


@routes.get("/api/filters")
async def get_filters(request: web.Request):
    filters = [{"name": cls.NAME, "display_name": cls.DISPLAY_NAME or cls.NAME} for cls in filter_registry.list_all() if not cls.INTERNAL_FILTER]
    return web.json_response({"filters": filters})


@routes.get("/api/sorts")
async def get_sorts(request: web.Request):
    return web.json_response({"sorts": sort_registry.names()})

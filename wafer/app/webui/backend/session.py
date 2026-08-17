from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from aiohttp import web

from wafer.builtins.filters import ContainedFilesFilter, DirectoryFilter, SourceChildrenFilter, TextFilter
from wafer.builtins.sorts import CollectedSort, CreatedSort, ModifiedSort, NaturalNameSort, NaturalPathSort, NoSort, RandomSort, SizeSort
from wafer.core.db.query import FileSearchEngine
from wafer.plugin.query.composer import SearchComposer
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.utils.logs import AppLogger
from wafer.utils.paths import data_db_path, list_data_db_names

SESSION_LIMIT = 8
SESSION_TTL = 3600.0

BUILTIN_FILTERS = (TextFilter, DirectoryFilter, ContainedFilesFilter, SourceChildrenFilter)
BUILTIN_SORTS = (NoSort, NaturalPathSort, NaturalNameSort, ModifiedSort, CreatedSort, SizeSort, CollectedSort, RandomSort)


def register_builtin_query_plugins():
    for cls in BUILTIN_FILTERS:
        filter_registry.register(cls)
    for cls in BUILTIN_SORTS:
        sort_registry.register(cls)


@dataclass
class QuerySession:
    query_id: str
    db: str
    paths: list[str]
    sources: list[str]
    aspects: list[float]
    created: float = field(default_factory=time.monotonic)
    last_access: float = field(default_factory=time.monotonic)

    @property
    def total(self) -> int:
        return len(self.paths)


class DbService:
    def __init__(self, name: str):
        self.name = name
        self.engine = FileSearchEngine(data_db_path(name))
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"webdb-{name}")

    async def run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)

    def lookup_file(self, path: str) -> tuple[str, str] | None:
        engine = self.engine
        if not engine._connect_if_needed():
            return None
        rows = engine.fetch("SELECT path, source FROM files WHERE path = ?", [engine._normalize_path(path)])
        if not rows:
            return None
        return rows[0]["path"], rows[0]["source"]

    def close(self):
        self.executor.submit(self.engine.close).result()
        self.executor.shutdown(wait=True, cancel_futures=True)


class QueryService:
    def __init__(self):
        self._dbs: dict[str, DbService] = {}
        self._sessions: OrderedDict[str, QuerySession] = OrderedDict()
        self.composer = SearchComposer()
        register_builtin_query_plugins()

    @staticmethod
    def list_dbs() -> list[str]:
        return list_data_db_names()

    def db(self, name: str) -> DbService:
        service = self._dbs.get(name)
        if service is None:
            if name not in self.list_dbs():
                raise KeyError(name)
            service = DbService(name)
            self._dbs[name] = service
        return service

    async def execute(self, db_name: str, filters: list[dict], sort: str, ascending: bool) -> QuerySession:
        service = self.db(db_name)
        entries = []
        for item in filters:
            if not isinstance(item, dict):
                raise ValueError("each filter must be an object")
            name = item.get("name")
            if not isinstance(name, str):
                raise ValueError("filter name must be a string")
            cls = filter_registry.get(name)
            if cls is None:
                raise ValueError(f"unknown filter: {name}")
            entries.append((cls, item.get("params") or {}, item.get("op") or "AND"))
        sort_plugin = sort_registry.get(sort) or NoSort
        started = time.perf_counter()
        paths, sources, aspects = await service.run(self.composer.execute, service.engine, entries, sort_plugin, ascending)
        session = QuerySession(uuid.uuid4().hex, db_name, paths, sources, aspects)
        self._store(session)
        AppLogger.info(f"WebUI query db={db_name} filters={len(entries)} sort={sort} -> {session.total} items in {time.perf_counter() - started:.3f}s")
        return session

    def _store(self, session: QuerySession):
        self._sessions[session.query_id] = session
        self._evict()

    def _evict(self):
        now = time.monotonic()
        expired = [k for k, s in self._sessions.items() if now - s.last_access > SESSION_TTL]
        for k in expired:
            del self._sessions[k]
        while len(self._sessions) > SESSION_LIMIT:
            self._sessions.popitem(last=False)

    def session(self, query_id: str) -> QuerySession | None:
        session = self._sessions.get(query_id)
        if session is None:
            return None
        session.last_access = time.monotonic()
        self._sessions.move_to_end(query_id)
        return session

    def close(self):
        for service in self._dbs.values():
            service.close()
        self._dbs.clear()
        self._sessions.clear()


QUERY_SERVICE = web.AppKey("query_service", QueryService)

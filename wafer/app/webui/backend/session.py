from __future__ import annotations

import asyncio
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial

from aiohttp import web

from wafer.builtins.filters import ContainedFilesFilter, DirectoryFilter, SourceChildrenFilter, TextFilter
from wafer.builtins.sorts import CollectedSort, CreatedSort, ModifiedSort, NaturalNameSort, NaturalPathSort, NoSort, RandomSort, SizeSort
from wafer.core.db.query import FileSearchEngine
from wafer.plugin.query.composer import SearchComposer
from wafer.plugin.query.handler import filter_registry, sort_registry
from wafer.core.logs import AppLogger
from wafer.core.common.paths import data_db_path, list_data_db_names

SESSION_LIMIT = 8
SESSION_TTL = 3600.0
KEY_SCAN_RETRY_COOLDOWN = 5.0
DB_CLOSE_TIMEOUT = 5.0

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
        self.executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix=f"webdb-{name}")

    async def run(self, fn, *args):
        return await asyncio.get_running_loop().run_in_executor(self.executor, fn, *args)

    def lookup_file(self, path: str) -> tuple[str, str] | None:
        record = self.engine.get_file_record(path)
        if not record:
            return None
        return record["path"], record["source"]

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.engine.close()


class QueryService:
    def __init__(self):
        self._dbs: dict[str, DbService] = {}
        self._sessions: OrderedDict[str, QuerySession] = OrderedDict()
        self._key_tasks: dict[str, asyncio.Task] = {}
        self._key_cache: dict[str, list[tuple[str, int]]] = {}
        self._key_stale: set[str] = set()
        self._key_version: dict[str, int] = {}
        self._key_retry_after: dict[str, float] = {}
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

    async def keys(self, db_name: str) -> list[tuple[str, int]]:
        service = self.db(db_name)
        cached = self._key_cache.get(db_name)
        if cached is not None and db_name not in self._key_stale:
            return cached
        task = self._key_tasks.get(db_name)
        if task is None:
            retry_after = self._key_retry_after.get(db_name)
            if cached is not None and retry_after is not None and time.monotonic() < retry_after:
                return cached
            version = self._key_version.get(db_name, 0)
            task = asyncio.get_running_loop().create_task(self._scan_keys(service, version))
            task.add_done_callback(partial(self._on_scan_done, db_name))
            self._key_tasks[db_name] = task
        if cached is not None:
            return cached
        return await asyncio.shield(task)

    async def _scan_keys(self, service: DbService, version: int) -> list[tuple[str, int]]:
        started = time.perf_counter()
        try:
            keys = await service.run(self.composer.list_all_keys, service.engine, [], True)
        finally:
            self._key_tasks.pop(service.name, None)
        self._key_cache[service.name] = keys
        self._key_retry_after.pop(service.name, None)
        if self._key_version.get(service.name, 0) == version:
            self._key_stale.discard(service.name)
        AppLogger.info(f"WebUI key scan db={service.name} -> {len(keys)} keys in {time.perf_counter() - started:.3f}s")
        return keys

    def _on_scan_done(self, db_name: str, task: asyncio.Task):
        if task.cancelled():
            return
        error = task.exception()
        if error is not None:
            self._key_stale.add(db_name)
            self._key_retry_after[db_name] = time.monotonic() + KEY_SCAN_RETRY_COOLDOWN
            AppLogger.warning(f"WebUI key scan failed for {db_name}, cached keys kept: {error}")

    def invalidate_keys(self, db_name: str = ""):
        if db_name:
            self._key_stale.add(db_name)
            self._key_version[db_name] = self._key_version.get(db_name, 0) + 1
        else:
            self._key_stale.update(self._key_cache)
            self._key_stale.update(self._key_tasks)
            for name in set(self._key_cache) | set(self._key_tasks):
                self._key_version[name] = self._key_version.get(name, 0) + 1

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

    async def close(self):
        for task in self._key_tasks.values():
            if not task.done():
                task.cancel()
        self._key_tasks.clear()
        self._key_cache.clear()
        self._key_stale.clear()
        self._key_version.clear()
        self._key_retry_after.clear()
        loop = asyncio.get_running_loop()
        for service in self._dbs.values():
            try:
                await asyncio.wait_for(loop.run_in_executor(None, service.close), timeout=DB_CLOSE_TIMEOUT)
            except TimeoutError:
                AppLogger.warning(f"WebUI db close timed out for {service.name}, a background scan may still be running")
        self._dbs.clear()
        self._sessions.clear()


QUERY_SERVICE = web.AppKey("query_service", QueryService)

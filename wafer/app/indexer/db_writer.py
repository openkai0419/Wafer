from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

from ...core.db.file_db import FileDB
from ...utils.profiling import profiler


class DatabaseWriter:
    def __init__(self, db_path: str | Path):
        self._db = FileDB(db_path)

    @property
    def db(self) -> FileDB:
        return self._db

    def start(self):
        self._db.start()

    def close(self):
        self._db.close()

    def initialize(self):
        self._db.initialize_database()

    @profiler.profile
    def delete_sources(self, paths: Sequence[str]):
        self._db.delete_sources_by_paths(paths)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def rename_paths(self, pairs: Sequence[tuple[str, str]]):
        self._db.rename_paths(pairs)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def upsert_sources(self, source_entries, image_entries, meta_info_entries=()):
        self._db.upsert_basic_sources(source_entries, image_entries, meta_info_entries)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def upsert_results(self, image_entries, meta_info_entries, tag_entries, collector_status_entries):
        self._db.upsert_collection_results(
            image_entries,
            meta_info_entries,
            tag_entries,
            collector_status_entries,
        )
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def insert_pending(self, sources, collectors):
        self._db.insert_pending_collection(sources, collectors)

    @profiler.profile
    def mark_dispatched(self, sources, collector):
        self._db.mark_dispatched(sources, collector)

    @profiler.profile
    def reset_stale(self, collectors=None):
        self._db.reset_stale_dispatched(collectors)

    @profiler.profile
    def purge_orphans(self):
        self._db.purge_orphan_records()

    @profiler.profile
    def purge_collector(self, collector: str, *, re_collect: bool = False):
        result = self._db.purge_collector_data(collector, re_collect=re_collect)
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def purge_keys(self, keys: list[str]) -> tuple[int, int]:
        result = self._db.purge_keys(keys)
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def upsert_detacher_results(self, meta_info_entries, tag_entries, collector_status_entries, delete_entries=()):
        self._db.upsert_collection_results(
            [],
            meta_info_entries,
            tag_entries,
            collector_status_entries,
        )
        if delete_entries:
            self._db.delete_meta_and_tags_by_keys(delete_entries)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def checkpoint(self, mode: str = "PASSIVE"):
        self._db.try_checkpoint(mode)

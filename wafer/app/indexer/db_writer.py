from __future__ import annotations

import os
from pathlib import Path
from collections import defaultdict
from collections.abc import Sequence

from ...core.db.file_db import FileDB
from ...utils.hashes import fast_signature_hash
from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
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
    def delete_source_trees(self, paths: Sequence[str]):
        self._db.delete_sources_by_path_prefixes(paths)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def rename_paths(self, pairs: Sequence[tuple[str, str]]) -> list[str]:
        missing = self._db.rename_paths(pairs)
        self._db.try_checkpoint("PASSIVE")
        return missing

    @profiler.profile
    def infer_moved_sources(self, deleted_paths: Sequence[str], candidate_paths: Sequence[str]) -> list[tuple[str, str]]:
        old_paths = [normalize_path(path) for path in deleted_paths if path]
        new_paths = [normalize_path(path) for path in candidate_paths if path]
        if not old_paths or not new_paths:
            return []
        old_signatures = self._db.load_source_signatures(old_paths)
        if not old_signatures:
            return []

        old_by_signature: dict[tuple[str, int | None], list[str]] = defaultdict(list)
        for path, (file_hash, size) in old_signatures.items():
            if file_hash and file_hash != "f":
                old_by_signature[(file_hash, size)].append(path)

        new_by_signature: dict[tuple[str, int | None], list[str]] = defaultdict(list)
        for path in new_paths:
            try:
                stat_result = os.stat(path)
            except OSError:
                continue
            if not os.path.isfile(path):
                continue
            file_hash = fast_signature_hash(path, stat_result.st_size, 256)
            if file_hash and file_hash != "f":
                new_by_signature[(file_hash, stat_result.st_size)].append(path)

        pairs = self._pair_sources_by_signature(old_by_signature, new_by_signature)
        if pairs:
            AppLogger.info(f"watcher inferred move: {len(pairs)} files")
        return pairs

    @staticmethod
    def _pair_sources_by_signature(old_by_signature: dict[tuple[str, int | None], list[str]], new_by_signature: dict[tuple[str, int | None], list[str]]) -> list[tuple[str, str]]:
        pairs: list[tuple[str, str]] = []
        for signature, old_group in old_by_signature.items():
            new_group = new_by_signature.get(signature, [])
            if not new_group:
                continue
            pairs.extend(DatabaseWriter._pair_unique_by_name(old_group, new_group))
            used_old = {old for old, _ in pairs}
            used_new = {new for _, new in pairs}
            remaining_old = [path for path in old_group if path not in used_old]
            remaining_new = [path for path in new_group if path not in used_new]
            if len(remaining_old) == 1 and len(remaining_new) == 1:
                pairs.append((remaining_old[0], remaining_new[0]))
        return pairs

    @staticmethod
    def _pair_unique_by_name(old_group: list[str], new_group: list[str]) -> list[tuple[str, str]]:
        old_by_name: dict[str, list[str]] = defaultdict(list)
        new_by_name: dict[str, list[str]] = defaultdict(list)
        for path in old_group:
            old_by_name[Path(path).name].append(path)
        for path in new_group:
            new_by_name[Path(path).name].append(path)
        pairs: list[tuple[str, str]] = []
        for name, old_paths in old_by_name.items():
            new_paths = new_by_name.get(name, [])
            if len(old_paths) == 1 and len(new_paths) == 1:
                pairs.append((old_paths[0], new_paths[0]))
        return pairs

    @profiler.profile
    def upsert_sources(self, source_entries, image_entries, meta_info_entries=()):
        self._db.upsert_basic_sources(source_entries, image_entries, meta_info_entries)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def upsert_results(self, image_entries, meta_info_entries, tag_entries, collector_status_entries, *, cleanup: bool = True):
        self._db.upsert_collection_results(
            image_entries,
            meta_info_entries,
            tag_entries,
            collector_status_entries,
            cleanup=cleanup,
        )
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def cleanup_source_extensions(self, image_entries, collector_status_entries):
        self._db.cleanup_source_extension_children(image_entries, collector_status_entries)
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
    def delete_orphans(self):
        self._db.delete_orphan_records()

    @profiler.profile
    def reset_collection(self, collector: str | None = None, sources=None, prefixes=None, keys=None, *, delete: bool = False, re_collect: bool = True) -> tuple[int, int, int, int]:
        result = self._db.reset_collection(collector, sources, prefixes, keys, delete=delete, re_collect=re_collect)
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def delete_all_sources(self) -> int:
        result = self._db.delete_all_sources()
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def apply_user_kv(self, paths, upserts, deletes, *, scope: str = "tag", lock_only: bool = False, renames=None):
        result = self._db.apply_user_kv(
            paths,
            upserts,
            deletes,
            scope=scope,
            lock_only=lock_only,
            renames=renames,
        )
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def convert_key_scope(self, key: str, to_scope: str):
        result = self._db.convert_key_scope(key, to_scope)
        self._db.try_checkpoint("PASSIVE")
        return result

    @profiler.profile
    def upsert_parser_results(self, meta_info_entries, tag_entries, collector_status_entries, delete_entries=()):
        self._db.upsert_collection_results(
            [],
            meta_info_entries,
            tag_entries,
            collector_status_entries,
            cleanup=False,
        )
        if delete_entries:
            self._db.delete_meta_and_tags_by_keys(delete_entries)
        self._db.try_checkpoint("PASSIVE")

    @profiler.profile
    def checkpoint(self, mode: str = "PASSIVE"):
        self._db.try_checkpoint(mode)

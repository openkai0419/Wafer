from __future__ import annotations
import bisect
import os
import threading
from pathlib import Path
from typing import Sequence

from .file_db import FileDB
from ...utils.paths import normalize_path
from ...utils.hashes import fast_signature_hash
from ...utils.profiling import profiler
from ...utils.logs import AppLogger
_CHUNK = 400


class FileIndexer:

    def __init__(self, db_path, collectors=None):
        self.db = FileDB(db_path)
        self.exclude_paths = set()
        self._progress_callback = None
        self._update_callback = None
        self._collectors = collectors or []
        self._ref_count = 0
        self._ref_lock = threading.Lock()

    @property
    def db_path(self):
        return self.db.db_path

    @profiler.profile
    def initialize(self):
        if not self.db.conn:
            raise Exception('please use with __enter__')
        self.db.initialize_database()
        AppLogger.info(f'image indexer init end {self.db.db_path}')

    def set_progress_callback(self, callback):
        self._progress_callback = callback
        AppLogger.debug(f'Progress callback set: {callback}')

    def set_update_callback(self, callback):
        self._update_callback = callback

    @profiler.profile
    def emit_update(self):
        if self._update_callback:
            self._update_callback()
        else:
            AppLogger.debug('Update callback is not set')

    @profiler.profile
    def _add_progress(self, current, total):
        if self._progress_callback:
            self._progress_callback(current, total)
        else:
            AppLogger.debug('Progress callback is not set')

    @profiler.profile
    def start(self):
        with self._ref_lock:
            if self._ref_count == 0:
                self.db.start()
            self._ref_count += 1

    @profiler.profile
    def close(self):
        with self._ref_lock:
            self._ref_count -= 1
            if self._ref_count <= 0:
                self._ref_count = 0
                self.db.close()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def try_checkpoint(self, mode='TRUNCATE'):
        self.db.try_checkpoint(mode)

    @profiler.profile
    def set_exclude_paths(self, paths, run=False):
        sorted_paths = sorted(normalize_path(p) for p in paths)
        self.exclude_paths = sorted_paths
        AppLogger.info(f'[ExcludePaths] {len(self.exclude_paths)} paths set.')
        if run:
            self.remove_excluded_from_db()

    @profiler.profile
    def is_path_excluded(self, path):
        if not self.exclude_paths:
            return False
        idx = bisect.bisect_right(self.exclude_paths, path)
        if idx > 0:
            candidate = self.exclude_paths[idx - 1]
            if path == candidate or path.startswith(candidate + '/'):
                return True
        return False

    @profiler.profile
    def remove_excluded_from_db(self):
        if not self.exclude_paths:
            return
        AppLogger.info('[ExcludePaths] Removing existing entries under exclude paths...')
        cur = self.db.get_reader_cursor()
        cur.execute('SELECT source FROM sources')
        all_paths = [normalize_path(row[0]) for row in cur.fetchall()]
        cur.close()
        to_remove = [p for p in all_paths if self.is_path_excluded(p)]
        if not to_remove:
            AppLogger.info('[ExcludePaths] No matching entries to remove.')
            return
        self._add_progress(0, len(to_remove))
        for i in range(0, len(to_remove), _CHUNK):
            chunk = to_remove[i:i + _CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        AppLogger.info(f'[ExcludePaths] Removed {len(to_remove)} entries from DB.')
        self.emit_update()

    @profiler.profile
    def load_existing_sources(self):
        prev = self.db.load_existing_sources()
        return {normalize_path(k): v for k, v in prev.items()}

    @profiler.profile
    def _detect_diff(self, current, previous):
        added_or_modified = [p for p in current if p not in previous or current[p] != previous[p]]
        removed = [p for p in previous if p not in current]
        return (added_or_modified, removed)

    @staticmethod
    def _get_stat(stat):
        ctime = stat.st_birthtime if hasattr(stat, 'st_birthtime') else stat.st_ctime
        return (stat.st_mtime, stat.st_size, ctime)

    @profiler.profile
    def scan_directory_fast(self, root_path):
        stack = [str(root_path)]
        while stack:
            current = stack.pop()
            self._add_progress(0, 1)
            full_path = normalize_path(current)
            if self.is_path_excluded(full_path):
                AppLogger.debug(f'[Excluded] Skipping file: {full_path}')
                self._add_progress(1, 0)
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False):
                            yield (normalize_path(entry.path), self._get_stat(entry.stat()))
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                self._add_progress(1, 0)
            except Exception as e:
                AppLogger.debug(f'scan_directory_fast error: {current} ({e})')
                self._add_progress(1, 0)
                continue

    @profiler.profile
    def update_index(self, root_paths: Sequence[str] | str):
        if isinstance(root_paths, str):
            root_paths = [root_paths]
        AppLogger.info('UPDATE_INDEX')
        current_compare = {}
        file_info = {}
        self._add_progress(0, 1)
        for path in root_paths:
            for norm_p, info in self.scan_directory_fast(path):
                mtime, fsize, ctime = info
                current_compare[norm_p] = (mtime, fsize)
                file_info[norm_p] = (mtime, fsize, ctime)
        self._add_progress(1, 0)

        previous = self.load_existing_sources()
        added_or_modified, removed = self._detect_diff(current_compare, previous)
        self._add_progress(0, len(added_or_modified))
        self._add_progress(0, len(removed))
        AppLogger.info(f'added/modified: {len(added_or_modified)}, removed: {len(removed)}')

        if removed:
            for i in range(0, len(removed), _CHUNK):
                chunk = removed[i:i + _CHUNK]
                self.db.delete_sources_by_paths(chunk)
                self._add_progress(len(chunk), 0)
            AppLogger.info(f'deleted {len(removed)} files')
            self.db.try_checkpoint('PASSIVE')
            self.emit_update()

        if added_or_modified:
            self._register_basic_info(added_or_modified, file_info)

    @profiler.profile
    def update_by_file_list(self, file_paths):
        file_paths = [p for p in file_paths if os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        normalized = [p for p in normalized if not self.is_path_excluded(p)]
        stat_info = {}
        for path in normalized:
            try:
                st = os.stat(path)
                stat_info[path] = self._get_stat(st)
            except FileNotFoundError:
                pass
        if not stat_info:
            AppLogger.info('No valid files to update.')
            return
        previous = {}
        keys = list(stat_info.keys())
        cur = self.db.get_reader_cursor()
        for i in range(0, len(keys), _CHUNK):
            chunk = keys[i:i + _CHUNK]
            cur.execute(
                f"SELECT source, modified, size FROM sources WHERE source IN ({','.join(['?'] * len(chunk))})",
                chunk,
            )
            previous.update({normalize_path(row[0]): (row[1], row[2]) for row in cur.fetchall()})
        cur.close()
        to_update = [p for p, (mt, sz, ct) in stat_info.items() if p not in previous or (mt, sz) != previous[p]]
        if to_update:
            self._add_progress(0, len(to_update))
            self._register_basic_info(to_update, stat_info)
            self.db.try_checkpoint()
            self.emit_update()
        else:
            AppLogger.info('[update_by_file_list] No updates needed.')

    @profiler.profile
    def remove_by_file_list(self, file_paths):
        file_paths = [p for p in file_paths if not os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        if not normalized:
            return
        self._add_progress(0, len(normalized))
        for i in range(0, len(normalized), _CHUNK):
            chunk = normalized[i:i + _CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        self.db.try_checkpoint()
        self.emit_update()
        AppLogger.info(f'[remove_by_file_list] Removed {len(normalized)} entries from DB')

    @profiler.profile
    def rename_by_pairs(self, pairs):
        normalized = [(normalize_path(old), normalize_path(new)) for old, new in pairs]
        normalized = [(old, new) for old, new in normalized if old != new]
        if not normalized:
            return
        self._add_progress(0, len(normalized))
        for i in range(0, len(normalized), _CHUNK):
            chunk = normalized[i:i + _CHUNK]
            self.db.rename_paths(chunk)
            self._add_progress(len(chunk), 0)
        self.db.try_checkpoint()
        self.emit_update()
        AppLogger.info(f'[rename_by_pairs] Renamed {len(normalized)} entries')

    @profiler.profile
    def _register_basic_info(self, paths, file_info):
        from ..platform.thumbnails import FileThumbnailer
        for i in range(0, len(paths), _CHUNK):
            chunk = paths[i:i + _CHUNK]
            aspect_map = FileThumbnailer.get_aspect_ratios(chunk)
            source_entries = []
            file_entries = []
            meta_entries = []
            for p in chunk:
                mtime, fsize, ctime = file_info.get(p, (0.0, 0, 0.0))
                file_hash = fast_signature_hash(p, fsize, 256)
                name = Path(p).name
                source_entries.append((p, file_hash, fsize, mtime))
                file_entries.append((p, p, name, aspect_map.get(p, 1.0)))
                meta_entries.append((p, 'name', name, None))
                meta_entries.append((p, 'size', str(fsize), float(fsize)))
                meta_entries.append((p, 'modified', str(mtime), mtime))
                meta_entries.append((p, 'created', str(ctime), ctime))
            self.db.upsert_basic_sources(source_entries, file_entries, meta_entries)
            self.db.try_checkpoint('PASSIVE')
            self._add_progress(len(chunk), 0)
            self.emit_update()
        self._insert_pending_by_extension(paths)
        AppLogger.info(f'[Phase1] Registered {len(paths)} files')

    def _insert_pending_by_extension(self, paths):
        if not self._collectors:
            return
        collector_paths = {}
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            for name, extensions in self._collectors:
                if not extensions or ext in extensions:
                    collector_paths.setdefault(name, []).append(p)
        total_pending = 0
        for name, matched_paths in collector_paths.items():
            self.db.insert_pending_collection(matched_paths, [name])
            total_pending += len(matched_paths)
        if total_pending:
            self._add_progress(0, total_pending)

    @profiler.profile
    def backfill_pending_for_collectors(self):
        if not self._collectors:
            return
        for name, extensions in self._collectors:
            sources = self.db.get_sources_without_collector(name)
            if extensions:
                ext_set = set(extensions)
                sources = [p for p in sources if os.path.splitext(p)[1].lower() in ext_set]
            if not sources:
                continue
            for i in range(0, len(sources), _CHUNK):
                chunk = sources[i:i + _CHUNK]
                self.db.insert_pending_collection(chunk, [name])
            AppLogger.info(f'[Backfill] Added {len(sources)} pending entries for "{name}"')

    @profiler.profile
    def purge_orphan_records(self):
        self.db.purge_orphan_records()
        self.emit_update()

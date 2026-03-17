from __future__ import annotations

import bisect
import os
import threading
import time
from pathlib import Path
from typing import Sequence

from ...core.db.db_utils import apply_read_pragmas, connect_with_retry
from ...utils.hashes import fast_signature_hash
from ...utils.logs import AppLogger
from ...utils.paths import normalize_path
from ...utils.profiling import profiler
from .db_writer import DatabaseWriter
from .progress_notifier import ProgressAggregator
from .scheduler import TaskScheduler
from .task import CancelToken, Task, TaskPriority

_CHUNK = 400


class DirectoryScanner:

    def __init__(
        self,
        db_path: str | Path,
        scheduler: TaskScheduler,
        writer: DatabaseWriter,
        progress: ProgressAggregator,
        collectors: list[tuple[str, list[str]]] | None = None,
    ):
        self._db_path = Path(db_path)
        self._scheduler = scheduler
        self._writer = writer
        self._progress = progress
        self._collectors = collectors or []
        self._exclude_paths: list[str] = []
        self._read_conn = None
        self._stop = threading.Event()
        self._request_queue: list[tuple[str, object]] = []
        self._request_lock = threading.Lock()
        self._request_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._current_token = CancelToken()

    def start(self):
        uri = self._db_path.resolve().as_uri()
        self._read_conn = connect_with_retry(
            f'{uri}?mode=ro', timeout=1.0, uri=True, check_same_thread=False,
        )
        apply_read_pragmas(self._read_conn)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        self._request_event.set()
        if self._thread:
            self._thread.join(timeout=10.0)
        if self._read_conn:
            self._read_conn.close()
            self._read_conn = None

    def request_scan(self, folders: list[str]):
        self._cancel_current()
        with self._request_lock:
            self._request_queue.append(('rescan', folders))
        self._request_event.set()

    def request_update(self, paths: list[str]):
        with self._request_lock:
            self._request_queue.append(('update', paths))
        self._request_event.set()

    def set_exclude_paths(self, paths: list[str]):
        sorted_paths = sorted(normalize_path(p) for p in paths)
        self._exclude_paths = sorted_paths
        AppLogger.info(f'[Scanner] Exclude paths set: {len(sorted_paths)}')
        self._submit_remove_excluded()

    def backfill_pending(self):
        with self._request_lock:
            self._request_queue.append(('backfill', None))
        self._request_event.set()

    def _cancel_current(self):
        self._current_token.cancel()
        self._progress.reset()
        self._current_token = CancelToken()

    def _loop(self):
        while not self._stop.is_set():
            self._request_event.wait(timeout=2.0)
            self._request_event.clear()
            if self._stop.is_set():
                break
            with self._request_lock:
                batch = list(self._request_queue)
                self._request_queue.clear()
            for kind, data in batch:
                if self._stop.is_set():
                    break
                if kind == 'rescan':
                    self._do_full_scan(data)
                elif kind == 'update':
                    self._do_update_files(data)
                elif kind == 'backfill':
                    self._do_backfill()

    def _is_excluded(self, path: str) -> bool:
        if not self._exclude_paths:
            return False
        idx = bisect.bisect_right(self._exclude_paths, path)
        if idx > 0:
            candidate = self._exclude_paths[idx - 1]
            if path == candidate or path.startswith(candidate + '/'):
                return True
        return False

    @profiler.profile
    def _do_full_scan(self, root_paths: Sequence[str]):
        AppLogger.info(f'[Scanner] Full scan: {len(root_paths)} folders')
        token = self._current_token
        current_compare: dict[str, tuple] = {}
        file_info: dict[str, tuple] = {}
        self._progress.increment(0, 1)
        for path in root_paths:
            if token.is_cancelled:
                return
            for norm_p, info in self._scan_directory(path):
                mtime, fsize, ctime = info
                current_compare[norm_p] = (mtime, fsize)
                file_info[norm_p] = (mtime, fsize, ctime)
        self._progress.increment(1, 0)

        if token.is_cancelled:
            return

        previous = self._load_existing_sources()
        added_or_modified = [
            p for p in current_compare
            if p not in previous or current_compare[p] != previous[p]
        ]
        removed = [p for p in previous if p not in current_compare]
        self._progress.increment(0, len(added_or_modified) + len(removed))
        AppLogger.info(f'[Scanner] added/modified: {len(added_or_modified)}, removed: {len(removed)}')

        if removed:
            for i in range(0, len(removed), _CHUNK):
                if token.is_cancelled:
                    return
                chunk = removed[i:i + _CHUNK]
                self._scheduler.submit(Task.create(
                    'delete_sources',
                    priority=TaskPriority.SCAN,
                    run=lambda c=chunk: self._writer.delete_sources(c),
                    cancel_token=token,
                    on_complete=lambda n=len(chunk): self._progress.increment(n, 0),
                ))
            self._scheduler.submit(Task.create(
                'checkpoint',
                priority=TaskPriority.SCAN,
                run=lambda: self._writer.checkpoint('PASSIVE'),
                cancel_token=token,
                on_complete=lambda: self._progress.send_event('update'),
            ))

        if added_or_modified:
            self._register_and_submit(added_or_modified, file_info, token)

    @profiler.profile
    def _do_update_files(self, file_paths: list[str]):
        file_paths = [p for p in file_paths if os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        normalized = [p for p in normalized if not self._is_excluded(p)]
        stat_info: dict[str, tuple] = {}
        for path in normalized:
            try:
                st = os.stat(path)
                stat_info[path] = _get_stat(st)
            except FileNotFoundError:
                pass
        if not stat_info:
            AppLogger.info('[Scanner] No valid files to update.')
            return

        previous: dict[str, tuple] = {}
        keys = list(stat_info.keys())
        cur = self._read_conn.cursor()
        for i in range(0, len(keys), _CHUNK):
            chunk = keys[i:i + _CHUNK]
            cur.execute(
                f"SELECT source, modified, size FROM sources WHERE source IN ({','.join(['?'] * len(chunk))})",
                chunk,
            )
            previous.update({normalize_path(row[0]): (row[1], row[2]) for row in cur.fetchall()})
        cur.close()

        to_update = [
            p for p, (mt, sz, ct) in stat_info.items()
            if p not in previous or (mt, sz) != previous[p]
        ]
        if to_update:
            self._progress.increment(0, len(to_update))
            token = self._current_token
            self._register_and_submit(to_update, stat_info, token)
        else:
            AppLogger.info('[Scanner] No updates needed.')

    @profiler.profile
    def _register_and_submit(self, paths: list[str], file_info: dict, token: CancelToken):
        from ...core.platform.thumbnails import FileThumbnailer
        now = time.time()
        for i in range(0, len(paths), _CHUNK):
            if token.is_cancelled:
                return
            chunk = paths[i:i + _CHUNK]
            aspect_map = FileThumbnailer.get_aspect_ratios(chunk)
            source_entries = []
            file_entries = []
            for p in chunk:
                mtime, fsize, ctime = file_info.get(p, (0.0, 0, 0.0))
                file_hash = fast_signature_hash(p, fsize, 256)
                source_entries.append((p, file_hash, fsize, mtime, ctime, now, 'indexed'))
                file_entries.append((p, p, Path(p).name, aspect_map.get(p, 1.0)))
            self._scheduler.submit(Task.create(
                'upsert_sources',
                priority=TaskPriority.SCAN,
                run=lambda se=source_entries, ie=file_entries: self._writer.upsert_sources(se, ie),
                cancel_token=token,
                on_complete=lambda n=len(chunk): (
                    self._progress.increment(n, 0),
                    self._progress.send_event('update'),
                ),
            ))
        self._submit_pending_by_extension(paths, token)
        AppLogger.info(f'[Scanner] Registered {len(paths)} files')

    def _submit_pending_by_extension(self, paths: list[str], token: CancelToken):
        if not self._collectors:
            return
        collector_paths: dict[str, list[str]] = {}
        for p in paths:
            ext = os.path.splitext(p)[1].lower()
            for name, extensions in self._collectors:
                if not extensions or ext in extensions:
                    collector_paths.setdefault(name, []).append(p)
        total_pending = 0
        for name, matched_paths in collector_paths.items():
            self._scheduler.submit(Task.create(
                'insert_pending',
                priority=TaskPriority.SCAN,
                run=lambda mp=matched_paths, n=name: self._writer.insert_pending(mp, [n]),
                cancel_token=token,
            ))
            total_pending += len(matched_paths)
        if total_pending:
            self._progress.increment(0, total_pending)

    def _submit_remove_excluded(self):
        if not self._exclude_paths:
            return
        if not self._read_conn:
            return
        cur = self._read_conn.cursor()
        cur.execute('SELECT source FROM sources')
        all_paths = [normalize_path(row[0]) for row in cur.fetchall()]
        cur.close()
        to_remove = [p for p in all_paths if self._is_excluded(p)]
        if not to_remove:
            return
        token = self._current_token
        self._progress.increment(0, len(to_remove))
        for i in range(0, len(to_remove), _CHUNK):
            chunk = to_remove[i:i + _CHUNK]
            self._scheduler.submit(Task.create(
                'delete_sources',
                priority=TaskPriority.SCAN,
                run=lambda c=chunk: self._writer.delete_sources(c),
                cancel_token=token,
                on_complete=lambda n=len(chunk): self._progress.increment(n, 0),
            ))
        AppLogger.info(f'[Scanner] Submitted removal of {len(to_remove)} excluded entries')

    def _do_backfill(self):
        if not self._collectors:
            return
        token = self._current_token
        cur = self._read_conn.cursor()
        for name, extensions in self._collectors:
            if token.is_cancelled:
                break
            cur.execute(
                '''SELECT s.source FROM sources s
                WHERE NOT EXISTS (
                    SELECT 1 FROM collection_status cs
                    WHERE cs.source = s.source AND cs.collector = ?
                )''',
                (name,),
            )
            sources = [row[0] for row in cur.fetchall()]
            if extensions:
                ext_set = set(extensions)
                sources = [p for p in sources if os.path.splitext(p)[1].lower() in ext_set]
            if not sources:
                continue
            for i in range(0, len(sources), _CHUNK):
                chunk = sources[i:i + _CHUNK]
                self._scheduler.submit(Task.create(
                    'insert_pending',
                    priority=TaskPriority.SCAN,
                    run=lambda c=chunk, n=name: self._writer.insert_pending(c, [n]),
                    cancel_token=token,
                ))
            AppLogger.info(f'[Scanner] Backfill: {len(sources)} pending for "{name}"')
        cur.close()

    def _load_existing_sources(self) -> dict[str, tuple[float, int]]:
        result: dict[str, tuple[float, int]] = {}
        try:
            cur = self._read_conn.cursor()
            cur.execute('SELECT source, modified, size FROM sources')
            for source, mtime, size in cur.fetchall():
                result[normalize_path(source)] = (mtime, size)
            cur.close()
        except Exception as e:
            AppLogger.warning(f'[Scanner] Failed to load existing sources: {e}', exc=e)
        return result

    def _scan_directory(self, root_path: str):
        stack = [str(root_path)]
        while stack:
            current = stack.pop()
            self._progress.increment(0, 1)
            full_path = normalize_path(current)
            if self._is_excluded(full_path):
                self._progress.increment(1, 0)
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False):
                            yield (normalize_path(entry.path), _get_stat(entry.stat()))
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                self._progress.increment(1, 0)
            except Exception as e:
                AppLogger.debug(f'[Scanner] scan error: {current} ({e})')
                self._progress.increment(1, 0)


def _get_stat(stat_result):
    ctime = stat_result.st_birthtime if hasattr(stat_result, 'st_birthtime') else stat_result.st_ctime
    return (stat_result.st_mtime, stat_result.st_size, ctime)

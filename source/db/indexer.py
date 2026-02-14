from __future__ import annotations
import concurrent.futures
import os
import queue
import threading
import time
from pathlib import Path
from typing import Sequence

from source.io.manager import ReaderClass
from .image_db import ImageDB
from ..common.funcs import IMAGE_EXTENSIONS, normalize_path
from ..common.hashes import fast_sig_hash
from ..common.profiling import logger, profiler

_CHUNK = 900
_executor = concurrent.futures.ThreadPoolExecutor()


class ImageIndexer:

    def __init__(self, db_path):
        self.db = ImageDB(db_path)
        self.exclude_paths = set()
        self._progress_callback = None
        self._update_callback = None

    @property
    def db_path(self):
        return self.db.db_path

    @profiler.profile
    def check_init(self):
        if not self.db.conn:
            raise Exception('please use with __enter__')
        self.db.initialize_database()
        logger.info(f'image indexer init end {self.db.db_path}')

    def set_progress_callback(self, callback):
        self._progress_callback = callback
        logger.debug('Progress callback set: %s', callback)

    def set_update_callback(self, callback):
        self._update_callback = callback

    @profiler.profile
    def emit_update(self):
        if self._update_callback:
            self._update_callback()
        else:
            logger.debug('Update callback is not set')

    @profiler.profile
    def _add_progress(self, current, total):
        if self._progress_callback:
            self._progress_callback(current, total)
        else:
            logger.debug('Progress callback is not set')

    @profiler.profile
    def start(self):
        self.db.start()

    @profiler.profile
    def exit(self):
        self.db.exit()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()

    def try_checkpoint(self, mode='TRUNCATE'):
        self.db.try_checkpoint(mode)

    @profiler.profile
    def set_exclude_paths(self, paths, run=False):
        self.exclude_paths = {normalize_path(p) for p in paths}
        logger.info(f'[ExcludePaths] {len(self.exclude_paths)} paths set.')
        if run:
            self.remove_excluded_from_db()

    @profiler.profile
    def is_path_excluded(self, path):
        for ex in self.exclude_paths:
            if path == ex or path.startswith(ex + '/'):
                return True
        return False

    @profiler.profile
    def remove_excluded_from_db(self):
        if not self.exclude_paths:
            return
        logger.info('[ExcludePaths] Removing existing entries under exclude paths...')
        cur = self.db.get_reader_cursor()
        cur.execute('SELECT source FROM sources')
        all_paths = [normalize_path(row[0]) for row in cur.fetchall()]
        cur.close()
        to_remove = [p for p in all_paths if self.is_path_excluded(p)]
        if not to_remove:
            logger.info('[ExcludePaths] No matching entries to remove.')
            return
        self._add_progress(0, len(to_remove))
        for i in range(0, len(to_remove), _CHUNK):
            chunk = to_remove[i:i + _CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        logger.info(f'[ExcludePaths] Removed {len(to_remove)} entries from DB.')
        self.emit_update()

    @profiler.profile
    def load_previous(self):
        prev = self.db.load_previous()
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
                logger.debug(f'[Excluded] Skipping file: {full_path}')
                self._add_progress(1, 0)
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(IMAGE_EXTENSIONS):
                            yield (normalize_path(entry.path), self._get_stat(entry.stat()))
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                self._add_progress(1, 0)
            except Exception:
                self._add_progress(1, 0)
                continue

    @profiler.profile
    def update_index(self, root_paths: Sequence[str] | str):
        if isinstance(root_paths, str):
            root_paths = [root_paths]
        logger.info('UPDATE_INDEX')
        current_compare = {}
        file_info = {}
        for path in root_paths:
            self._add_progress(0, 1)
            for norm_p, info in self.scan_directory_fast(path):
                mtime, fsize, ctime = info
                current_compare[norm_p] = (mtime, fsize)
                file_info[norm_p] = (mtime, fsize, ctime)
            self._add_progress(1, 0)

        previous = self.load_previous()
        added_or_modified, removed = self._detect_diff(current_compare, previous)
        self._add_progress(0, len(added_or_modified))
        self._add_progress(0, len(removed))
        logger.info('added/modified: {}, removed: {}'.format(len(added_or_modified), len(removed)))

        if removed:
            for i in range(0, len(removed), _CHUNK):
                chunk = removed[i:i + _CHUNK]
                self.db.delete_sources_by_paths(chunk)
                self._add_progress(len(chunk), 0)
            logger.info(f'deleted {len(removed)} files')
            self.db.try_checkpoint('PASSIVE')
            self.emit_update()

        if added_or_modified:
            self._update_meta_and_image(added_or_modified, file_info)

    @profiler.profile
    def update_by_file_list(self, file_paths):
        total_paths = len(file_paths)
        file_paths = [p for p in file_paths if os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        normalized = [p for p in normalized if not self.is_path_excluded(p)]
        self._add_progress(total_paths - len(normalized), 0)
        stat_info = {}
        for path in normalized:
            try:
                st = os.stat(path)
                stat_info[path] = self._get_stat(st)
            except FileNotFoundError:
                self._add_progress(1, 0)
        if not stat_info:
            logger.info('No valid files to update.')
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
        skip_count = len(stat_info) - len(to_update)
        if skip_count:
            self._add_progress(skip_count, 0)
        if to_update:
            self._update_meta_and_image(to_update, stat_info)
            self.db.try_checkpoint()
            self.emit_update()
        else:
            logger.info('[update_by_file_list] No updates needed.')

    @profiler.profile
    def remove_by_file_list(self, file_paths):
        total_paths = len(file_paths)
        file_paths = [p for p in file_paths if not os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        self._add_progress(total_paths - len(normalized), 0)
        if not normalized:
            return
        for i in range(0, len(normalized), _CHUNK):
            chunk = normalized[i:i + _CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        self.db.try_checkpoint()
        self.emit_update()
        logger.info(f'[remove_by_file_list] Removed {len(normalized)} entries from DB')

    @staticmethod
    def _read_single(p):
        try:
            return ReaderClass.read(p)
        except Exception:
            norm = normalize_path(p)
            return ({'source': norm, 'path': norm, 'name': Path(p).name, 'aspect': None}, {}, {}, 'fail')

    @profiler.profile
    def _batch_process_images(self, batch, file_info):
        results = list(_executor.map(self._read_single, batch))

        source_entries = set()
        image_entries = []
        meta_info_entries = []
        tag_entries = []

        for info, meta_info, tags, status in results:
            source = info.get('source')
            path   = info.get('path')
            name   = info.get('name')
            aspect = info.get('aspect')
            file_hash = info.get('file_hash')

            mtime, fsize, ctime = file_info.get(source, (0.0, 0, 0.0))
            if not file_hash:
                file_hash = fast_sig_hash(source, fsize, 256)

            source_entries.add((source, file_hash, fsize, mtime, ctime, time.time(), 'fail' if status == 'fail' else 'ok'))

            if status == 'fail':
                continue

            image_entries.append((path, source, name, aspect))
            meta_info_entries.extend((path, k, v) for k, v in meta_info.items())
            tag_entries.extend((file_hash, k, v) for k, v in tags.items())

        return (list(source_entries), image_entries, meta_info_entries, tag_entries)

    @profiler.profile
    def _update_meta_and_image(self, paths, file_info):
        total = len(paths)
        MIN_BATCH_SIZE = 100
        MAX_BATCH_SIZE = 50000
        batch_size = MIN_BATCH_SIZE
        TARGET_MIN_S = 4.0
        TARGET_MAX_S = 300.0
        QUEUE_MAX = 8
        i = 0
        start_time = time.monotonic()

        write_queue = queue.Queue(maxsize=QUEUE_MAX)

        def writer_thread_func():
            while True:
                item = write_queue.get()
                if item is None:
                    break
                try:
                    self.db.upsert_batches(*item)
                except Exception as e:
                    logger.error(f'[WriterThread] Error in write_batch_to_db: {e}')
                finally:
                    write_queue.task_done()

        writer_thread = threading.Thread(target=writer_thread_func, daemon=True)
        writer_thread.start()

        acc_source = []
        acc_image = []
        acc_meta = []
        acc_tag = []
        acc_duration = 0.0

        while i < total:
            elapsed = time.monotonic() - start_time
            target_s = min(TARGET_MAX_S, TARGET_MIN_S + elapsed / TARGET_MAX_S * (TARGET_MAX_S - TARGET_MIN_S))

            batch = paths[i:i + batch_size]
            t0 = time.monotonic()
            source_entries, image_entries, meta_entries, tag_entries = self._batch_process_images(batch, file_info)
            duration = time.monotonic() - t0

            acc_source.extend(source_entries)
            acc_image.extend(image_entries)
            acc_meta.extend(meta_entries)
            acc_tag.extend(tag_entries)
            acc_duration += duration

            if acc_duration >= target_s or write_queue.qsize() >= int(QUEUE_MAX * 0.8):
                write_queue.put((acc_source, acc_image, acc_meta, acc_tag))
                acc_source, acc_image, acc_meta, acc_tag = [], [], [], []
                acc_duration = 0.0

            if duration > 0:
                if duration < target_s:
                    batch_size = int(batch_size * (target_s / duration) ** 0.5)
                else:
                    batch_size = int(batch_size / (duration / target_s) ** 0.5)

            if write_queue.qsize() >= int(QUEUE_MAX * 0.6):
                batch_size = max(MIN_BATCH_SIZE, int(batch_size * 0.7))

            batch_size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch_size))

            i += len(batch)
            self.db.try_checkpoint('PASSIVE')
            self.emit_update()
            self._add_progress(len(batch), 0)
            logger.info(f'[Adaptive Commit] {i}/{total} processed (batch={len(batch)}, {duration:.2f}s, target={target_s:.2f}s)')

        if acc_source or acc_image or acc_meta or acc_tag:
            write_queue.put((acc_source, acc_image, acc_meta, acc_tag))

        write_queue.join()
        write_queue.put(None)
        writer_thread.join()
        self.db.try_checkpoint()
        self.emit_update()

    @profiler.profile
    def clean_unused(self):
        self.db.clean_unused()
        self.emit_update()

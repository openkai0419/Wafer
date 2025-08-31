
from __future__ import annotations
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Sequence

from .db_utils import connect_with_retry
from ..common.profiling import logger, profiler


class ImageDB:

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix('.bak')
        self.conn: sqlite3.Connection | None = None
        self.read_conn: sqlite3.Connection | None = None

    # ---- lifecycle -----------------------------------------------------
    @profiler.profile
    def start(self):
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=False)
        self._apply_pragmas(self.conn, read_only=False)
        uri = Path(self.db_path).resolve().as_uri()
        self.read_conn = connect_with_retry(f'{uri}?mode=ro', timeout=1.0, uri=True, check_same_thread=False)
        self._apply_pragmas(self.read_conn, read_only=True)

    @profiler.profile
    def exit(self):
        self.try_checkpoint()
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

    # ---- connections & pragmas ----------------------------------------
    def get_writer_cursor(self):
        return self.conn.cursor()

    def get_reader_cursor(self):
        return self.read_conn.cursor()

    @profiler.profile
    def _apply_pragmas(self, conn: sqlite3.Connection, read_only: bool = False):
        if read_only:
            conn.execute('PRAGMA temp_store = MEMORY')
            conn.execute('PRAGMA cache_size = -10000')
            conn.execute('PRAGMA mmap_size = 134217728')
            conn.execute('PRAGMA foreign_keys=ON')
        else:
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA locking_mode=NORMAL')
            conn.execute('PRAGMA foreign_keys=ON')

    def try_checkpoint(self, mode: str = 'TRUNCATE'):
        try:
            conn = self.conn or self.read_conn
            cur = conn.execute(f'PRAGMA wal_checkpoint({mode})')
            cur.close()
        except Exception:
            logger.debug(f'wal_checkpoint({mode}) failed')

    # ---- initialization & schema --------------------------------------
    @profiler.profile
    def initialize_database(self):
        try:
            if not self._integrity_check():
                raise sqlite3.DatabaseError('Integrity check failed.')
        except sqlite3.DatabaseError as e:
            logger.warning(f'[ERROR] DB corrupted: {e}')
            self._backup_and_recreate()
        except:
            raise
        self._ensure_schema()

    @profiler.profile
    def _integrity_check(self) -> bool:
        try:
            result = self.conn.execute('PRAGMA quick_check').fetchone()
            return result[0] == 'ok'
        except Exception as e:
            logger.warning(f'[WARN] integrity_check failed: {e}')
            return False

    @profiler.profile
    def _backup_and_recreate(self):
        if self.read_conn:
            try:
                self.read_conn.close()
            except:  # noqa
                pass
            self.read_conn = None
        if self.conn:
            try:
                self.conn.close()
            except:  # noqa
                pass
            self.conn = None
        # safe backup first
        try:
            tmp = sqlite3.connect(str(self.db_path), check_same_thread=False)
            tmp.execute('PRAGMA journal_mode=WAL')
            tmp.execute('VACUUM INTO ?', (str(self.backup_path),))
            tmp.close()
            for suf in ('', '-wal', '-shm'):
                try:
                    os.remove(str(self.db_path) + suf)
                except FileNotFoundError:
                    pass
        except Exception:
            # fallback copy
            if self.db_path.exists():
                shutil.copy(self.db_path, self.backup_path)
                for suf in ('', '-wal', '-shm'):
                    try:
                        os.remove(str(self.db_path) + suf)
                    except FileNotFoundError:
                        pass
        # recreate
        self.start()
        logger.warning(f'[INFO] New DB created at: {self.db_path}')

    @profiler.profile
    def _ensure_schema(self):
        cur = self.get_writer_cursor()
        cur.executescript(
            """
            PRAGMA foreign_keys=ON;

            -- DATA TABLES
            CREATE TABLE IF NOT EXISTS hash_index (
                file_hash TEXT PRIMARY KEY
            );

            CREATE TABLE IF NOT EXISTS sources (
                source        TEXT PRIMARY KEY,
                file_hash     TEXT NOT NULL,
                size          INTEGER,
                modified      REAL,
                created       REAL,
                collected     REAL,
                status        TEXT DEFAULT NULL,
                FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS images (
                path          TEXT PRIMARY KEY,
                source        TEXT NOT NULL,
                name          TEXT,
                aspect_ratio  REAL,
                FOREIGN KEY(source) REFERENCES sources(source) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS meta_info (
                path   TEXT NOT NULL,
                key    TEXT NOT NULL,
                value  TEXT,
                PRIMARY KEY(path, key),
                FOREIGN KEY(path) REFERENCES images(path) ON UPDATE CASCADE ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS tags (
                file_hash  TEXT NOT NULL,
                key        TEXT NOT NULL,
                value      TEXT,
                PRIMARY KEY(file_hash, key),
                FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
            );

            -- VIEWS
            CREATE VIEW IF NOT EXISTS images_full AS
            SELECT
                i.path,
                i.source,
                i.name,
                i.aspect_ratio,
                s.file_hash,
                s.size,
                s.modified,
                s.created,
                s.collected,
                s.status
            FROM images i
            JOIN sources s ON s.source = i.source;

            CREATE VIEW IF NOT EXISTS kv_all AS
            WITH base AS (
                SELECT mi.path AS path, mi.key AS key, mi.value AS value, 'meta_info' AS src, 2 AS rank
                FROM meta_info AS mi
            UNION ALL
                -- tags は sources の file_hash 経由で images に関連付ける
                SELECT i.path AS path, t.key AS key, t.value AS value, 'tags' AS src, 0 AS rank
                FROM tags AS t
                JOIN sources AS s ON s.file_hash = t.file_hash
                JOIN images  AS i ON i.source    = s.source
            UNION ALL
                SELECT i.path AS path, '__filepath__' AS key, i.path AS value, 'virtual' AS src, 1 AS rank
                FROM images AS i
            ),
            picked AS (
                SELECT path, key, value, src, rank,
                    ROW_NUMBER() OVER (PARTITION BY path, key ORDER BY rank, src) AS rn
                FROM base
            )
            SELECT path, key, value, src
            FROM picked
            WHERE rn = 1;

            CREATE VIEW IF NOT EXISTS kv_meta AS
            SELECT
                k.path,
                vf.file_hash,
                k.key,
                k.value,
                k.src
            FROM kv_all AS k
            JOIN images_full AS vf ON vf.path = k.path;
            """
        )
        self.conn.executescript(
            """
            -- Indexes identical to original
            CREATE INDEX IF NOT EXISTS idx_sources_file_hash     ON sources(file_hash);
            CREATE INDEX IF NOT EXISTS idx_images_source         ON images(source);

            CREATE INDEX IF NOT EXISTS idx_meta_info_key_fid     ON meta_info(key, path);
            CREATE INDEX IF NOT EXISTS idx_tags_key_fid          ON tags(key, file_hash);

            CREATE INDEX IF NOT EXISTS idx_images_name_path         ON images(name, path);
            CREATE INDEX IF NOT EXISTS idx_sources_modified_source  ON sources(modified, source);
            CREATE INDEX IF NOT EXISTS idx_sources_size_source      ON sources(size, source);
            CREATE INDEX IF NOT EXISTS idx_sources_created_source   ON sources(created, source);
            CREATE INDEX IF NOT EXISTS idx_sources_collected_source ON sources(collected, source);
            """
        )
        cur.close()

    # ---- high-level DB ops used by indexer ----------------------------
    @profiler.profile
    def load_previous(self) -> dict[str, tuple[float, int]]:
        result: dict[str, tuple[float, int]] = {}
        try:
            cur = self.get_reader_cursor()
            cur.execute('SELECT source, modified, size FROM sources')
            for source, mtime, size in cur.fetchall():
                result[source] = (mtime, size)  # ここでは normalize しない
            cur.close()
        except Exception as e:
            logger.warning(f'Failed to load previous data from DB: {e}')
        return result


    @profiler.profile
    def delete_sources_by_paths(self, paths: Sequence[str]):
        if not paths:
            return
        cur = self.get_writer_cursor()
        try:
            cur.executemany('DELETE FROM sources WHERE source = ?', [(p,) for p in paths])
            self.conn.commit()
        finally:
            cur.close()

    @profiler.profile
    def upsert_batches(self,
                    source_entries,     
                    image_entries,      
                    meta_info_entries,  
                    tag_entries,        
                    ):
        with self.conn:
            cur = self.conn.cursor()

            # 1) hash_index 先行 (images/tags の file_hash をカバー)
            file_ids = set()
            for _, fid, *_ in source_entries:   # ★sources側からも回収
                if fid: file_ids.add(fid)
            for fid, *_ in tag_entries:
                if fid: file_ids.add(fid)
            if file_ids:
                cur.executemany(
                    'INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)',
                    [(fid,) for fid in file_ids],
                )
            # 2) sources を upsert
            cur.executemany(
                '''
                INSERT INTO sources (source, file_hash, size, modified, created, collected, status)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                file_hash = excluded.file_hash,
                size      = excluded.size,
                modified  = excluded.modified,
                created   = excluded.created,
                collected = excluded.collected,
                status    = excluded.status
                ''',
                source_entries,
            )

            # 3) images を upsert（時刻やサイズは保持しない）
            if image_entries:
                cur.executemany(
                    '''
                    INSERT INTO images (path, source, name, aspect_ratio)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        source       = excluded.source,
                        name         = excluded.name,
                        aspect_ratio = excluded.aspect_ratio
                    ''',
                    image_entries,
                )

            # 4) meta_info / tags
            if meta_info_entries:
                cur.executemany(
                    '''
                    INSERT INTO meta_info (path, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(path, key) DO UPDATE SET
                        value = excluded.value
                    ''',
                    meta_info_entries,
                )

            if tag_entries:
                cur.executemany(
                    '''
                    INSERT INTO tags (file_hash, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(file_hash, key) DO UPDATE SET
                        value = excluded.value
                    ''',
                    tag_entries,
                )
            cur.close()


    @profiler.profile
    def clean_unused(self):
        logger.info('CLEANING UP DATABASE')
        try:
            cur = self.get_writer_cursor()

            # 1) images にいない path の meta を掃除
            cur.execute('''
                DELETE FROM meta_info
                WHERE path NOT IN (SELECT path FROM images)
            ''')

            # 2) images に使われない file_hash の tags を掃除
            cur.execute('''
                DELETE FROM tags
                WHERE file_hash NOT IN (SELECT file_hash FROM sources);
            ''')

            # 3) images/tags から参照されない hash_index を掃除
            cur.execute('''
                DELETE FROM hash_index
                WHERE file_hash NOT IN (SELECT file_hash FROM sources)
                AND file_hash NOT IN (SELECT file_hash FROM tags);
            ''')

            self.conn.commit()

            logger.info('RUNNING VACUUM')
            cur.execute('VACUUM')
            logger.info('RUNNING ANALYZE')
            cur.execute('ANALYZE')
            self.conn.commit()
            self.try_checkpoint()
        except Exception as e:
            logger.exception('DATABASE CLEANUP FAILED: %s', e)
        else:
            logger.info('DATABASE CLEANUP END')



import concurrent.futures
import os
import queue
import threading
import time
from pathlib import Path
from typing import Sequence

from source.io.manager import ReaderClass
from ..common.funcs import IMAGE_EXTENSIONS, normalize_path
from ..common.hashes import fast_sig_hash
from ..common.profiling import logger, profiler

extensions = IMAGE_EXTENSIONS
CHUNK = 900
executor = concurrent.futures.ThreadPoolExecutor()


def path_to_meta(name):
    return name


class ImageIndexer:
    """Public API unchanged. Internally delegates all DB work to ImageDB."""

    def __init__(self, db_path):
        self.db = ImageDB(db_path)
        self.exclude_paths = set()
        self._progress_callback = None
        self._update_callback = None

    # ---- lifecycle & callbacks ----------------------------------------
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

    # ---- DB-backed helpers --------------------------------------------
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
        for i in range(0, len(to_remove), CHUNK):
            chunk = to_remove[i:i + CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        logger.info(f'[ExcludePaths] Removed {len(to_remove)} entries from DB.')
        self.emit_update()

    @profiler.profile
    def load_previous(self):
        # returns {path: (mtime, size)} with normalized keys as before
        prev = self.db.load_previous()
        return {normalize_path(k): v for k, v in prev.items()}

    # ---- scanning & diff ----------------------------------------------
    @profiler.profile
    def _detect_diff(self, current, previous):
        added_or_modified = [p for p in current if p not in previous or current[p] != previous[p]]
        removed = [p for p in previous if p not in current]
        return (added_or_modified, removed)

    def get_stat(self, stat):
        if hasattr(stat, 'st_birthtime'):
            ctime = stat.st_birthtime
        else:
            ctime = stat.st_ctime
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
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(extensions):
                            stat = entry.stat()
                            yield (normalize_path(entry.path), self.get_stat(stat))
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
            for i in range(0, len(removed), CHUNK):
                chunk = removed[i:i + CHUNK]
                self.db.delete_sources_by_paths(chunk)
                self._add_progress(len(chunk), 0)
            logger.info(f'deleted {len(removed)} files')
            self.db.try_checkpoint('PASSIVE')
            self.emit_update()

        if added_or_modified:
            self.update_meta_and_image(added_or_modified, file_info)

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
                stat_info[path] = self.get_stat(st)
            except FileNotFoundError:
                self._add_progress(1, 0)
        if not stat_info:
            logger.info('No valid files to update.')
            return
        previous = {}
        keys = list(stat_info.keys())
        cur = self.db.get_reader_cursor()
        for i in range(0, len(keys), CHUNK):
            chunk = keys[i:i + CHUNK]
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
            self.update_meta_and_image(to_update, stat_info)
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
        for i in range(0, len(normalized), CHUNK):
            chunk = normalized[i:i + CHUNK]
            self.db.delete_sources_by_paths(chunk)
            self._add_progress(len(chunk), 0)
        self.db.try_checkpoint()
        self.emit_update()
        logger.info(f'[remove_by_file_list] Removed {len(normalized)} entries from DB')

    # ---- processing & writing -----------------------------------------
    def _batch_images(self, p):
        try:
            return ReaderClass.read(p)
        except Exception:
            norm = normalize_path(p)
            return ({'source': norm, 'path': norm, 'name': Path(p).name, 'aspect': None}, {}, {}, 'fail')

    @profiler.profile
    def batch_process_images(self, batch, file_info):
        results = list(executor.map(self._batch_images, batch))

        source_entries = set()   # dedup by source
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

            # status を sources.status に残す（fail も upsert しておく）
            source_entries.add((source, file_hash, fsize, mtime, ctime, time.time(), 'fail' if status == 'fail' else 'ok'))

            if status == 'fail':
                continue

            image_entries.append((path, source, name, aspect))
            meta_info_entries.extend((path, k, v) for k, v in meta_info.items())
            tag_entries.extend((file_hash, k, v) for k, v in tags.items())

        return (list(source_entries), image_entries, meta_info_entries, tag_entries)


    @profiler.profile
    def write_batch_to_db(self, source_entries, image_entries, meta_info_entries, tag_entries):
        self.db.upsert_batches(source_entries, image_entries, meta_info_entries, tag_entries)

    @profiler.profile
    def update_meta_and_image(self, paths, file_info):
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
                    (source_entries, image_entries, meta_info_entries, tag_entries) = item
                    self.write_batch_to_db(source_entries, image_entries, meta_info_entries, tag_entries)
                except Exception as e:
                    logger.error(f'[WriterThread] Error in write_batch_to_db: {e}')
                finally:
                    write_queue.task_done()

        writer_thread = threading.Thread(target=writer_thread_func, daemon=True)
        writer_thread.start()

        acc_source_entries = []
        acc_image_entries = []
        acc_meta_info_entries = []
        acc_tag_entries = []
        acc_proc_duration = 0.0

        while i < total:
            elapsed = time.monotonic() - start_time
            target_s = min(TARGET_MAX_S, TARGET_MIN_S + elapsed / TARGET_MAX_S * (TARGET_MAX_S - TARGET_MIN_S))

            batch = paths[i:i + batch_size]
            t0 = time.monotonic()
            (source_entries, image_entries, meta_info_entries, tag_entries) = self.batch_process_images(batch, file_info)
            duration = time.monotonic() - t0

            acc_source_entries.extend(source_entries)
            acc_image_entries.extend(image_entries)
            acc_meta_info_entries.extend(meta_info_entries)
            acc_tag_entries.extend(tag_entries)
            acc_proc_duration += duration

            # 目標時間 or キュー圧でフラッシュ
            if acc_proc_duration >= target_s or write_queue.qsize() >= int(QUEUE_MAX * 0.8):
                write_queue.put((acc_source_entries, acc_image_entries, acc_meta_info_entries, acc_tag_entries))
                acc_source_entries = []
                acc_image_entries = []
                acc_meta_info_entries = []
                acc_tag_entries = []
                acc_proc_duration = 0.0

            # 自動バッチサイズ調整
            if duration > 0:
                if duration < target_s:
                    ratio = target_s / duration
                    batch_size = int(batch_size * ratio ** 0.5)
                else:
                    ratio = duration / target_s
                    batch_size = int(batch_size / ratio ** 0.5)

            if write_queue.qsize() >= int(QUEUE_MAX * 0.6):
                batch_size = max(MIN_BATCH_SIZE, int(batch_size * 0.7))

            batch_size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch_size))

            i += len(batch)
            self.db.try_checkpoint('PASSIVE')
            self.emit_update()
            self._add_progress(len(batch), 0)
            logger.info(f'[Adaptive Commit] {i}/{total} processed (batch={len(batch)}, {duration:.2f}s, target={target_s:.2f}s)')

        # 残りをフラッシュ
        if acc_source_entries or acc_image_entries or acc_meta_info_entries or acc_tag_entries:
            write_queue.put((acc_source_entries, acc_image_entries, acc_meta_info_entries, acc_tag_entries))

        write_queue.join()
        write_queue.put(None)
        writer_thread.join()
        self.db.try_checkpoint()
        self.emit_update()

    @profiler.profile
    def clean_unused(self):
        self.db.clean_unused()
        self.emit_update()

    # ---- placeholder to keep interface identical ----------------------
    def dump_json(self, out_path: str | None = 'temp_dump_json.json', mode: str = 'by_table', pretty: bool = True, chunk_size: int = 10_000):
        return None

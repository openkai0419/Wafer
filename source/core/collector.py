import os
import shutil
import sqlite3
import time

from pathlib import Path
from PySide6 import QtGui

from ..profiling import init_env
from ..common import normalize_path
from .db_manager import DBManager
from .file_scanner import FileScanner
from .batch_writer import BatchWriter
from .batch_utils import (
    process_image,
    CHUNK,
    BASE_DURATION,
    MIN_BATCH_SIZE,
    MAX_BATCH_SIZE,
    INITIAL_BATCH_SIZE,
    executor,
    extensions,
)

logger, profiler = init_env()

def connect_with_retry(path, timeout=3.0, retries=3, delay=1.0, **kwargs):
    last_exception = None
    for attempt in range(retries):
        try:
            conn = sqlite3.connect(path, timeout=timeout, **kwargs)
            return conn
        except sqlite3.OperationalError as e:
            last_exception = e
            logger.warning(f"[connect_with_retry] Attempt {attempt+1} failed: {e}")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"[connect_with_retry] Unexpected error: {e}")
            raise
    logger.error(f"[connect_with_retry] All attempts failed. Raising last exception.")
    raise last_exception


class ImageIndexer:
    def __init__(self, db_path):
        logger.info(f"image indexer init {db_path}")
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix(".bak")
        self.db = DBManager(self.db_path, connect_with_retry, self._apply_pragmas)
        self.file_scanner = FileScanner(self.is_path_excluded, extensions)
        self.batch_writer = BatchWriter(self.db)
        self.batch_writer.indexer = self
        self.exclude_paths = set()
        logger.info("image indexer init end")

    @profiler.profile
    def check_init(self):
        self._initialize_database()
        self._ensure_schema()

    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def set_update_callback(self, callback):
        self._update_callback = callback

    @profiler.profile
    def emit_update(self):
        self._update_callback()

    @profiler.profile
    def _emit_progress(self, current, total):
        self._progress_callback(current, total)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()

    @profiler.profile
    def set_exclude_paths(self, paths, run=False):
        self.exclude_paths = {normalize_path(p) for p in paths}
        logger.info(f"[ExcludePaths] {len(self.exclude_paths)} paths set.")
        if run:
            self.remove_excluded_from_db()

    @profiler.profile
    def is_path_excluded(self, path: str) -> bool:
        for ex in self.exclude_paths:
            if path == ex or path.startswith(ex + "/"):
                return True
        return False

    @profiler.profile
    def start(self):
        self.db.start()
        self.conn = self.db.conn
        self.read_conn = self.db.read_conn
        logger.info("indexer start end")

    @profiler.profile
    def exit(self):
        try:
            self.db.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except Exception as e:
            logger.info(e)
        self.db.close()

    @profiler.profile
    def _apply_pragmas(self, conn, read_only=False):
        if read_only:
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = -50000")
            conn.execute("PRAGMA mmap_size = 268435456")
        else:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA locking_mode=NORMAL")

    def get_writer_cursor(self):
        return self.conn.cursor()

    def get_reader_cursor(self):
        return self.read_conn.cursor()

    @profiler.profile
    def _initialize_database(self):
        try:
            if not self.db.integrity_check():
                raise sqlite3.DatabaseError("Integrity check failed.")
        except sqlite3.DatabaseError as e:
            logger.warning(f"[ERROR] DB corrupted: {e}")
            self.db.backup_and_recreate(self.backup_path)
        except Exception:
            raise


    @profiler.profile
    def _ensure_schema(self):
        self.db.ensure_schema()

    @profiler.profile
    def _detect_diff(self, current, previous):
        added_or_modified = [p for p in current if p not in previous or current[p] != previous[p]]
        removed = [p for p in previous if p not in current]
        return added_or_modified, removed

    @profiler.profile
    def scan_directory_fast(self, root_path):
        scanner = self.file_scanner
        for item in scanner.scan(root_path):
            yield item

    @profiler.profile
    def load_previous(self):
        try:
            cur = self.get_reader_cursor()
            return self.file_scanner.load_previous(cur)
        except Exception as e:
            logger.warning(f"Failed to load previous data from DB: {e}")
            return {}

    @profiler.profile
    def remove_excluded_from_db(self):
        if not self.exclude_paths:
            return
        logger.info("[ExcludePaths] Removing existing entries under exclude paths...")

        # 全ての登録済み path を取得
        cur = self.get_reader_cursor()
        cur.execute("SELECT path FROM images")
        all_paths = [normalize_path(row[0]) for row in cur.fetchall()]
        cur.close()

        # 除外対象にマッチするものをフィルタ
        to_remove = [p for p in all_paths if self.is_path_excluded(p)]
        if not to_remove:
            logger.info("[ExcludePaths] No matching entries to remove.")
            return
        
        self._emit_progress(0, len(to_remove))

        cur = self.get_writer_cursor()
        for i in range(0, len(to_remove), CHUNK):
            chunk = to_remove[i:i+CHUNK]
            cur.executemany("DELETE FROM images WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta_info WHERE path = ?", [(p,) for p in chunk])
            self._emit_progress(len(chunk), 0)
        self.conn.commit()
        cur.close()

        logger.info(f"[ExcludePaths] Removed {len(to_remove)} entries from DB.")
        self.emit_update()

    @profiler.profile
    def update_index(self, root_paths):
        if isinstance(root_paths, str):
            root_paths = [root_paths]

        logger.info("UPDATE_INDEX")
        current = {}
        for path in root_paths:
            for norm_p, info in self.scan_directory_fast(path):
                current[norm_p] = info

        previous = {}
        cur = self.get_reader_cursor()
        cur.execute("SELECT path, mtime, size FROM images")
        while True:
            rows = cur.fetchmany(10000)
            if not rows:
                break
            for path, mtime, size in rows:
                previous[normalize_path(path)] = (mtime, size)

        added_or_modified, removed = self._detect_diff(current, previous)
        self._emit_progress(0, len(added_or_modified))
        self._emit_progress(0, len(removed))

        logger.info("added/modified: {}, removed: {}".format(len(added_or_modified), len(removed)))

        cur = self.get_writer_cursor()

        if removed:
            for i in range(0, len(removed), CHUNK):
                logger.debug(i)
                chunk = removed[i:i+CHUNK]
                cur.executemany("DELETE FROM images WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta_info WHERE path = ?", [(str(p),) for p in chunk])
                self._emit_progress(len(chunk), 0)
            logger.info(f"deleted {len(removed)} files")
            self.conn.commit()
            self.emit_update()

        if added_or_modified:
            self.batch_writer.update_meta_and_image(added_or_modified, current)
    
        cur.close()


    @profiler.profile
    def update_by_file_list(self, file_paths):
        total_paths = len(file_paths)

        file_paths = [p for p in file_paths if os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]
        normalized = [p for p in normalized if not self.is_path_excluded(p)]

        self._emit_progress(total_paths - len(normalized), 0)

        stat_info = {}
        for path in normalized:
            try:
                st = os.stat(path)
                stat_info[path] = (st.st_mtime, st.st_size)
            except FileNotFoundError:
                self._emit_progress(1, 0)

        if not stat_info:
            logger.info("No valid files to update.")
            return

        previous = {}
        keys = list(stat_info.keys())

        for i in range(0, len(keys), CHUNK):
            chunk = keys[i:i+CHUNK]
            cur = self.get_reader_cursor()
            cur.execute(
                f"SELECT path, mtime, size FROM images WHERE path IN ({','.join(['?'] * len(chunk))})",
                chunk
            )
            previous.update({normalize_path(row[0]): (row[1], row[2]) for row in cur.fetchall()})

        to_update = [p for p in stat_info if p not in previous or stat_info[p] != previous[p]]
        skip_count = len(stat_info) - len(to_update)
        if skip_count:
            self._emit_progress(skip_count, 0)

        if to_update:
            self.batch_writer.update_meta_and_image(to_update, stat_info)
            self.conn.commit()
            self.emit_update()
        else:
            logger.info("[update_by_file_list] No updates needed.")

    @profiler.profile
    def remove_by_file_list(self, file_paths):
        total_paths = len(file_paths)
        file_paths = [p for p in file_paths if not os.path.exists(p)]
        normalized = [normalize_path(p) for p in file_paths]

        self._emit_progress(total_paths - len(normalized), 0)

        if not normalized:
            return

        cur = self.get_writer_cursor()
        for i in range(0, len(normalized), CHUNK):
            chunk = normalized[i:i+CHUNK]
            cur.executemany("DELETE FROM images WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta_info WHERE path = ?", [(p,) for p in chunk])
            self._emit_progress(len(chunk), 0)

        self.conn.commit()
        self.emit_update()
        logger.info(f"[remove_by_file_list] Removed {len(normalized)} entries from DB")


    @profiler.profile
    def clean_unused(self):
        logger.info("CLEANUNG UP DATABASE")
        cur = self.get_writer_cursor()

        cur.execute("""
            SELECT DISTINCT m.key
            FROM meta_info m
            LEFT JOIN images i ON m.path = i.path
            WHERE i.path IS NULL
        """)
        unused_keys = [row[0] for row in cur.fetchall()]

        if unused_keys:
            logger.info(f"Cleaning up {len(unused_keys)} unused keys: {unused_keys}")

        cur.execute("""
            DELETE FROM meta_info
            WHERE path NOT IN (SELECT path FROM images)
        """)
        self.conn.commit()
        cur = self.get_writer_cursor()
        cur.execute("VACUUM")
        logger.info("DATABASE CLEANUP END")



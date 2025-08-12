import os
import shutil
import sqlite3
import time
import queue
import threading
import concurrent.futures

from pathlib import Path
from PIL import Image
from PySide6 import QtGui

from ..common.profiling import logger, profiler
from ..common.funcs import normalize_path, IMAGE_EXTENSIONS
from .db_utils import connect_with_retry

extensions = IMAGE_EXTENSIONS
CHUNK = 900

# reusable ThreadPoolExecutor
executor = concurrent.futures.ThreadPoolExecutor()

def get_file_ctime(path):
    try:
        stat = os.stat(path)
        if hasattr(stat, 'st_birthtime'):  # macOS
            return stat.st_birthtime
        else:  # on Unix/Linux st_ctime represents change time
            return stat.st_ctime
    except Exception as e:
        logger.warning(f"Failed to get ctime for {path}: {e}")
        return None

def read_info(path):
    try:
        with Image.open(path) as img:
            return dict(img.info)
    except Exception as e:
        logger.warning(f"Failed to read image info for {path}: {e}")
    return {}

def process_image(p, file_info):
    try:
        name = os.path.basename(p)
        mtime, fsize = file_info.get(p, (None, None))
        ctime = get_file_ctime(p)
        collected_at = time.time()
        with Image.open(p) as img:
            width, height = img.size
            exif = img.getexif()
            orientation = exif.get(274, 1) if exif else 1
            if orientation in (5, 6, 7, 8):
                width, height = height, width
            aspect = (width / height) if height else 1.0
            info = dict(img.info)
        meta_info = [(str(p), str(k), str(v)) for k, v in info.items()]
        meta_info.append((str(p), "__filepath__", str(p)))
        return (p, name, aspect, mtime, fsize, ctime, collected_at, meta_info, None)
    except Exception as e:
        logger.warning(f"Failed to process {p}: {e}")
        mtime, fsize = file_info.get(p, (None, None))
        name = os.path.basename(p)
        return (p, name, None, mtime, fsize, None, time.time(), [], 'fail')

class ImageIndexer:
    def __init__(self, db_path):
        logger.info(f"image indexer init {db_path}")
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix(".bak")
        self.conn = None
        self.read_conn = None
        self.exclude_paths = set()
        logger.info("image indexer init end")

    @profiler.profile
    def check_init(self):
        self._initialize_database()
        self._ensure_schema()

    def set_progress_callback(self, callback):
        self._progress_callback = callback
        logger.debug("Progress callback set: %s", callback)

    def set_update_callback(self, callback):
        self._update_callback = callback

    @profiler.profile
    def emit_update(self):
        self._update_callback()

    @profiler.profile
    def _emit_progress(self, current, total):
        if hasattr(self, "_progress_callback") and self._progress_callback:
            self._progress_callback(current, total)
        else:
            logger.warning("Progress callback is not set")

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
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=False)
        self._apply_pragmas(self.conn)

        self.read_conn = connect_with_retry(
            f"file:{self.db_path}?mode=ro&immutable=1", timeout=1.0, uri=True
        )
        self._apply_pragmas(self.read_conn, read_only=True)
        logger.info("indexer start end")

    def try_checkpoint(self):
        try:
            self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.conn.commit()
        except Exception as e:
            logger.warning(e)

    @profiler.profile
    def exit(self):
        self.try_checkpoint()
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

    @profiler.profile
    def _apply_pragmas(self, conn, read_only=False):
        if read_only:
            conn.execute("PRAGMA temp_store = MEMORY")
            conn.execute("PRAGMA cache_size = -10000")
            conn.execute("PRAGMA mmap_size = 134217728")
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
            if not self._integrity_check():
                raise sqlite3.DatabaseError("Integrity check failed.")
        except sqlite3.DatabaseError as e:
            logger.warning(f"[ERROR] DB corrupted: {e}")
            self._backup_and_recreate()
        except:
            raise

    @profiler.profile
    def _integrity_check(self) -> bool:
        try:
            logger.info("quick check start")
            result = self.conn.execute("PRAGMA quick_check").fetchone()
            logger.info("quick check end")
            return result[0] == "ok"
        except Exception as e:
            logger.warning(f"[WARN] integrity_check failed: {e}")
            return False

    @profiler.profile
    def _backup_and_recreate(self):
        if self.conn:
            self.conn.close()
        if self.db_path.exists():
            shutil.copy(self.db_path, self.backup_path)
            os.remove(self.db_path)
            logger.warning(f"[INFO] Corrupted DB backed up to: {self.backup_path}")
        self.conn = sqlite3.connect(self.db_path)
        self._apply_pragmas(self.conn)
        logger.warning(f"[INFO] New DB created at: {self.db_path}")

    @profiler.profile
    def _ensure_schema(self):
        cur = self.get_writer_cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS images (
                path TEXT PRIMARY KEY,
                mtime REAL,
                size INTEGER,
                status TEXT DEFAULT NULL
            )
        """)
        cur.execute("PRAGMA table_info(images)")
        columns = [row[1] for row in cur.fetchall()]
        if "status" not in columns:
            cur.execute("ALTER TABLE images ADD COLUMN status TEXT DEFAULT NULL")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta (
                path TEXT PRIMARY KEY,
                name TEXT,
                aspect_ratio REAL,
                mtime REAL,
                size INTEGER,
                created REAL,
                collected_at REAL,
                FOREIGN KEY(path) REFERENCES images(path) ON DELETE CASCADE
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS meta_info (
                path TEXT,
                key TEXT,
                value TEXT,
                PRIMARY KEY(path, key),
                FOREIGN KEY(path) REFERENCES images(path) ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_path ON meta_info(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_key ON meta_info(key)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_value ON meta_info(value)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_path_key ON meta_info(path, key)")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_path ON images(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_size ON images(size)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_mtime ON images(mtime)")
        
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_path ON meta(path)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_name ON meta(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_aspect_ratio ON meta(aspect_ratio)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_mtime ON meta(mtime)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_size ON meta(size)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_created ON meta(created)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_collected ON meta(collected_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_path_aspect ON meta(path, aspect_ratio)")
        cur.close()
        logger.info("ensureschema end")

    @profiler.profile
    def _detect_diff(self, current, previous):
        added_or_modified = [p for p in current if p not in previous or current[p] != previous[p]]
        removed = [p for p in previous if p not in current]
        return added_or_modified, removed

    @profiler.profile
    def scan_directory_fast(self, root_path):
        stack = [str(root_path)]
        while stack:
            current = stack.pop()
            self._emit_progress(0, 1)
            full_path = normalize_path(current)

            if self.is_path_excluded(full_path):
                logger.debug(f"[Excluded] Skipping file: {full_path}")
                self._emit_progress(1, 0)
                continue
            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(extensions):
                            stat = entry.stat()
                            yield normalize_path(entry.path), (stat.st_mtime, stat.st_size)
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                self._emit_progress(1, 0)
            except Exception:
                self._emit_progress(1, 0)
                continue

    @profiler.profile
    def load_previous(self):
        result = {}
        try:
            cur = self.get_reader_cursor()
            cur.execute("SELECT path, mtime, size FROM images")
            while True:
                rows = cur.fetchmany(10000)
                if not rows:
                    break
                result.update({normalize_path(path): (mtime, size) for path, mtime, size in rows})
        except Exception as e:
            logger.warning(f"Failed to load previous data from DB: {e}")
        return result

    @profiler.profile
    def remove_excluded_from_db(self):
        if not self.exclude_paths:
            return
        logger.info("[ExcludePaths] Removing existing entries under exclude paths...")

        # get all registered paths
        cur = self.get_reader_cursor()
        cur.execute("SELECT path FROM images")
        all_paths = [normalize_path(row[0]) for row in cur.fetchall()]
        cur.close()

        # filter entries under excluded paths
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
            self._emit_progress(0, 1)
            for norm_p, info in self.scan_directory_fast(path):
                current[norm_p] = info
            self._emit_progress(1, 0)
            

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
            self.update_meta_and_image(added_or_modified, current)
    
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
            self.update_meta_and_image(to_update, stat_info)
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
    def batch_process_images(self, batch, file_info):
        results = list(executor.map(lambda p: process_image(p, file_info), batch))

        image_entries = []
        meta_entries = []
        meta_info_entries = []
        failed_entries = []

        for p, name, aspect, mtime, fsize, ctime, collected_at, meta_info, status in results:
            if status == 'fail':
                failed_entries.append((str(p), mtime, fsize))
                continue
            image_entries.append((str(p), mtime, fsize))
            meta_entries.append((str(p), name, aspect, mtime, fsize, ctime, collected_at))
            meta_info_entries.extend(meta_info)

        return image_entries, meta_entries, meta_info_entries, failed_entries

    @profiler.profile
    def write_batch_to_db(self, image_entries, meta_entries, meta_info_entries, failed_entries):
        with self.conn:
            cur = self.conn.cursor()
            if failed_entries:
                cur.executemany("""
                    INSERT INTO images (path, mtime, size, status)
                    VALUES (?, ?, ?, 'fail')
                    ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'fail'
                """, failed_entries)

            if image_entries:
                cur.executemany("""
                    INSERT INTO images (path, mtime, size, status)
                    VALUES (?, ?, ?, 'ok')
                    ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'ok'
                """, image_entries)

            if meta_entries:
                cur.executemany("""
                    INSERT INTO meta (path, name, aspect_ratio, mtime, size, created, collected_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(path) DO UPDATE SET 
                        name = excluded.name,
                        aspect_ratio = excluded.aspect_ratio,
                        mtime = excluded.mtime,
                        size = excluded.size,
                        created = excluded.created,
                        collected_at = excluded.collected_at
                """, meta_entries)

            if meta_info_entries:
                cur.executemany("""
                    INSERT INTO meta_info (path, key, value)
                    VALUES (?, ?, ?)
                    ON CONFLICT(path, key) DO UPDATE SET value = excluded.value
                """, meta_info_entries)
            cur.close()

    @profiler.profile
    def update_meta_and_image(self, paths, file_info):
        total = len(paths)
        MIN_BATCH_SIZE = 100
        MAX_BATCH_SIZE = 50000
        batch_size = MIN_BATCH_SIZE
        TARGET_MIN_S = 3.0
        TARGET_MAX_S = 300.0
        QUEUE_MAX = 8
        i = 0

        start_time = time.monotonic()
        target_s = TARGET_MIN_S

        write_queue = queue.Queue(maxsize=QUEUE_MAX)

        def writer_thread_func():
            while True:
                item = write_queue.get()
                if item is None:
                    break
                try:
                    image_entries, meta_entries, meta_info_entries, failed_entries = item
                    self.write_batch_to_db(image_entries, meta_entries, meta_info_entries, failed_entries)
                except Exception as e:
                    logger.error(f"[WriterThread] Error in write_batch_to_db: {e}")
                finally:
                    write_queue.task_done()

        writer_thread = threading.Thread(target=writer_thread_func, daemon=True)
        writer_thread.start()

        acc_image_entries = []
        acc_meta_entries = []
        acc_meta_info_entries = []
        acc_failed_entries = []
        acc_proc_duration = 0.0

        while i < total:
            elapsed = time.monotonic() - start_time
            ramp_target = TARGET_MIN_S + (elapsed / TARGET_MAX_S) * (TARGET_MAX_S - TARGET_MIN_S)
            target_s = min(TARGET_MAX_S, ramp_target)

            batch = paths[i:i + batch_size]

            t0 = time.monotonic()
            image_entries, meta_entries, meta_info_entries, failed_entries = self.batch_process_images(batch, file_info)
            duration = time.monotonic() - t0

            acc_image_entries.extend(image_entries)
            acc_meta_entries.extend(meta_entries)
            acc_meta_info_entries.extend(meta_info_entries)
            acc_failed_entries.extend(failed_entries)
            acc_proc_duration += duration

            if acc_proc_duration >= target_s or write_queue.qsize() >= int(QUEUE_MAX * 0.8):
                write_queue.put((acc_image_entries, acc_meta_entries, acc_meta_info_entries, acc_failed_entries))
                acc_image_entries = []
                acc_meta_entries = []
                acc_meta_info_entries = []
                acc_failed_entries = []
                acc_proc_duration = 0.0

            if duration > 0:
                if duration < target_s:
                    ratio = target_s / duration
                    batch_size = int(batch_size * (ratio ** 0.5))
                else:
                    ratio = duration / target_s
                    batch_size = int(batch_size / (ratio ** 0.5))

            if write_queue.qsize() >= int(QUEUE_MAX * 0.6):
                batch_size = max(MIN_BATCH_SIZE, int(batch_size * 0.7))

            batch_size = max(MIN_BATCH_SIZE, min(MAX_BATCH_SIZE, batch_size))

            i += len(batch)
            self._emit_progress(len(batch), 0)
            self.emit_update()
            self.try_checkpoint()
            logger.info(f"[Adaptive Commit] {i}/{total} processed (batch={len(batch)}, {duration:.2f}s, target={target_s:.2f}s)")

        if acc_image_entries or acc_meta_entries or acc_meta_info_entries or acc_failed_entries:
            write_queue.put((acc_image_entries, acc_meta_entries, acc_meta_info_entries, acc_failed_entries))

        write_queue.join()
        write_queue.put(None)
        writer_thread.join()
        self.try_checkpoint()


    @profiler.profile
    def clean_unused(self):
        logger.info("CLEANING UP DATABASE")
        try:
            cur = self.get_writer_cursor()
            cur.execute("""
                DELETE FROM meta_info
                WHERE path NOT IN (SELECT path FROM images)
            """)
            self.conn.commit()

            logger.info("RUNNING VACUUM")
            cur.execute("VACUUM")

            logger.info("RUNNING ANALYZE")
            cur.execute("ANALYZE")
            self.conn.commit()

        except Exception as e:
            logger.exception("DATABASE CLEANUP FAILED: %s", e)
        else:
            logger.info("DATABASE CLEANUP END")



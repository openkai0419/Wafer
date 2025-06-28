import os
import shutil
import sqlite3
import time
from pathlib import Path
from PIL import Image
import concurrent.futures
from PySide6 import QtGui

from ..profiling import init_env
from ..common import normalize_path
logger, profiler = init_env()

extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
CHUNK = 900
COMMIT_INTERVAL = 4.0
RECOMMENDED_BATCH_SIZE = 50

# 再利用可能なThreadPoolExecutor
executor = concurrent.futures.ThreadPoolExecutor()


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

def read_info(path):
    try:
        with Image.open(path) as img:
            return dict(img.info)
    except Exception as e:
        logger.warning(f"Failed to read image info for {path}: {e}")
    return {}

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

    def set_update_callback(self, callback):
        self._update_callback = callback

    @profiler.profile
    def emit_update(self):
        self._update_callback()

    @profiler.profile
    def _emit_progress(self, current, total):
        self._progress_callback(current, total)

    def __enter__(self):
        logger.info("image indexer enter")
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()

    @profiler.profile
    def set_exclude_paths(self, paths):
        self.exclude_paths = {normalize_path(p) for p in paths}
        logger.info(f"[ExcludePaths] {len(self.exclude_paths)} paths set.")
        self._remove_excluded_from_db()

    @profiler.profile
    def is_path_excluded(self, path: str) -> bool:
        for ex in self.exclude_paths:
            if path == ex or path.startswith(ex + "/"):
                return True
        return False

    @profiler.profile
    def _remove_excluded_from_db(self):
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
    def start(self):
        logger.info("self.conn getting")
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=True)
        self._apply_pragmas(self.conn)

        logger.info("self.read_conn getting")
        self.read_conn = connect_with_retry(
            f"file:{self.db_path}?mode=ro&immutable=1", timeout=1.0, uri=True
        )
        self._apply_pragmas(self.read_conn, read_only=True)
        logger.info("start end")

    @profiler.profile
    def exit(self):
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

    @profiler.profile
    def _apply_pragmas(self, conn, read_only=False):
        logger.info("apply_pragmas")
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
            logger.info("quick_check")
            result = self.conn.execute("PRAGMA quick_check").fetchone()
            logger.info("quick_check_end")
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
                aspect_ratio REAL,
                mtime REAL,
                size INTEGER,
                created REAL,
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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_aspect_ratio ON meta(aspect_ratio)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_mtime ON meta(mtime)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_size ON meta(size)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_created ON meta(created)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_meta_path_aspect ON meta(path, aspect_ratio)")
        cur.close()

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

            full_path = normalize_path(current)
            if self.is_path_excluded(full_path):
                logger.debug(f"[Excluded] Skipping file: {full_path}")
                continue

            try:
                with os.scandir(current) as it:
                    for entry in it:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(extensions):
                            stat = entry.stat()
                            yield normalize_path(entry.path), (stat.st_mtime, stat.st_size)
                        elif entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
            except Exception:
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
                logger.info(i)
                chunk = removed[i:i+CHUNK]
                cur.executemany("DELETE FROM images WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta_info WHERE path = ?", [(str(p),) for p in chunk])
                self._emit_progress(len(chunk), 0)
            logger.info(f"deleted {len(removed)} files")
            self.conn.commit()
            self.emit_update()

        if added_or_modified:
            logger.info("added_or_modified")
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
    def update_meta_and_image(self, paths, file_info):
        total = len(paths)
        updated_count = 0
        update_emit_interval = COMMIT_INTERVAL  # emit_update() 呼び出し間隔（秒）
        emit_last_time = time.monotonic()

        def process_image(p):
            try:
                reader = QtGui.QImageReader(p)
                reader.setAutoTransform(True)
                size = reader.size()
                aspect = size.width() / size.height() if size.isValid() and size.height() > 0 else 1.0
                mtime, fsize = file_info[p] if p in file_info else (None, None)
                info = read_info(p)
                meta_info = [(str(p), str(k), str(v)) for k, v in info.items()]
                meta_info.append((str(p), "__filepath__", str(p)))
                return (p, aspect, mtime, fsize, meta_info, None)
            except Exception as e:
                logger.warning(f"Failed to process {p}: {e}")
                return (p, None, file_info.get(p, (None, None))[0], file_info.get(p, (None, None))[1], [], 'fail')

        for i in range(0, total, RECOMMENDED_BATCH_SIZE):
            batch = paths[i:i+RECOMMENDED_BATCH_SIZE]
            results = list(executor.map(process_image, batch))

            meta_entries = []
            image_entries = []
            meta_info_entries = []

            for p, aspect, mtime, fsize, meta_info, status in results:
                if status == 'fail':
                    with self.conn:
                        cur = self.conn.cursor()
                        cur.execute("""
                            INSERT INTO images (path, mtime, size, status)
                            VALUES (?, ?, ?, 'fail')
                            ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'fail'
                        """, (str(p), mtime, fsize))
                        cur.close()
                    continue
                meta_entries.append((str(p), aspect, mtime, fsize, mtime))
                image_entries.append((str(p), mtime, fsize))
                meta_info_entries.extend(meta_info)

            try:
                with self.conn:
                    cur = self.conn.cursor()
                    if image_entries:
                        cur.executemany("""
                            INSERT INTO images (path, mtime, size, status)
                            VALUES (?, ?, ?, 'ok')
                            ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'ok'
                        """, image_entries)
                    if meta_entries:
                        cur.executemany("""
                            INSERT INTO meta (path, aspect_ratio, mtime, size, created)
                            VALUES (?, ?, ?, ?, ?)
                            ON CONFLICT(path) DO UPDATE SET aspect_ratio = excluded.aspect_ratio, mtime = excluded.mtime, size = excluded.size, created = excluded.created
                        """, meta_entries)
                    if meta_info_entries:
                        cur.executemany("""
                            INSERT INTO meta_info (path, key, value)
                            VALUES (?, ?, ?)
                            ON CONFLICT(path, key) DO UPDATE SET value = excluded.value
                        """, meta_info_entries)
                    cur.close()
            except Exception as e:
                logger.error(f"Transaction failed at batch {i+len(batch)}/{total}: {e}")

            updated_count += len(batch)
            now = time.monotonic()
            if (now - emit_last_time) > update_emit_interval:
                self._emit_progress(updated_count, 0)
                self.emit_update()
                logger.info(f"[Time Commit] Committed after {i+len(batch)} / {total} items")
                emit_last_time = now
                updated_count = 0

        # 最後に一度だけ通知
        if updated_count > 0:
            self._emit_progress(updated_count, 0)
            self.emit_update()
            logger.info(f"[Final Commit] update_meta_and_image completed {total} items")

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



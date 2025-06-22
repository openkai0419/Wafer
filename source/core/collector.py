import os
import shutil
import sqlite3
import threading
from pathlib import Path
from PIL import Image
import concurrent.futures
from PySide6 import QtGui

from ..profiling import init_env
from ..common import normalize_path
logger, profiler = init_env()

extensions = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp")
CHUNK = 900

def read_info(path):
    try:
        with Image.open(path) as img:
            return dict(img.info)
    except Exception as e:
        logger.warning(f"Failed to read image info for {path}: {e}")
    return {}

class ImageIndexer:
    def __init__(self, db_path, zmqpublisher=None):
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix(".bak")
        self.conn = None
        self.read_conn = None
        self.start()
        self._initialize_database()
        self._ensure_schema()

    
    def set_progress_callback(self, callback):
        self._progress_callback = callback

    def set_update_callback(self, callback):
        self._update_callback = callback

    def _emit_progress(self, current, total, send_total=True):
        last_c = getattr(self, '_last_progress_current', 0)
        last_t = getattr(self, '_last_progress_total', 0)

        diff_c = current - last_c
        diff_t = total - last_t if send_total else 0

        if (diff_c or diff_t) and hasattr(self, '_progress_callback') and callable(self._progress_callback):
            try:
                self._progress_callback(diff_c, diff_t)
            except Exception as e:
                logger.warning(f"Progress callback failed: {e}")

        if diff_c > 0 and hasattr(self, '_update_callback') and callable(self._update_callback):
            try:
                self._update_callback()
            except Exception as e:
                logger.warning(f"notify callback failed: {e}")

        if current == total:
            self._last_progress_current = 0
            self._last_progress_total = 0
        else:
            self._last_progress_current = current
            self._last_progress_total = total

    def _emit_progress_inc(self, current_inc=0, total_inc=0):
        current = getattr(self, '_last_progress_current', 0) + current_inc
        total = getattr(self, '_last_progress_total', 0) + total_inc
        self._emit_progress(current, total, send_total=bool(total_inc))

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.exit()
    
    def start(self):
        self.conn = sqlite3.connect(self.db_path, timeout=10.0, check_same_thread=False)
        self._apply_pragmas(self.conn)

        self.read_conn = sqlite3.connect(f"file:{self.db_path}?mode=ro&immutable=1", uri=True)
        self._apply_pragmas(self.read_conn, read_only=True)

    def exit(self):
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

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

    def _initialize_database(self):
        try:
            if not self._integrity_check():
                raise sqlite3.DatabaseError("Integrity check failed.")
        except sqlite3.DatabaseError as e:
            logger.warning(f"[ERROR] DB corrupted: {e}")
            self._backup_and_recreate()

    def _integrity_check(self) -> bool:
        try:
            result = self.conn.execute("PRAGMA integrity_check").fetchone()
            return result[0] == "ok"
        except Exception as e:
            logger.warning(f"[WARN] integrity_check failed: {e}")
            return False

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
        cur.execute("CREATE INDEX IF NOT EXISTS idx_images_path ON images(path)")
        cur.close()

    @profiler.profile
    def scan_directory_fast(self, root_path):
        stack = [str(root_path)]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as it:
                    entries = list(it)
                    for entry in entries:
                        if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(extensions):
                            stat = entry.stat()
                            yield normalize_path(entry.path), (stat.st_mtime, stat.st_size)
                    stack.extend(
                        entry.path for entry in entries if entry.is_dir(follow_symlinks=False)
                    )
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

        added_or_modified = [p for p in current if p not in previous or current[p] != previous[p]]
        removed = [p for p in previous if p not in current]

        logger.info("added/modified: {}, removed: {}".format(len(added_or_modified), len(removed)))

        cur = self.get_writer_cursor()

        if added_or_modified:
            self.update_meta_and_image(added_or_modified, current, send_total=True)

        if removed:
            self._emit_progress_inc(0, len(removed))
            for i in range(0, len(removed), CHUNK):
                chunk = removed[i:i+CHUNK]
                cur.executemany("DELETE FROM images WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta WHERE path = ?", [(str(p),) for p in chunk])
                cur.executemany("DELETE FROM meta_info WHERE path = ?", [(str(p),) for p in chunk])
                self._emit_progress_inc(len(chunk), 0)
            logger.info(f"deleted {len(removed)} files")

        self.conn.commit()
        cur.close()


    @profiler.profile
    def update_by_file_list(self, file_paths):
        total_paths = len(file_paths)
        completed = 0

        exists = [p for p in file_paths if os.path.exists(p)]
        removed = total_paths - len(exists)
        if removed:
            completed += removed
            self._emit_progress_inc(removed, 0)

        normalized = []
        seen = set()
        for p in exists:
            np = normalize_path(p)
            if np not in seen:
                seen.add(np)
                normalized.append(np)
            else:
                completed += 1
                self._emit_progress_inc(1, 0)

        stat_info = {}
        for path in normalized:
            try:
                st = os.stat(path)
                stat_info[path] = (st.st_mtime, st.st_size)
            except FileNotFoundError:
                completed += 1
                self._emit_progress_inc(1, 0)

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
            completed += skip_count
            self._emit_progress_inc(skip_count, 0)

        if to_update:
            self.update_meta_and_image(to_update, stat_info, send_total=False)
            self.conn.commit()
        else:
            logger.info("[update_by_file_list] No updates needed.")

    @profiler.profile
    def remove_by_file_list(self, file_paths):
        total_paths = len(file_paths)
        completed = 0

        missing = [p for p in file_paths if not os.path.exists(p)]
        removed = len(missing)
        if removed:
            completed += removed
            self._emit_progress_inc(removed, 0)

        normalized = []
        seen = set()
        for p in missing:
            np = normalize_path(p)
            if np not in seen:
                seen.add(np)
                normalized.append(np)
            else:
                completed += 1
                self._emit_progress_inc(1, 0)

        if not normalized:
            return

        cur = self.get_writer_cursor()
        for i in range(0, len(normalized), CHUNK):
            chunk = normalized[i:i+CHUNK]
            cur.executemany("DELETE FROM images WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta WHERE path = ?", [(p,) for p in chunk])
            cur.executemany("DELETE FROM meta_info WHERE path = ?", [(p,) for p in chunk])
            self._emit_progress_inc(len(chunk), 0)

        self.conn.commit()
        logger.info(f"[remove_by_file_list] Removed {len(normalized)} entries from DB")

    @profiler.profile
    def update_meta_and_image(self, paths, file_info, send_total=True):
        cur = self.get_writer_cursor()
        total = len(paths)

        if total > 50000:
            batch_size = 1000
        elif total < 1000:
            batch_size = 100
        else:
            batch_size = 500

        def process_image(p):
            try:
                reader = QtGui.QImageReader(p)
                reader.setAutoTransform(True)
                size = reader.size()
                aspect = size.width() / size.height() if size.isValid() and size.height() > 0 else 1.0
                mtime, fsize = file_info[p] if file_info and p in file_info else (None, None)
                info = read_info(p)
                meta_info = [(str(p), str(k), str(v)) for k, v in info.items()]
                meta_info.append((str(p), "__filepath__", str(p)))
                meta_info.append((str(p), "__filename__", str(os.path.basename(p))))
                return (p, aspect, mtime, fsize, meta_info, None)
            except Exception as e:
                logger.warning(f"Failed to process {p}: {e}")
                return (p, None, file_info.get(p, (None, None))[0], file_info.get(p, (None, None))[1], [], 'fail')

        if send_total:
            self._emit_progress_inc(0, total)
        for i in range(0, total, batch_size):
            batch = paths[i:i+batch_size]
            meta_entries = []
            image_entries = []
            meta_info_entries = []

            with concurrent.futures.ThreadPoolExecutor() as executor:
                results = list(executor.map(process_image, batch))

            for p, aspect, mtime, fsize, meta_info, status in results:
                if status == 'fail':
                    cur.execute("""
                        INSERT INTO images (path, mtime, size, status)
                        VALUES (?, ?, ?, 'fail')
                        ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'fail'
                    """, (str(p), mtime, fsize))
                    continue
                meta_entries.append((str(p), aspect, mtime))
                image_entries.append((str(p), mtime, fsize))
                meta_info_entries.extend(meta_info)

            try:
                cur.execute("BEGIN TRANSACTION")
                if image_entries:
                    cur.executemany("""
                        INSERT INTO images (path, mtime, size, status)
                        VALUES (?, ?, ?, 'ok')
                        ON CONFLICT(path) DO UPDATE SET mtime = excluded.mtime, size = excluded.size, status = 'ok'
                    """, image_entries)
                if meta_entries:
                    cur.executemany("""
                        INSERT INTO meta (path, aspect_ratio, created)
                        VALUES (?, ?, ?)
                        ON CONFLICT(path) DO UPDATE SET aspect_ratio = excluded.aspect_ratio, created = excluded.created
                    """, meta_entries)
                if meta_info_entries:
                    cur.executemany("""
                        INSERT INTO meta_info (path, key, value)
                        VALUES (?, ?, ?)
                        ON CONFLICT(path, key) DO UPDATE SET value = excluded.value
                    """, meta_info_entries)
                cur.execute("COMMIT")
            except Exception as e:
                logger.error(f"Transaction failed at batch {i+batch_size}/{total}: {e}")
                cur.execute("ROLLBACK")

            logger.info(f"[Batch] Meta+Images Updated {len(meta_entries)} entries ({i+batch_size}/{total})")
            self._emit_progress_inc(len(batch), 0)

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



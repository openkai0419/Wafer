from __future__ import annotations
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from collections.abc import Sequence

from .db_utils import apply_read_pragmas, apply_write_pragmas, connect_with_retry
from ...utils.profiling import profiler
from ...utils.logs import AppLogger

_TABLES = (
    ("hash_index", (), "CREATE TABLE IF NOT EXISTS hash_index (file_hash TEXT PRIMARY KEY)"),
    (
        "sources",
        ("hash_index",),
        """CREATE TABLE IF NOT EXISTS sources (
        source TEXT PRIMARY KEY,
        file_hash TEXT NOT NULL,
        size INTEGER,
        modified REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )""",
    ),
    (
        "files",
        ("sources",),
        """CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    ),
    (
        "meta_info",
        ("files",),
        """CREATE TABLE IF NOT EXISTS meta_info (
        path TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    ),
    (
        "tags",
        ("hash_index",),
        """CREATE TABLE IF NOT EXISTS tags (
        file_hash TEXT NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    ),
    (
        "collection_status",
        ("sources",),
        """CREATE TABLE IF NOT EXISTS collection_status (
        source TEXT NOT NULL,
        collector TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        collected_at REAL,
        PRIMARY KEY(source, collector),
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    ),
)

_VIEWS = (
    (
        "files_full",
        """CREATE VIEW files_full AS
        SELECT i.path, i.source, i.aspect_ratio,
               s.file_hash, s.size, s.modified
        FROM files i JOIN sources s ON s.source = i.source""",
    ),
)

_INDEXES_SQL = """
    CREATE INDEX IF NOT EXISTS idx_sources_file_hash ON sources(file_hash);
    CREATE INDEX IF NOT EXISTS idx_files_source ON files(source);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_fid ON meta_info(key, path);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_value ON meta_info(key, value);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_num ON meta_info(key, value_num);
    CREATE INDEX IF NOT EXISTS idx_tags_key_fid ON tags(key, file_hash);
    CREATE INDEX IF NOT EXISTS idx_tags_key_value ON tags(key, value);
    CREATE INDEX IF NOT EXISTS idx_tags_key_num ON tags(key, value_num);
    CREATE INDEX IF NOT EXISTS idx_sources_modified_source ON sources(modified, source);
    CREATE INDEX IF NOT EXISTS idx_sources_size_source ON sources(size, source);
    CREATE INDEX IF NOT EXISTS idx_cs_collector_status ON collection_status(collector, status);
"""

_SQL_UPSERT_SOURCES = """INSERT INTO sources (source, file_hash, size, modified)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(source) DO UPDATE SET
        file_hash = excluded.file_hash,
        size      = excluded.size,
        modified  = excluded.modified"""

_SQL_UPSERT_FILES = """INSERT INTO files (path, source, aspect_ratio)
    VALUES (?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        aspect_ratio = excluded.aspect_ratio"""

_SQL_UPSERT_FILES_COALESCE = """INSERT INTO files (path, source, aspect_ratio)
    VALUES (?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        aspect_ratio = COALESCE(excluded.aspect_ratio, files.aspect_ratio)"""

_SQL_UPSERT_META = """INSERT INTO meta_info (path, key, value, value_num)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(path, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num
    WHERE meta_info.locked = 0"""

_SQL_UPSERT_TAGS = """INSERT INTO tags (file_hash, key, value, value_num)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(file_hash, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num
    WHERE tags.locked = 0"""

_SQL_UPSERT_USER_TAGS = """INSERT INTO tags (file_hash, key, value, value_num, locked)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(file_hash, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num,
        locked    = excluded.locked"""

_SQL_UPSERT_USER_META = """INSERT INTO meta_info (path, key, value, value_num, locked)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(path, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num,
        locked    = excluded.locked"""

_SQL_UPSERT_COLLECTION_STATUS = """INSERT INTO collection_status (source, collector, status, collected_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(source, collector) DO UPDATE SET
        status       = excluded.status,
        collected_at = excluded.collected_at"""

_EXPECTED_SIGNATURES: dict[str, frozenset] = {}


def _table_signature(conn, name):
    rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
    if not rows:
        return None
    return frozenset((r[1], r[2], r[3], r[4], r[5]) for r in rows)


def _expected_table_signature(name, create_sql):
    if name not in _EXPECTED_SIGNATURES:
        tmp = sqlite3.connect(":memory:")
        try:
            tmp.execute(create_sql)
            _EXPECTED_SIGNATURES[name] = _table_signature(tmp, name)
        finally:
            tmp.close()
    return _EXPECTED_SIGNATURES[name]


class FileDB:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix(".bak")
        self.conn: sqlite3.Connection | None = None
        self.read_conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()

    @profiler.profile
    def start(self):
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=False)
        apply_write_pragmas(self.conn)
        uri = Path(self.db_path).resolve().as_uri()
        self.read_conn = connect_with_retry(f"{uri}?mode=ro", timeout=1.0, uri=True, check_same_thread=False)
        apply_read_pragmas(self.read_conn)

    @profiler.profile
    def close(self):
        self.try_checkpoint()
        if self.conn:
            self.conn.close()
            self.conn = None
        if self.read_conn:
            self.read_conn.close()
            self.read_conn = None

    def get_writer_cursor(self):
        return self.conn.cursor()

    def get_reader_cursor(self):
        return self.read_conn.cursor()

    def try_checkpoint(self, mode: str = "TRUNCATE"):
        try:
            conn = self.conn or self.read_conn
            cur = conn.execute(f"PRAGMA wal_checkpoint({mode})")
            cur.close()
        except Exception as e:
            AppLogger.debug(f"wal_checkpoint({mode}) failed: {e}")

    @profiler.profile
    def initialize_database(self):
        try:
            if not self._integrity_check():
                raise sqlite3.DatabaseError("Integrity check failed.")
        except sqlite3.DatabaseError as e:
            AppLogger.warning(f"DB corrupted: {e}", exc=e)
            self._backup_and_recreate()
        self._ensure_schema()

    @profiler.profile
    def _integrity_check(self) -> bool:
        try:
            result = self.conn.execute("PRAGMA quick_check").fetchone()
            return result[0] == "ok"
        except Exception as e:
            AppLogger.warning(f"integrity_check failed: {e}", exc=e)
            return False

    @profiler.profile
    def _backup_and_recreate(self):
        if self.read_conn:
            try:
                self.read_conn.close()
            except Exception as e:
                AppLogger.debug(f"read_conn.close() failed: {e}")
            self.read_conn = None
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                AppLogger.debug(f"conn.close() failed: {e}")
            self.conn = None
        try:
            if self.backup_path.exists():
                os.remove(self.backup_path)
            tmp = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                tmp.execute("PRAGMA journal_mode=WAL")
                tmp.execute("VACUUM INTO ?", (str(self.backup_path),))
            finally:
                tmp.close()
            for suf in ("", "-wal", "-shm"):
                try:
                    os.remove(str(self.db_path) + suf)
                except (FileNotFoundError, PermissionError) as e:
                    if isinstance(e, PermissionError):
                        AppLogger.warning(f"Cannot remove {self.db_path}{suf}: {e}", exc=e)
        except Exception as e:
            AppLogger.warning(f"VACUUM INTO backup failed: {e}", exc=e)
            if self.db_path.exists():
                try:
                    if self.backup_path.exists():
                        os.remove(self.backup_path)
                    shutil.copy(self.db_path, self.backup_path)
                except Exception as copy_err:
                    AppLogger.warning(f"Backup copy also failed: {copy_err}", exc=copy_err)
                for suf in ("", "-wal", "-shm"):
                    try:
                        os.remove(str(self.db_path) + suf)
                    except (FileNotFoundError, PermissionError) as rm_err:
                        if isinstance(rm_err, PermissionError):
                            AppLogger.warning(f"Cannot remove {self.db_path}{suf}: {rm_err}", exc=rm_err)
        try:
            self.start()
        except Exception as e:
            AppLogger.error(f"Failed to recreate DB at {self.db_path}: {e}", exc=e)
            raise
        AppLogger.warning(f"New DB created at: {self.db_path}")

    @profiler.profile
    def _ensure_schema(self):
        self._ensure_compatible_schema_migrations()
        changed = self._detect_changed_tables()
        if changed:
            AppLogger.info(f"[Schema] Recreating tables: {changed}")
            self._drop_tables(changed)
        self.conn.execute("PRAGMA foreign_keys=ON")
        for _, _, sql in _TABLES:
            self.conn.execute(sql)
        self.conn.commit()
        for name, _ in reversed(_VIEWS):
            self.conn.execute(f"DROP VIEW IF EXISTS {name}")
        for _, sql in _VIEWS:
            self.conn.execute(sql)
        self.conn.commit()
        self.conn.executescript(_INDEXES_SQL)

    def _ensure_compatible_schema_migrations(self):
        self._add_missing_column("meta_info", "locked", "locked INTEGER NOT NULL DEFAULT 0")
        self._add_missing_column("tags", "locked", "locked INTEGER NOT NULL DEFAULT 0")

    def _add_missing_column(self, table: str, column: str, column_sql: str):
        row = self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if not row:
            return
        columns = {r[1] for r in self.conn.execute(f"PRAGMA table_info('{table}')").fetchall()}
        if column in columns:
            return
        self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column_sql}")
        self.conn.commit()
        AppLogger.info(f"[Schema] Added {table}.{column}")

    def _detect_changed_tables(self):
        changed = set()
        for name, _, create_sql in _TABLES:
            actual = _table_signature(self.conn, name)
            if actual is None:
                continue
            if actual != _expected_table_signature(name, create_sql):
                changed.add(name)
        for name, deps, _ in _TABLES:
            if name not in changed and any(d in changed for d in deps):
                changed.add(name)
        return changed

    def _drop_tables(self, tables):
        self.conn.execute("PRAGMA foreign_keys=OFF")
        for name, _, _ in reversed(_TABLES):
            if name in tables:
                self.conn.execute(f"DROP TABLE IF EXISTS {name}")
        self.conn.commit()

    @profiler.profile
    def load_existing_sources(self) -> dict[str, tuple[float, int]]:
        result: dict[str, tuple[float, int]] = {}
        try:
            cur = self.get_reader_cursor()
            try:
                cur.execute("SELECT source, modified, size FROM sources")
                for source, mtime, size in cur.fetchall():
                    result[source] = (mtime, size)
            finally:
                cur.close()
        except Exception as e:
            AppLogger.warning(f"Failed to load previous data from DB: {e}", exc=e)
        return result

    @profiler.profile
    def delete_sources_by_paths(self, paths: Sequence[str]):
        if not paths:
            return
        with self._write_lock:
            cur = self.get_writer_cursor()
            try:
                cur.executemany("DELETE FROM sources WHERE source = ?", [(p,) for p in paths])
                self.conn.commit()
            finally:
                cur.close()

    @profiler.profile
    def rename_paths(self, pairs: Sequence[tuple[str, str]]):
        if not pairs:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                cur.execute("PRAGMA foreign_keys=ON")
                for old, new in pairs:
                    cur.execute("UPDATE sources SET source = ? WHERE source = ?", (new, old))
                    cur.execute("UPDATE files SET path = ? WHERE source = ?", (new, new))
                    name = os.path.basename(new)
                    cur.execute(
                        "UPDATE meta_info SET value = ? WHERE path = ? AND key = 'path'",
                        (new, new),
                    )
                    cur.execute(
                        "UPDATE meta_info SET value = ? WHERE path = ? AND key = 'name'",
                        (name, new),
                    )
            finally:
                cur.close()

    @staticmethod
    def _ensure_hash_indexes(cur, source_entries, tag_entries=()):
        file_hashes = set()
        for _, fid, *_ in source_entries:
            if fid:
                file_hashes.add(fid)
        for fid, *_ in tag_entries:
            if fid:
                file_hashes.add(fid)
        if file_hashes:
            cur.executemany(
                "INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)",
                [(h,) for h in file_hashes],
            )

    @staticmethod
    def _migrate_tags_on_hash_change(cur, source_entries):
        if not source_entries:
            return
        new_hash_by_path = {e[0]: e[1] for e in source_entries if e[0] and e[1]}
        if not new_hash_by_path:
            return
        paths = list(new_hash_by_path.keys())
        old_hash_by_path: dict[str, str] = {}
        for i in range(0, len(paths), 900):
            chunk = paths[i : i + 900]
            ph = ",".join(["?"] * len(chunk))
            rows = cur.execute(f"SELECT source, file_hash FROM sources WHERE source IN ({ph})", chunk).fetchall()
            for src, fh in rows:
                if fh:
                    old_hash_by_path[src] = fh
        migrations = [(new_hash_by_path[p], old) for p, old in old_hash_by_path.items() if new_hash_by_path[p] != old]
        if not migrations:
            return
        for new_hash, old_hash in migrations:
            cur.execute(
                """INSERT INTO tags (file_hash, key, value, value_num, locked)
                SELECT ?, key, value, value_num, locked FROM tags WHERE file_hash = ?
                ON CONFLICT(file_hash, key) DO NOTHING""",
                (new_hash, old_hash),
            )
        AppLogger.info(f"[DB] Migrated tags for {len(migrations)} sources with content change")

    @profiler.profile
    def upsert_batches(self, source_entries, image_entries, meta_info_entries, tag_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                self._ensure_hash_indexes(cur, source_entries, tag_entries)
                self._migrate_tags_on_hash_change(cur, source_entries)
                cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
                if image_entries:
                    cur.executemany(_SQL_UPSERT_FILES, image_entries)
                if meta_info_entries:
                    cur.executemany(_SQL_UPSERT_META, meta_info_entries)
                if tag_entries:
                    cur.executemany(_SQL_UPSERT_TAGS, tag_entries)
            finally:
                cur.close()

    @profiler.profile
    def upsert_basic_sources(self, source_entries, image_entries, meta_info_entries=()):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                self._ensure_hash_indexes(cur, source_entries)
                self._migrate_tags_on_hash_change(cur, source_entries)
                cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
                if image_entries:
                    cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
                if meta_info_entries:
                    cur.executemany(_SQL_UPSERT_META, meta_info_entries)
            finally:
                cur.close()

    @profiler.profile
    def upsert_collection_results(self, image_entries, meta_info_entries, tag_entries, collector_status_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                if image_entries:
                    try:
                        cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
                    except sqlite3.IntegrityError:
                        existing = self._existing_sources(cur)
                        image_entries = [e for e in image_entries if e[1] in existing]
                        collector_status_entries = [e for e in (collector_status_entries or []) if e[0] in existing]
                        if image_entries:
                            cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
                if meta_info_entries:
                    cur.executemany(_SQL_UPSERT_META, meta_info_entries)
                self._ensure_hash_indexes(cur, [], tag_entries)
                if tag_entries:
                    cur.executemany(_SQL_UPSERT_TAGS, tag_entries)
                if collector_status_entries:
                    try:
                        cur.executemany(_SQL_UPSERT_COLLECTION_STATUS, collector_status_entries)
                    except sqlite3.IntegrityError:
                        existing = self._existing_sources(cur)
                        collector_status_entries = [e for e in collector_status_entries if e[0] in existing]
                        if collector_status_entries:
                            cur.executemany(_SQL_UPSERT_COLLECTION_STATUS, collector_status_entries)
            finally:
                cur.close()

    def _existing_sources(self, cur):
        cur.execute("SELECT source FROM sources")
        return {row[0] for row in cur.fetchall()}

    @profiler.profile
    def insert_pending_collection(self, sources, collectors):
        if not sources or not collectors:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                entries = [(s, c, "pending", None) for s in sources for c in collectors]
                try:
                    cur.executemany(
                        """INSERT INTO collection_status (source, collector, status, collected_at)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(source, collector) DO UPDATE SET
                            status       = 'pending',
                            collected_at = NULL""",
                        entries,
                    )
                except sqlite3.IntegrityError:
                    existing = self._existing_sources(cur)
                    entries = [e for e in entries if e[0] in existing]
                    if entries:
                        cur.executemany(
                            """INSERT INTO collection_status (source, collector, status, collected_at)
                            VALUES (?, ?, ?, ?)
                            ON CONFLICT(source, collector) DO UPDATE SET
                                status       = 'pending',
                                collected_at = NULL""",
                            entries,
                        )
            finally:
                cur.close()

    @profiler.profile
    def get_sources_without_collector(self, collector):
        cur = self.get_reader_cursor()
        try:
            cur.execute(
                """SELECT s.source FROM sources s
                WHERE NOT EXISTS (
                    SELECT 1 FROM collection_status cs
                    WHERE cs.source = s.source AND cs.collector = ?
                )""",
                (collector,),
            )
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

    @profiler.profile
    def get_pending_sources(self, collector, limit=5000):
        cur = self.get_reader_cursor()
        try:
            cur.execute(
                """SELECT cs.source, s.modified, s.size
                FROM collection_status cs
                JOIN sources s ON s.source = cs.source
                WHERE cs.collector = ? AND cs.status = 'pending'
                LIMIT ?""",
                (collector, limit),
            )
            return cur.fetchall()
        finally:
            cur.close()

    @profiler.profile
    def mark_dispatched(self, sources, collector):
        if not sources:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                for i in range(0, len(sources), 900):
                    chunk = sources[i : i + 900]
                    cur.executemany(
                        """UPDATE collection_status SET status = 'dispatched'
                        WHERE source = ? AND collector = ? AND status = 'pending' """,
                        [(s, collector) for s in chunk],
                    )
            finally:
                cur.close()

    @profiler.profile
    def reset_stale_dispatched(self, collectors=None):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                if collectors:
                    for c in collectors:
                        cur.execute(
                            """UPDATE collection_status SET status = 'pending'
                            WHERE collector = ? AND status = 'dispatched' """,
                            (c,),
                        )
                else:
                    cur.execute(
                        """UPDATE collection_status SET status = 'pending'
                        WHERE status = 'dispatched' """,
                    )
                changed = cur.execute("SELECT changes()").fetchone()[0]
            finally:
                cur.close()
        if changed:
            AppLogger.info(f"[DB] Reset {changed} stale dispatched entries to pending")
        return changed

    @profiler.profile
    def delete_orphan_records(self):
        AppLogger.info("CLEANING UP DATABASE")
        try:
            with self._write_lock:
                cur = self.get_writer_cursor()
                try:
                    cur.execute("""
                        DELETE FROM collection_status
                        WHERE source NOT IN (SELECT source FROM sources)
                    """)
                    cur.execute("""
                        DELETE FROM meta_info
                        WHERE path NOT IN (SELECT path FROM files)
                    """)
                    cur.execute("""
                        DELETE FROM tags
                        WHERE file_hash NOT IN (SELECT file_hash FROM sources);
                    """)
                    cur.execute("""
                        DELETE FROM hash_index
                        WHERE file_hash NOT IN (SELECT file_hash FROM sources)
                        AND file_hash NOT IN (SELECT file_hash FROM tags);
                    """)

                    self.conn.commit()

                    AppLogger.info("RUNNING VACUUM")
                    cur.execute("VACUUM")
                    AppLogger.info("RUNNING ANALYZE")
                    cur.execute("ANALYZE")
                    self.conn.commit()
                    self.try_checkpoint()
                finally:
                    cur.close()
        except Exception as e:
            AppLogger.warning(f"DATABASE CLEANUP FAILED: {e}", exc=e)
        else:
            AppLogger.info("DATABASE CLEANUP END")

    def delete_collector_data(self, collector: str, *, re_collect: bool = False):
        meta_deleted = 0
        tags_deleted = 0
        cs_affected = 0
        escaped = collector.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"{escaped}.%"
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                cur.execute("DELETE FROM meta_info WHERE key LIKE ? ESCAPE '\\' AND locked = 0", (pattern,))
                meta_deleted = cur.execute("SELECT changes()").fetchone()[0]
                cur.execute("DELETE FROM tags WHERE key LIKE ? ESCAPE '\\' AND locked = 0", (pattern,))
                tags_deleted = cur.execute("SELECT changes()").fetchone()[0]
                if re_collect:
                    cur.execute(
                        "UPDATE collection_status SET status = 'pending', collected_at = NULL WHERE collector = ?",
                        (collector,),
                    )
                else:
                    cur.execute("DELETE FROM collection_status WHERE collector = ?", (collector,))
                cs_affected = cur.execute("SELECT changes()").fetchone()[0]
            finally:
                cur.close()
        AppLogger.info(f"[DB] Deleted collector={collector}: meta={meta_deleted}, tags={tags_deleted}, cs={cs_affected}")
        return meta_deleted, tags_deleted, cs_affected

    def delete_keys(self, keys: list[str]) -> tuple[int, int]:
        if not keys:
            return 0, 0
        meta_deleted = 0
        tags_deleted = 0
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                for i in range(0, len(keys), 900):
                    chunk = keys[i : i + 900]
                    placeholders = ",".join(["?"] * len(chunk))
                    cur.execute(f"DELETE FROM meta_info WHERE key IN ({placeholders}) AND locked = 0", chunk)
                    meta_deleted += cur.execute("SELECT changes()").fetchone()[0]
                    cur.execute(f"DELETE FROM tags WHERE key IN ({placeholders}) AND locked = 0", chunk)
                    tags_deleted += cur.execute("SELECT changes()").fetchone()[0]
            finally:
                cur.close()
        AppLogger.info(f"[DB] Deleted keys ({len(keys)}): meta={meta_deleted}, tags={tags_deleted}")
        return meta_deleted, tags_deleted

    def reset_collector_status(self, collector: str) -> int:
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                cur.execute(
                    "UPDATE collection_status SET status = 'pending', collected_at = NULL WHERE collector = ?",
                    (collector,),
                )
                affected = cur.execute("SELECT changes()").fetchone()[0]
            finally:
                cur.close()
        AppLogger.info(f"[DB] Reset collector status: collector={collector}, affected={affected}")
        return affected

    def collector_data_counts(self) -> list[tuple[str, int]]:
        cur = self.get_reader_cursor()
        try:
            cur.execute("SELECT collector, COUNT(*) FROM collection_status WHERE status = 'ok' GROUP BY collector")
            return cur.fetchall()
        finally:
            cur.close()

    def prefix_data_summary(self) -> list[tuple[str, int, int]]:
        cur = self.get_reader_cursor()
        try:
            cur.execute("""
                SELECT prefix, SUM(meta_count), SUM(tag_count) FROM (
                    SELECT
                        CASE WHEN INSTR(key, '.') > 0
                             THEN SUBSTR(key, 1, INSTR(key, '.') - 1)
                             ELSE '' END AS prefix,
                        COUNT(*) AS meta_count,
                        0 AS tag_count
                    FROM meta_info GROUP BY prefix
                    UNION ALL
                    SELECT
                        CASE WHEN INSTR(key, '.') > 0
                             THEN SUBSTR(key, 1, INSTR(key, '.') - 1)
                             ELSE '' END AS prefix,
                        0 AS meta_count,
                        COUNT(*) AS tag_count
                    FROM tags GROUP BY prefix
                ) GROUP BY prefix ORDER BY prefix
            """)
            return cur.fetchall()
        finally:
            cur.close()

    def delete_meta_and_tags_by_keys(self, delete_entries: list[tuple[str, str | None, list[str]]]):
        if not delete_entries:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                for path, file_hash, keys in delete_entries:
                    if not keys:
                        continue
                    placeholders = ",".join(["?"] * len(keys))
                    cur.execute(
                        f"DELETE FROM meta_info WHERE path = ? AND key IN ({placeholders}) AND locked = 0",
                        [path] + keys,
                    )
                    if file_hash:
                        cur.execute(
                            f"DELETE FROM tags WHERE file_hash = ? AND key IN ({placeholders}) AND locked = 0",
                            [file_hash] + keys,
                        )
            finally:
                cur.close()

    def apply_user_kv(
        self,
        paths: Sequence[str],
        upserts: list[tuple[str, str, float | None, int]],
        deletes: list[str],
        *,
        scope: str = "tag",
        lock_only: bool = False,
        renames: list[tuple[str, str, str, float | None, int]] | None = None,
    ) -> dict[str, tuple[str, list[str], list[str]]]:
        renames = list(renames or [])
        if not paths or (not upserts and not deletes and not renames):
            return {}
        if scope not in ("tag", "meta_info"):
            raise ValueError(f"Unsupported key-value scope: {scope}")
        table = "tags" if scope == "tag" else "meta_info"
        target_col = "file_hash" if scope == "tag" else "path"
        upsert_sql = _SQL_UPSERT_USER_TAGS if scope == "tag" else _SQL_UPSERT_USER_META
        results: dict[str, tuple[str, list[str], list[str]]] = {}
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                target_by_path = self._resolve_user_kv_targets(cur, scope, paths)
                paths_list = list(paths)
                missing = [p for p in paths_list if p not in target_by_path]
                if missing:
                    reason = "file_hash" if scope == "tag" else "file row"
                    AppLogger.warning(f"[DB] apply_user_kv: {len(missing)} paths have no {reason} (skipped)")
                upsert_keys = [k for (k, _v, _vn, _lk) in upserts]
                for path, target_id in target_by_path.items():
                    applied: list[str] = []
                    deleted: list[str] = []
                    for old_key, new_key, value, value_num, locked in renames:
                        if not old_key or not new_key or old_key == new_key:
                            continue
                        exists = cur.execute(
                            f"SELECT 1 FROM {table} WHERE {target_col} = ? AND key = ?",
                            (target_id, new_key),
                        ).fetchone()
                        if exists:
                            AppLogger.warning(f"[DB] apply_user_kv: rename collision skipped {old_key}->{new_key}")
                            continue
                        cur.execute(
                            f"UPDATE {table} SET key = ?, value = ?, value_num = ?, locked = ? WHERE {target_col} = ? AND key = ?",
                            (new_key, value, value_num, locked, target_id, old_key),
                        )
                        if cur.execute("SELECT changes()").fetchone()[0] > 0:
                            applied.append(new_key)
                            deleted.append(old_key)
                    if upserts:
                        if lock_only:
                            for k, _v, _vn, lk in upserts:
                                cur.execute(
                                    f"UPDATE {table} SET locked = ? WHERE {target_col} = ? AND key = ?",
                                    (lk, target_id, k),
                                )
                                if cur.execute("SELECT changes()").fetchone()[0] > 0:
                                    applied.append(k)
                        else:
                            entries = [(target_id, k, v, vn, lk) for (k, v, vn, lk) in upserts]
                            cur.executemany(upsert_sql, entries)
                            applied.extend(upsert_keys)
                    if deletes:
                        placeholders = ",".join(["?"] * len(deletes))
                        cur.execute(
                            f"DELETE FROM {table} WHERE {target_col} = ? AND key IN ({placeholders}) AND locked = 0",
                            [target_id] + list(deletes),
                        )
                        if cur.execute("SELECT changes()").fetchone()[0] > 0:
                            rows = cur.execute(
                                f"SELECT key FROM {table} WHERE {target_col} = ? AND key IN ({placeholders})",
                                [target_id] + list(deletes),
                            ).fetchall()
                            remaining = {r[0] for r in rows}
                            deleted.extend(k for k in deletes if k not in remaining)
                    results[path] = (target_id, applied, deleted)
            finally:
                cur.close()
        AppLogger.info(f"[DB] apply_user_kv scope={scope} paths={len(paths_list)} resolved={len(results)} renames={len(renames)} upserts={len(upserts)} deletes={len(deletes)}")
        return results

    def apply_user_meta_info(
        self,
        paths: Sequence[str],
        upserts: list[tuple[str, str, float | None, int]],
        deletes: list[str],
        *,
        lock_only: bool = False,
        renames: list[tuple[str, str, str, float | None, int]] | None = None,
    ) -> dict[str, tuple[str, list[str], list[str]]]:
        return self.apply_user_kv(
            paths,
            upserts,
            deletes,
            scope="meta_info",
            lock_only=lock_only,
            renames=renames,
        )

    @staticmethod
    def _resolve_user_kv_targets(cur, scope: str, paths: Sequence[str]) -> dict[str, str]:
        result: dict[str, str] = {}
        paths_list = list(paths)
        for i in range(0, len(paths_list), 900):
            chunk = paths_list[i : i + 900]
            ph = ",".join(["?"] * len(chunk))
            if scope == "tag":
                rows = cur.execute(f"SELECT source, file_hash FROM sources WHERE source IN ({ph})", chunk).fetchall()
                for src, file_hash in rows:
                    if file_hash:
                        result[src] = file_hash
            else:
                rows = cur.execute(f"SELECT path FROM files WHERE path IN ({ph})", chunk).fetchall()
                for (path,) in rows:
                    result[path] = path
        return result

    def find_sources_with_trigger_keys(self, trigger_keys: tuple[str, ...], parser_status_name: str) -> list[str]:
        if not trigger_keys:
            return []
        cur = self.get_reader_cursor()
        try:
            placeholders = ",".join(["?"] * len(trigger_keys))
            cur.execute(
                f"""SELECT DISTINCT mi.path FROM meta_info mi
                WHERE mi.key IN ({placeholders})
                AND mi.path NOT IN (
                    SELECT cs.source FROM collection_status cs
                    WHERE cs.collector = ?
                )
                UNION
                SELECT DISTINCT i.path FROM tags t
                JOIN sources s ON s.file_hash = t.file_hash
                JOIN files i ON i.source = s.source
                WHERE t.key IN ({placeholders})
                AND i.path NOT IN (
                    SELECT cs.source FROM collection_status cs
                    WHERE cs.collector = ?
                )""",
                list(trigger_keys) + [parser_status_name] + list(trigger_keys) + [parser_status_name],
            )
            return [row[0] for row in cur.fetchall()]
        finally:
            cur.close()

    def get_trigger_metadata(self, sources: list[str], trigger_keys: tuple[str, ...]) -> dict[str, dict[str, str]]:
        if not sources or not trigger_keys:
            return {}
        result: dict[str, dict[str, str]] = {}
        key_ph = ",".join(["?"] * len(trigger_keys))
        cur = self.get_reader_cursor()
        try:
            chunk_size = 900
            key_list = list(trigger_keys)
            for i in range(0, len(sources), chunk_size):
                chunk = sources[i : i + chunk_size]
                src_ph = ",".join(["?"] * len(chunk))
                cur.execute(
                    f"SELECT path, key, value FROM meta_info WHERE path IN ({src_ph}) AND key IN ({key_ph})",
                    chunk + key_list,
                )
                for path, key, value in cur.fetchall():
                    result.setdefault(path, {})[key] = value
                cur.execute(
                    f"""SELECT i.path, t.key, t.value FROM tags t
                    JOIN sources s ON s.file_hash = t.file_hash
                    JOIN files i ON i.source = s.source
                    WHERE i.path IN ({src_ph}) AND t.key IN ({key_ph})""",
                    chunk + key_list,
                )
                for path, key, value in cur.fetchall():
                    result.setdefault(path, {})[key] = value
        finally:
            cur.close()
        return result

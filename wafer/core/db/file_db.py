from __future__ import annotations
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from collections.abc import Sequence

from .db_utils import apply_read_pragmas, apply_write_pragmas, connect_with_retry, escape_like
from .key_value import SCOPE_ALL, SCOPE_META_INFO, SCOPE_TAG, conversion_spec, normalize_data_scope, scope_spec
from ...constants import VIRTUAL_PATH_SEPARATOR
from ...utils.virtual_paths import display_name
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
        created REAL,
        collected REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )""",
    ),
    (
        "files",
        ("sources",),
        """CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        name TEXT,
        aspect_ratio REAL,
        source_extension TEXT,
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
        SELECT i.path, i.name, i.source, i.aspect_ratio, i.source_extension,
               s.file_hash, s.size, s.modified, s.created, s.collected
        FROM files i JOIN sources s ON s.source = i.source""",
    ),
)

_INDEXES_SQL = """
    CREATE INDEX IF NOT EXISTS idx_sources_file_hash ON sources(file_hash);
    CREATE INDEX IF NOT EXISTS idx_files_source ON files(source);
    CREATE INDEX IF NOT EXISTS idx_files_source_extension ON files(source_extension, source);
    CREATE INDEX IF NOT EXISTS idx_files_name ON files(name);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_fid ON meta_info(key, path);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_value ON meta_info(key, value);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_num ON meta_info(key, value_num);
    CREATE INDEX IF NOT EXISTS idx_tags_key_fid ON tags(key, file_hash);
    CREATE INDEX IF NOT EXISTS idx_tags_key_value ON tags(key, value);
    CREATE INDEX IF NOT EXISTS idx_tags_key_num ON tags(key, value_num);
    CREATE INDEX IF NOT EXISTS idx_sources_modified ON sources(modified);
    CREATE INDEX IF NOT EXISTS idx_sources_created ON sources(created);
    CREATE INDEX IF NOT EXISTS idx_sources_collected ON sources(collected);
    CREATE INDEX IF NOT EXISTS idx_sources_size ON sources(size);
    CREATE INDEX IF NOT EXISTS idx_cs_collector_status ON collection_status(collector, status);
"""

_SQL_UPSERT_SOURCES = """INSERT INTO sources (source, file_hash, size, modified, created, collected)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(source) DO UPDATE SET
        file_hash = excluded.file_hash,
        size      = excluded.size,
        modified  = excluded.modified,
        created   = excluded.created,
        collected = COALESCE(sources.collected, excluded.collected)"""

_SQL_UPSERT_FILES = """INSERT INTO files (path, source, name, aspect_ratio, source_extension)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        name         = excluded.name,
        aspect_ratio = excluded.aspect_ratio,
        source_extension = excluded.source_extension"""

_SQL_UPSERT_FILES_COALESCE = """INSERT INTO files (path, source, name, aspect_ratio, source_extension)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        name         = COALESCE(excluded.name, files.name),
        aspect_ratio = COALESCE(excluded.aspect_ratio, files.aspect_ratio),
        source_extension = excluded.source_extension"""

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


def _table_columns(conn, name):
    return [row[1] for row in conn.execute(f"PRAGMA table_info('{name}')").fetchall()]


def _quote_identifier(name: str) -> str:
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


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
        for name, _ in reversed(_VIEWS):
            self.conn.execute(f"DROP VIEW IF EXISTS {name}")
        if changed:
            AppLogger.info(f"[Schema] Recreating tables: {changed}")
            self._recreate_tables(changed)
        self.conn.execute("PRAGMA foreign_keys=ON")
        for _, _, sql in _TABLES:
            self.conn.execute(sql)
        self.conn.commit()
        for _, sql in _VIEWS:
            self.conn.execute(sql)
        self.conn.commit()
        self.conn.executescript(_INDEXES_SQL)

    def _ensure_compatible_schema_migrations(self):
        self._add_missing_column("files", "source_extension", "source_extension TEXT")
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

    def _recreate_tables(self, tables):
        ordered_tables = [name for name, _, _ in _TABLES if name in tables and _table_signature(self.conn, name) is not None]
        if not ordered_tables:
            return

        backup_names = {name: f"__old__{name}" for name in ordered_tables}
        self.conn.execute("PRAGMA foreign_keys=OFF")
        try:
            for name in reversed(ordered_tables):
                backup_name = backup_names[name]
                self.conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(backup_name)}")
                self.conn.execute(f"ALTER TABLE {_quote_identifier(name)} RENAME TO {_quote_identifier(backup_name)}")

            for _, _, sql in _TABLES:
                self.conn.execute(sql)

            for name in ordered_tables:
                backup_name = backup_names[name]
                columns = [column for column in _table_columns(self.conn, backup_name) if column in set(_table_columns(self.conn, name))]
                if columns:
                    columns_sql = ", ".join(_quote_identifier(column) for column in columns)
                    self.conn.execute(f"INSERT INTO {_quote_identifier(name)} ({columns_sql}) SELECT {columns_sql} FROM {_quote_identifier(backup_name)}")

            for name in reversed(ordered_tables):
                self.conn.execute(f"DROP TABLE IF EXISTS {_quote_identifier(backup_names[name])}")

            self.conn.commit()
        finally:
            self.conn.execute("PRAGMA foreign_keys=ON")

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
    def delete_sources_by_path_prefixes(self, paths: Sequence[str]):
        prefixes = tuple(dict.fromkeys(p for p in paths if p))
        if not prefixes:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                existing = set()
                for i in range(0, len(prefixes), 900):
                    chunk = prefixes[i : i + 900]
                    placeholders = ",".join(["?"] * len(chunk))
                    rows = cur.execute(f"SELECT source FROM sources WHERE source IN ({placeholders})", chunk).fetchall()
                    existing.update(row[0] for row in rows)
                    cur.executemany("DELETE FROM sources WHERE source = ?", [(path,) for path in chunk])
                for prefix in (path for path in prefixes if path not in existing):
                    child_pattern = f"{escape_like(prefix if prefix.endswith('/') else prefix + '/')}%"
                    cur.execute(
                        "DELETE FROM sources WHERE source = ? OR source LIKE ? ESCAPE '\\'",
                        (prefix, child_pattern),
                    )
            finally:
                cur.close()

    @profiler.profile
    def rename_paths(self, pairs: Sequence[tuple[str, str]]) -> list[str]:
        if not pairs:
            return []
        missing: list[str] = []
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                cur.execute("PRAGMA foreign_keys=ON")
                for old, new in pairs:
                    path_map = self._renamed_file_paths(cur, old, new)
                    cur.execute("UPDATE sources SET source = ? WHERE source = ?", (new, old))
                    if cur.rowcount == 0:
                        missing.append(new)
                        continue
                    for old_path, new_path in path_map.items():
                        if old_path != new_path:
                            cur.execute("UPDATE files SET path = ? WHERE path = ?", (new_path, old_path))
                    cur.executemany(
                        "UPDATE files SET name = ? WHERE path = ?",
                        [(display_name(new_path), new_path) for new_path in path_map.values()],
                    )
            finally:
                cur.close()
        return missing

    def load_source_signatures(self, paths: Sequence[str]) -> dict[str, tuple[str, int | None]]:
        if not paths:
            return {}
        result: dict[str, tuple[str, int | None]] = {}
        cur = self.get_reader_cursor()
        try:
            unique_paths = list(dict.fromkeys(str(path) for path in paths if path))
            for start in range(0, len(unique_paths), 900):
                chunk = unique_paths[start : start + 900]
                placeholders = ",".join(["?"] * len(chunk))
                rows = cur.execute(
                    f"SELECT source, file_hash, size FROM sources WHERE source IN ({placeholders})",
                    chunk,
                ).fetchall()
                for source, file_hash, size in rows:
                    result[source] = (file_hash, size)
        finally:
            cur.close()
        return result

    @staticmethod
    def _renamed_file_paths(cur, old: str, new: str) -> dict[str, str]:
        prefix = old + VIRTUAL_PATH_SEPARATOR
        rows = cur.execute(
            "SELECT path FROM files WHERE source = ? AND (path = ? OR path LIKE ? ESCAPE '\\')",
            (old, old, f"{escape_like(prefix)}%"),
        ).fetchall()
        paths: dict[str, str] = {}
        for (path,) in rows:
            if path == old:
                paths[path] = new
            elif path.startswith(prefix):
                paths[path] = new + VIRTUAL_PATH_SEPARATOR + path[len(prefix) :]
        return paths

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

    @staticmethod
    def _normalize_file_entries(image_entries):
        entries = []
        for entry in image_entries or []:
            n = len(entry)
            if n == 5:
                path, source, name, aspect, source_extension = entry
            elif n == 3:
                path, source, aspect = entry
                name = None
                source_extension = None
            else:
                raise ValueError(f"file entry must be (path, source, aspect) or (path, source, name, aspect, source_extension): got {entry!r}")
            if not name:
                name = display_name(path) if path else None
            entries.append((path, source, name, aspect, source_extension or None))
        return entries

    @staticmethod
    def _normalize_source_entries(source_entries):
        entries = []
        for entry in source_entries or []:
            n = len(entry)
            if n == 6:
                entries.append(tuple(entry))
            elif n == 4:
                src, fh, size, mtime = entry
                entries.append((src, fh, size, mtime, None, None))
            else:
                raise ValueError(f"source entry must be (source, file_hash, size, modified) or include (created, collected): got {entry!r}")
        return entries

    @profiler.profile
    def upsert_batches(self, source_entries, image_entries, meta_info_entries, tag_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                source_entries = self._normalize_source_entries(source_entries)
                self._ensure_hash_indexes(cur, source_entries, tag_entries)
                self._migrate_tags_on_hash_change(cur, source_entries)
                cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
                image_entries = self._normalize_file_entries(image_entries)
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
                source_entries = self._normalize_source_entries(source_entries)
                self._ensure_hash_indexes(cur, source_entries)
                self._migrate_tags_on_hash_change(cur, source_entries)
                cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
                image_entries = self._normalize_file_entries(image_entries)
                if image_entries:
                    cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
                if meta_info_entries:
                    cur.executemany(_SQL_UPSERT_META, meta_info_entries)
            finally:
                cur.close()

    @profiler.profile
    def upsert_collection_results(self, image_entries, meta_info_entries, tag_entries, collector_status_entries, *, cleanup: bool = True):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                image_entries = self._normalize_file_entries(image_entries)
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
                if cleanup:
                    self._delete_missing_source_extension_children(cur, image_entries, collector_status_entries)
            finally:
                cur.close()

    @profiler.profile
    def cleanup_source_extension_children(self, image_entries, collector_status_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                entries = self._normalize_file_entries(image_entries)
                self._delete_missing_source_extension_children(cur, entries, collector_status_entries)
            finally:
                cur.close()

    def _delete_missing_source_extension_children(self, cur, image_entries, collector_status_entries):
        ok_pairs = {(src, collector) for src, collector, status, *_ in (collector_status_entries or []) if src and collector and status == "ok"}
        if not ok_pairs:
            return
        keep_by_pair: dict[tuple[str, str], set[str]] = {pair: set() for pair in ok_pairs}
        for path, source, _name, _aspect, source_extension in image_entries or []:
            if not source_extension or path == source:
                continue
            pair = (source, source_extension)
            if pair in keep_by_pair:
                keep_by_pair[pair].add(path)
        deleted = 0
        for (source, extension), keep in keep_by_pair.items():
            rows = cur.execute(
                "SELECT path FROM files WHERE source = ? AND source_extension = ?",
                (source, extension),
            ).fetchall()
            stale = [(row[0],) for row in rows if row[0] not in keep]
            if stale:
                cur.executemany("DELETE FROM files WHERE path = ?", stale)
                deleted += len(stale)
        if deleted:
            AppLogger.info(f"[DB] Deleted stale source extension child rows: {deleted}")

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
        child_deleted = 0
        escaped = collector.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        pattern = f"{escaped}.%"
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                cur.execute("DELETE FROM files WHERE source_extension = ?", (collector,))
                child_deleted = cur.execute("SELECT changes()").fetchone()[0]
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
        AppLogger.info(f"[DB] Deleted collector={collector}: children={child_deleted}, meta={meta_deleted}, tags={tags_deleted}, cs={cs_affected}")
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
        scope = normalize_data_scope(scope, allow_all=True)
        if scope == SCOPE_ALL:
            if upserts or renames or lock_only:
                raise ValueError("scope='*' only supports key deletion")
            return self._delete_user_kv_all_scopes(paths, deletes)
        spec = scope_spec(scope)
        table = spec.table
        target_col = spec.target_column
        upsert_sql = _SQL_UPSERT_USER_TAGS if scope == SCOPE_TAG else _SQL_UPSERT_USER_META
        results: dict[str, tuple[str, list[str], list[str]]] = {}
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                target_by_path = self._resolve_user_kv_targets(cur, scope, paths)
                paths_list = list(paths)
                missing = [p for p in paths_list if p not in target_by_path]
                if missing:
                    reason = "file_hash" if target_col == "file_hash" else "path"
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

    def _delete_user_kv_all_scopes(self, paths: Sequence[str], deletes: list[str]) -> dict[str, tuple[str, list[str], list[str]]]:
        deletes = [str(key).strip() for key in deletes if str(key).strip()]
        if not paths or not deletes:
            return {}
        paths_list = list(paths)
        results: dict[str, tuple[str, list[str], list[str]]] = {}
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                tag_targets = self._resolve_user_kv_targets(cur, SCOPE_TAG, paths_list)
                meta_targets = self._resolve_user_kv_targets(cur, SCOPE_META_INFO, paths_list)
                placeholders = ",".join(["?"] * len(deletes))
                for path in paths_list:
                    remaining_any: set[str] = set()
                    tag_target = tag_targets.get(path)
                    if tag_target:
                        cur.execute(
                            f"DELETE FROM tags WHERE file_hash = ? AND key IN ({placeholders}) AND locked = 0",
                            [tag_target] + deletes,
                        )
                        rows = cur.execute(
                            f"SELECT key FROM tags WHERE file_hash = ? AND key IN ({placeholders})",
                            [tag_target] + deletes,
                        ).fetchall()
                        remaining_any.update(row[0] for row in rows)
                    meta_target = meta_targets.get(path)
                    if meta_target:
                        cur.execute(
                            f"DELETE FROM meta_info WHERE path = ? AND key IN ({placeholders}) AND locked = 0",
                            [meta_target] + deletes,
                        )
                        rows = cur.execute(
                            f"SELECT key FROM meta_info WHERE path = ? AND key IN ({placeholders})",
                            [meta_target] + deletes,
                        ).fetchall()
                        remaining_any.update(row[0] for row in rows)
                    if tag_target or meta_target:
                        deleted = [key for key in deletes if key not in remaining_any]
                        results[path] = (tag_target or meta_target or path, [], sorted(deleted))
            finally:
                cur.close()
        AppLogger.info(f"[DB] apply_user_kv scope=* paths={len(paths_list)} resolved={len(results)} deletes={len(deletes)}")
        return results

    def convert_key_scope(self, key: str, to_scope: str) -> dict[str, int | str | list[str] | dict[str, str]]:
        key = str(key or "").strip()
        if not key:
            raise ValueError("key must not be empty")
        to_scope = normalize_data_scope(to_scope)
        conversion = conversion_spec(to_scope)
        from_scope = conversion.from_scope
        affected_rows: list[tuple[str, str | None]] = []
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            try:
                affected_rows = [(str(path), str(target_id) if target_id else None) for path, target_id in cur.execute(conversion.affected_rows_sql, (key,)).fetchall()]
                cur.execute(conversion.insert_sql, (key,))
                upserted = cur.execute("SELECT changes()").fetchone()[0]
                cur.execute(conversion.delete_sql, (key,))
                source_deleted = cur.execute("SELECT changes()").fetchone()[0]
            finally:
                cur.close()
        affected_paths: list[str] = []
        targets: dict[str, str] = {}
        seen_paths: set[str] = set()
        for path, file_hash in affected_rows:
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            affected_paths.append(path)
            if file_hash:
                targets[path] = file_hash
        AppLogger.info(f"[DB] convert_key_scope key={key} {from_scope}->{to_scope} upserted={upserted} source_deleted={source_deleted}")
        return {
            "key": key,
            "from_scope": from_scope,
            "to_scope": to_scope,
            "upserted": int(upserted),
            "source_deleted": int(source_deleted),
            "paths": affected_paths,
            "targets": targets,
        }

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
            if scope == SCOPE_TAG:
                rows = cur.execute(
                    f"""SELECT i.path, s.file_hash
                    FROM files AS i
                    JOIN sources AS s ON s.source = i.source
                    WHERE i.path IN ({ph})""",
                    chunk,
                ).fetchall()
                for path, file_hash in rows:
                    if file_hash:
                        result[path] = file_hash
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

from __future__ import annotations
import os
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Sequence

from .db_utils import apply_read_pragmas, apply_write_pragmas, connect_with_retry
from ...utils.profiling import profiler
from ...utils.logs import AppLogger

_TABLES = (
    ('hash_index', (),
     'CREATE TABLE IF NOT EXISTS hash_index (file_hash TEXT PRIMARY KEY)'),
    ('sources', ('hash_index',),
     '''CREATE TABLE IF NOT EXISTS sources (
        source TEXT PRIMARY KEY, 
        file_hash TEXT NOT NULL,
        size INTEGER, 
        modified REAL, 
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )'''),
    ('files', ('sources',),
     '''CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY, 
        source TEXT NOT NULL, 
        aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
    ('meta_info', ('files',),
     '''CREATE TABLE IF NOT EXISTS meta_info (
        path TEXT NOT NULL, 
        key TEXT NOT NULL, 
        value TEXT,
        value_num REAL,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
    ('tags', ('hash_index',),
     '''CREATE TABLE IF NOT EXISTS tags (
        file_hash TEXT NOT NULL, 
        key TEXT NOT NULL, 
        value TEXT,
        value_num REAL,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
    ('collection_status', ('sources',),
     '''CREATE TABLE IF NOT EXISTS collection_status (
        source TEXT NOT NULL, 
        collector TEXT NOT NULL,
        status TEXT DEFAULT 'pending',
        collected_at REAL,
        PRIMARY KEY(source, collector),
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
)

_VIEWS = (
    ('files_full',
     '''CREATE VIEW files_full AS
        SELECT i.path, i.source, i.aspect_ratio,
               s.file_hash, s.size, s.modified
        FROM files i JOIN sources s ON s.source = i.source'''),
    ('kv_all',
     '''CREATE VIEW kv_all AS
        WITH base AS (
            SELECT mi.path AS path, mi.key AS key, mi.value AS value, mi.value_num AS value_num, 'meta_info' AS src, 2 AS rank
            FROM meta_info AS mi
        UNION ALL
            SELECT i.path AS path, t.key AS key, t.value AS value, t.value_num AS value_num, 'tags' AS src, 0 AS rank
            FROM tags AS t
            JOIN sources AS s ON s.file_hash = t.file_hash
            JOIN files  AS i ON i.source    = s.source
        ),
        picked AS (
            SELECT path, key, value, value_num, src, rank,
                ROW_NUMBER() OVER (PARTITION BY path, key ORDER BY rank, src) AS rn
            FROM base
        )
        SELECT path, key, value, value_num, src FROM picked WHERE rn = 1'''),
    ('kv_meta',
     '''CREATE VIEW kv_meta AS
        SELECT k.path, vf.file_hash, k.key, k.value, k.value_num, k.src
        FROM kv_all AS k JOIN files_full AS vf ON vf.path = k.path'''),
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

_SQL_UPSERT_SOURCES = '''INSERT INTO sources (source, file_hash, size, modified)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(source) DO UPDATE SET
        file_hash = excluded.file_hash,
        size      = excluded.size,
        modified  = excluded.modified'''

_SQL_UPSERT_FILES = '''INSERT INTO files (path, source, aspect_ratio)
    VALUES (?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        aspect_ratio = excluded.aspect_ratio'''

_SQL_UPSERT_FILES_COALESCE = '''INSERT INTO files (path, source, aspect_ratio)
    VALUES (?, ?, ?)
    ON CONFLICT(path) DO UPDATE SET
        source       = excluded.source,
        aspect_ratio = COALESCE(excluded.aspect_ratio, files.aspect_ratio)'''

_SQL_UPSERT_META = '''INSERT INTO meta_info (path, key, value, value_num)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(path, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num'''

_SQL_UPSERT_TAGS = '''INSERT INTO tags (file_hash, key, value, value_num)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(file_hash, key) DO UPDATE SET
        value     = excluded.value,
        value_num = excluded.value_num'''

_SQL_UPSERT_COLLECTION_STATUS = '''INSERT INTO collection_status (source, collector, status, collected_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(source, collector) DO UPDATE SET
        status       = excluded.status,
        collected_at = excluded.collected_at'''

_EXPECTED_SIGNATURES: dict[str, frozenset] = {}


def _table_signature(conn, name):
    rows = conn.execute(f"PRAGMA table_info('{name}')").fetchall()
    if not rows:
        return None
    return frozenset((r[1], r[2], r[3], r[4], r[5]) for r in rows)


def _expected_table_signature(name, create_sql):
    if name not in _EXPECTED_SIGNATURES:
        tmp = sqlite3.connect(':memory:')
        try:
            tmp.execute(create_sql)
            _EXPECTED_SIGNATURES[name] = _table_signature(tmp, name)
        finally:
            tmp.close()
    return _EXPECTED_SIGNATURES[name]


class FileDB:

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix('.bak')
        self.conn: sqlite3.Connection | None = None
        self.read_conn: sqlite3.Connection | None = None
        self._write_lock = threading.Lock()

    @profiler.profile
    def start(self):
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=False)
        apply_write_pragmas(self.conn)
        uri = Path(self.db_path).resolve().as_uri()
        self.read_conn = connect_with_retry(f'{uri}?mode=ro', timeout=1.0, uri=True, check_same_thread=False)
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

    def try_checkpoint(self, mode: str = 'TRUNCATE'):
        try:
            conn = self.conn or self.read_conn
            cur = conn.execute(f'PRAGMA wal_checkpoint({mode})')
            cur.close()
        except Exception:
            AppLogger.debug(f'wal_checkpoint({mode}) failed')

    @profiler.profile
    def initialize_database(self):
        try:
            if not self._integrity_check():
                raise sqlite3.DatabaseError('Integrity check failed.')
        except sqlite3.DatabaseError as e:
            AppLogger.warning(f'DB corrupted: {e}', exc=e)
            self._backup_and_recreate()
        self._ensure_schema()

    @profiler.profile
    def _integrity_check(self) -> bool:
        try:
            result = self.conn.execute('PRAGMA quick_check').fetchone()
            return result[0] == 'ok'
        except Exception as e:
            AppLogger.warning(f'integrity_check failed: {e}', exc=e)
            return False

    @profiler.profile
    def _backup_and_recreate(self):
        if self.read_conn:
            try:
                self.read_conn.close()
            except Exception as e:
                AppLogger.debug(f'read_conn.close() failed: {e}')
            self.read_conn = None
        if self.conn:
            try:
                self.conn.close()
            except Exception as e:
                AppLogger.debug(f'conn.close() failed: {e}')
            self.conn = None
        try:
            if self.backup_path.exists():
                os.remove(self.backup_path)
            tmp = sqlite3.connect(str(self.db_path), check_same_thread=False)
            try:
                tmp.execute('PRAGMA journal_mode=WAL')
                tmp.execute('VACUUM INTO ?', (str(self.backup_path),))
            finally:
                tmp.close()
            for suf in ('', '-wal', '-shm'):
                try:
                    os.remove(str(self.db_path) + suf)
                except (FileNotFoundError, PermissionError) as e:
                    if isinstance(e, PermissionError):
                        AppLogger.warning(f'Cannot remove {self.db_path}{suf}: {e}', exc=e)
        except Exception as e:
            AppLogger.warning(f'VACUUM INTO backup failed: {e}', exc=e)
            if self.db_path.exists():
                try:
                    if self.backup_path.exists():
                        os.remove(self.backup_path)
                    shutil.copy(self.db_path, self.backup_path)
                except Exception as copy_err:
                    AppLogger.warning(f'Backup copy also failed: {copy_err}', exc=copy_err)
                for suf in ('', '-wal', '-shm'):
                    try:
                        os.remove(str(self.db_path) + suf)
                    except (FileNotFoundError, PermissionError) as rm_err:
                        if isinstance(rm_err, PermissionError):
                            AppLogger.warning(f'Cannot remove {self.db_path}{suf}: {rm_err}', exc=rm_err)
        try:
            self.start()
        except Exception as e:
            AppLogger.error(f'Failed to recreate DB at {self.db_path}: {e}', exc=e)
            raise
        AppLogger.warning(f'New DB created at: {self.db_path}')

    @profiler.profile
    def _ensure_schema(self):
        changed = self._detect_changed_tables()
        if changed:
            AppLogger.info(f'[Schema] Recreating tables: {changed}')
            self._drop_tables(changed)
        self.conn.execute('PRAGMA foreign_keys=ON')
        for _, _, sql in _TABLES:
            self.conn.execute(sql)
        self.conn.commit()
        for name, _ in reversed(_VIEWS):
            self.conn.execute(f'DROP VIEW IF EXISTS {name}')
        for _, sql in _VIEWS:
            self.conn.execute(sql)
        self.conn.commit()
        self.conn.executescript(_INDEXES_SQL)

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
        self.conn.execute('PRAGMA foreign_keys=OFF')
        for name, _, _ in reversed(_TABLES):
            if name in tables:
                self.conn.execute(f'DROP TABLE IF EXISTS {name}')
        self.conn.commit()

    @profiler.profile
    def load_existing_sources(self) -> dict[str, tuple[float, int]]:
        result: dict[str, tuple[float, int]] = {}
        try:
            cur = self.get_reader_cursor()
            cur.execute('SELECT source, modified, size FROM sources')
            for source, mtime, size in cur.fetchall():
                result[source] = (mtime, size)
            cur.close()
        except Exception as e:
            AppLogger.warning(f'Failed to load previous data from DB: {e}', exc=e)
        return result

    @profiler.profile
    def delete_sources_by_paths(self, paths: Sequence[str]):
        if not paths:
            return
        with self._write_lock:
            cur = self.get_writer_cursor()
            try:
                cur.executemany('DELETE FROM sources WHERE source = ?', [(p,) for p in paths])
                self.conn.commit()
            finally:
                cur.close()

    @profiler.profile
    def rename_paths(self, pairs: Sequence[tuple[str, str]]):
        if not pairs:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            cur.execute('PRAGMA foreign_keys=ON')
            for old, new in pairs:
                cur.execute('UPDATE sources SET source = ? WHERE source = ?', (new, old))
                cur.execute('UPDATE files SET path = ? WHERE source = ?', (new, new))
                name = os.path.basename(new)
                cur.execute(
                    "UPDATE meta_info SET value = ? WHERE path = ? AND key = 'path'",
                    (new, new),
                )
                cur.execute(
                    "UPDATE meta_info SET value = ? WHERE path = ? AND key = 'name'",
                    (name, new),
                )
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
                'INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)',
                [(h,) for h in file_hashes],
            )

    @profiler.profile
    def upsert_batches(self, source_entries, image_entries, meta_info_entries, tag_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            self._ensure_hash_indexes(cur, source_entries, tag_entries)
            cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
            if image_entries:
                cur.executemany(_SQL_UPSERT_FILES, image_entries)
            if meta_info_entries:
                cur.executemany(_SQL_UPSERT_META, meta_info_entries)
            if tag_entries:
                cur.executemany(_SQL_UPSERT_TAGS, tag_entries)
            cur.close()

    @profiler.profile
    def upsert_basic_sources(self, source_entries, image_entries, meta_info_entries=()):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            self._ensure_hash_indexes(cur, source_entries)
            cur.executemany(_SQL_UPSERT_SOURCES, source_entries)
            if image_entries:
                cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
            if meta_info_entries:
                cur.executemany(_SQL_UPSERT_META, meta_info_entries)
            cur.close()

    @profiler.profile
    def upsert_collection_results(self, image_entries, meta_info_entries, tag_entries, collector_status_entries):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            if image_entries:
                cur.executemany(_SQL_UPSERT_FILES_COALESCE, image_entries)
            if meta_info_entries:
                cur.executemany(_SQL_UPSERT_META, meta_info_entries)
            self._ensure_hash_indexes(cur, [], tag_entries)
            if tag_entries:
                cur.executemany(_SQL_UPSERT_TAGS, tag_entries)
            if collector_status_entries:
                cur.executemany(_SQL_UPSERT_COLLECTION_STATUS, collector_status_entries)
            cur.close()

    @profiler.profile
    def insert_pending_collection(self, sources, collectors):
        if not sources or not collectors:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            entries = [(s, c, 'pending', None) for s in sources for c in collectors]
            cur.executemany(
                '''INSERT INTO collection_status (source, collector, status, collected_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source, collector) DO UPDATE SET
                    status       = 'pending',
                    collected_at = NULL''',
                entries,
            )
            cur.close()


    @profiler.profile
    def get_sources_without_collector(self, collector):
        cur = self.get_reader_cursor()
        cur.execute(
            '''SELECT s.source FROM sources s
            WHERE NOT EXISTS (
                SELECT 1 FROM collection_status cs
                WHERE cs.source = s.source AND cs.collector = ?
            )''',
            (collector,),
        )
        rows = [row[0] for row in cur.fetchall()]
        cur.close()
        return rows

    @profiler.profile
    def get_pending_sources(self, collector, limit=5000):
        cur = self.get_reader_cursor()
        cur.execute(
            '''SELECT cs.source, s.modified, s.size
            FROM collection_status cs
            JOIN sources s ON s.source = cs.source
            WHERE cs.collector = ? AND cs.status = 'pending'
            LIMIT ?''',
            (collector, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return rows

    @profiler.profile
    def mark_dispatched(self, sources, collector):
        if not sources:
            return
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            for i in range(0, len(sources), 900):
                chunk = sources[i:i + 900]
                cur.executemany(
                    '''UPDATE collection_status SET status = 'dispatched'
                    WHERE source = ? AND collector = ? AND status = 'pending' ''',
                    [(s, collector) for s in chunk],
                )
            cur.close()

    @profiler.profile
    def reset_stale_dispatched(self, collectors=None):
        with self._write_lock, self.conn:
            cur = self.conn.cursor()
            if collectors:
                for c in collectors:
                    cur.execute(
                        '''UPDATE collection_status SET status = 'pending'
                        WHERE collector = ? AND status = 'dispatched' ''',
                        (c,),
                    )
            else:
                cur.execute(
                    '''UPDATE collection_status SET status = 'pending'
                    WHERE status = 'dispatched' ''',
                )
            changed = cur.execute('SELECT changes()').fetchone()[0]
            cur.close()
        if changed:
            AppLogger.info(f'[DB] Reset {changed} stale dispatched entries to pending')
        return changed

    @profiler.profile
    def purge_orphan_records(self):
        AppLogger.info('CLEANING UP DATABASE')
        try:
            with self._write_lock:
                cur = self.get_writer_cursor()

                cur.execute('''
                    DELETE FROM collection_status
                    WHERE source NOT IN (SELECT source FROM sources)
                ''')
                cur.execute('''
                    DELETE FROM meta_info
                    WHERE path NOT IN (SELECT path FROM files)
                ''')
                cur.execute('''
                    DELETE FROM tags
                    WHERE file_hash NOT IN (SELECT file_hash FROM sources);
                ''')
                cur.execute('''
                    DELETE FROM hash_index
                    WHERE file_hash NOT IN (SELECT file_hash FROM sources)
                    AND file_hash NOT IN (SELECT file_hash FROM tags);
                ''')

                self.conn.commit()

                AppLogger.info('RUNNING VACUUM')
                cur.execute('VACUUM')
                AppLogger.info('RUNNING ANALYZE')
                cur.execute('ANALYZE')
                self.conn.commit()
                self.try_checkpoint()
        except Exception as e:
            AppLogger.warning(f'DATABASE CLEANUP FAILED: {e}', exc=e)
        else:
            AppLogger.info('DATABASE CLEANUP END')

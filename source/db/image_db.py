from __future__ import annotations
import os
import shutil
import sqlite3
from pathlib import Path
from typing import Sequence

from .db_utils import apply_read_pragmas, apply_write_pragmas, connect_with_retry
from ..common.profiling import profiler
from ..common.logs import AppLogger


_TABLES = (
    ('hash_index', (),
     'CREATE TABLE IF NOT EXISTS hash_index (file_hash TEXT PRIMARY KEY)'),
    ('sources', ('hash_index',),
     '''CREATE TABLE IF NOT EXISTS sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL, created REAL, collected REAL,
        status TEXT DEFAULT NULL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )'''),
    ('images', ('sources',),
     '''CREATE TABLE IF NOT EXISTS images (
        path TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT, aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source) ON DELETE CASCADE
    )'''),
    ('meta_info', ('images',),
     '''CREATE TABLE IF NOT EXISTS meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES images(path) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
    ('tags', ('hash_index',),
     '''CREATE TABLE IF NOT EXISTS tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
    )'''),
)

_VIEWS = (
    ('images_full',
     '''CREATE VIEW images_full AS
        SELECT i.path, i.source, i.name, i.aspect_ratio,
               s.file_hash, s.size, s.modified, s.created, s.collected, s.status
        FROM images i JOIN sources s ON s.source = i.source'''),
    ('kv_all',
     '''CREATE VIEW kv_all AS
        WITH base AS (
            SELECT mi.path AS path, mi.key AS key, mi.value AS value, 'meta_info' AS src, 2 AS rank
            FROM meta_info AS mi
        UNION ALL
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
        SELECT path, key, value, src FROM picked WHERE rn = 1'''),
    ('kv_meta',
     '''CREATE VIEW kv_meta AS
        SELECT k.path, vf.file_hash, k.key, k.value, k.src
        FROM kv_all AS k JOIN images_full AS vf ON vf.path = k.path'''),
)

_INDEXES_SQL = """
    CREATE INDEX IF NOT EXISTS idx_sources_file_hash ON sources(file_hash);
    CREATE INDEX IF NOT EXISTS idx_images_source ON images(source);
    CREATE INDEX IF NOT EXISTS idx_meta_info_key_fid ON meta_info(key, path);
    CREATE INDEX IF NOT EXISTS idx_tags_key_fid ON tags(key, file_hash);
    CREATE INDEX IF NOT EXISTS idx_images_name_path ON images(name, path);
    CREATE INDEX IF NOT EXISTS idx_sources_modified_source ON sources(modified, source);
    CREATE INDEX IF NOT EXISTS idx_sources_size_source ON sources(size, source);
    CREATE INDEX IF NOT EXISTS idx_sources_created_source ON sources(created, source);
    CREATE INDEX IF NOT EXISTS idx_sources_collected_source ON sources(collected, source);
"""

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


class ImageDB:

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.backup_path = self.db_path.with_suffix('.bak')
        self.conn: sqlite3.Connection | None = None
        self.read_conn: sqlite3.Connection | None = None

    @profiler.profile
    def start(self):
        self.conn = connect_with_retry(self.db_path, timeout=3.0, check_same_thread=False)
        apply_write_pragmas(self.conn)
        uri = Path(self.db_path).resolve().as_uri()
        self.read_conn = connect_with_retry(f'{uri}?mode=ro', timeout=1.0, uri=True, check_same_thread=False)
        apply_read_pragmas(self.read_conn)

    @profiler.profile
    def exit(self):
        self.try_checkpoint()
        if self.conn:
            self.conn.close()
        if self.read_conn:
            self.read_conn.close()

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
            if self.db_path.exists():
                shutil.copy(self.db_path, self.backup_path)
                for suf in ('', '-wal', '-shm'):
                    try:
                        os.remove(str(self.db_path) + suf)
                    except FileNotFoundError:
                        pass
        self.start()
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
    def load_previous(self) -> dict[str, tuple[float, int]]:
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
        cur = self.get_writer_cursor()
        try:
            cur.executemany('DELETE FROM sources WHERE source = ?', [(p,) for p in paths])
            self.conn.commit()
        finally:
            cur.close()

    @profiler.profile
    def upsert_batches(self, source_entries, image_entries, meta_info_entries, tag_entries):
        with self.conn:
            cur = self.conn.cursor()

            file_ids = set()
            for _, fid, *_ in source_entries:
                if fid:
                    file_ids.add(fid)
            for fid, *_ in tag_entries:
                if fid:
                    file_ids.add(fid)
            if file_ids:
                cur.executemany(
                    'INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)',
                    [(fid,) for fid in file_ids],
                )

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
        AppLogger.info('CLEANING UP DATABASE')
        try:
            cur = self.get_writer_cursor()

            cur.execute('''
                DELETE FROM meta_info
                WHERE path NOT IN (SELECT path FROM images)
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

import contextlib
import json
import sqlite3
from ..common.funcs import normalize_path
from ..common.profiling import logger, profiler
from .db_utils import retry_sqlite_connection

class SettingDB:

    def __init__(self, db_name):
        self.db_name = db_name
        self._ensure_schema()

    @profiler.profile
    @contextlib.contextmanager
    def _conn(self, read_only=False):
        if read_only:
            uri = f'file:{self.db_name}?mode=ro'
            con = sqlite3.connect(uri, uri=True)
        else:
            con = retry_sqlite_connection(self.db_name)
        try:
            yield con
        except sqlite3.DatabaseError as e:
            logger.exception('SQLite error during DB operation')
            raise
        finally:
            con.close()

    @profiler.profile
    def _ensure_schema(self):
        with self._conn() as con:
            con.execute('\n                CREATE TABLE IF NOT EXISTS parent_folders (\n                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    path TEXT NOT NULL UNIQUE\n                );\n            ')
            con.execute('\n                CREATE TABLE IF NOT EXISTS ignore_folders (\n                    id INTEGER PRIMARY KEY AUTOINCREMENT,\n                    path TEXT NOT NULL UNIQUE\n                );\n            ')
            con.execute('\n                CREATE TABLE IF NOT EXISTS kv_store (\n                    key TEXT PRIMARY KEY,\n                    value TEXT NOT NULL,\n                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP\n                );\n            ')

    def _sync_folders(self, folder_type, new_paths):
        norm_paths = set((normalize_path(p) for p in new_paths))
        with self._conn() as con:
            current = {row[0] for row in con.execute(f'SELECT path FROM {folder_type}')}
            to_add = norm_paths - current
            to_remove = current - norm_paths
            with con:
                if to_add:
                    con.executemany(f'INSERT OR IGNORE INTO {folder_type}(path) VALUES (?)', ((p,) for p in to_add))
                if to_remove:
                    con.executemany(f'DELETE FROM {folder_type} WHERE path = ?', ((p,) for p in to_remove))
        return {'added': list(to_add), 'removed': list(to_remove)}

    def _add_folder(self, folder_type, path):
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute('BEGIN TRANSACTION')
            cur = con.execute(f'SELECT 1 FROM {folder_type} WHERE path = ?', (norm_path,))
            if cur.fetchone():
                con.execute('ROLLBACK')
                return False
            con.execute(f'INSERT INTO {folder_type}(path) VALUES (?)', (norm_path,))
            con.execute('COMMIT')
        return True

    def _remove_folder(self, folder_type, path):
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute('BEGIN TRANSACTION')
            cur = con.execute(f'SELECT 1 FROM {folder_type} WHERE path = ?', (norm_path,))
            if not cur.fetchone():
                con.execute('ROLLBACK')
                return False
            con.execute(f'DELETE FROM {folder_type} WHERE path = ?', (norm_path,))
            con.execute('COMMIT')
        return True

    def _get_all_folders(self, folder_type):
        with self._conn(read_only=True) as con:
            cur = con.execute(f'SELECT path FROM {folder_type} ORDER BY id ASC')
            return [row[0] for row in cur.fetchall()]

    @profiler.profile
    def sync_parent_folders(self, new_paths):
        return self._sync_folders('parent_folders', new_paths)

    @profiler.profile
    def add_parent_folder(self, path):
        return self._add_folder('parent_folders', path)

    @profiler.profile
    def remove_parent_folder(self, path):
        return self._remove_folder('parent_folders', path)

    @profiler.profile
    def get_all_parent_folders(self):
        return self._get_all_folders('parent_folders')

    @profiler.profile
    def sync_ignore_folders(self, new_paths):
        return self._sync_folders('ignore_folders', new_paths)

    @profiler.profile
    def add_ignore_folder(self, path):
        return self._add_folder('ignore_folders', path)

    @profiler.profile
    def remove_ignore_folder(self, path):
        return self._remove_folder('ignore_folders', path)

    @profiler.profile
    def get_all_ignore_folders(self):
        return self._get_all_folders('ignore_folders')

    @profiler.profile
    def set_kv(self, key, value):
        json_value = json.dumps(value, ensure_ascii=False)
        with self._conn() as con:
            con.execute('\n                INSERT INTO kv_store (key, value)\n                VALUES (?, ?)\n                ON CONFLICT(key) DO UPDATE\n                SET value = excluded.value,\n                    updated_at = CURRENT_TIMESTAMP\n            ', (key, json_value))

    @profiler.profile
    def get_kv(self, key, default=None):
        with self._conn(read_only=True) as con:
            cur = con.execute('SELECT value FROM kv_store WHERE key = ?', (key,))
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    logger.exception(f'Failed to decode JSON for key: {key}')
                    return default
            else:
                return default

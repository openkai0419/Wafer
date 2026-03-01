import contextlib
import json
import sqlite3
from afterimages.utils.paths import normalize_path
from afterimages.utils.helpers import try_json_loads
from afterimages.utils.profiling import profiler
from afterimages.utils.logs import AppLogger
from .db_utils import retry_sqlite_connection
class SettingDB:

    def __init__(self, db_name):
        self.db_name = db_name
        self._ensure_schema()

    @profiler.profile
    @contextlib.contextmanager
    def _conn(self, read_only: bool = False):
        if read_only:
            uri = f"file:{self.db_name}?mode=ro"
            con = sqlite3.connect(uri, uri=True, isolation_level=None)
            try:
                yield con
            finally:
                con.close()
            return
        con = retry_sqlite_connection(self.db_name)
        try:
            yield con
            if con.in_transaction:
                con.commit()
        except Exception as e:
            if con.in_transaction:
                try:
                    con.rollback()
                except Exception:
                    pass
            AppLogger.error(f"SQLite error during DB operation: {e}", exc=e)
            raise
        finally:
            con.close()

    @profiler.profile
    def _ensure_schema(self):
        with self._conn() as con:
            con.execute('''
                CREATE TABLE IF NOT EXISTS parent_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE
                );
            ''')
            con.execute('''
                CREATE TABLE IF NOT EXISTS ignore_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE
                );
            ''')
            con.execute('''
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            ''')

    def _sync_folders(self, folder_type, new_paths):
        norm_paths = set((normalize_path(p) for p in new_paths))
        with self._conn() as con:
            current = {row[0] for row in con.execute(f'SELECT path FROM {folder_type}')}
            to_add = norm_paths - current
            to_remove = current - norm_paths
            if to_add:
                con.executemany(f'INSERT OR IGNORE INTO {folder_type}(path) VALUES (?)', ((p,) for p in to_add))
            if to_remove:
                con.executemany(f'DELETE FROM {folder_type} WHERE path = ?', ((p,) for p in to_remove))
        return {'added': list(to_add), 'removed': list(to_remove)}

    def _add_folder(self, folder_type, path):
        norm_path = normalize_path(path)
        with self._conn() as con:
            cur = con.execute(f'SELECT 1 FROM {folder_type} WHERE path = ?', (norm_path,))
            if cur.fetchone():
                return False
            con.execute(f'INSERT INTO {folder_type}(path) VALUES (?)', (norm_path,))
        return True

    def _remove_folder(self, folder_type, path):
        norm_path = normalize_path(path)
        with self._conn() as con:
            cur = con.execute(f'SELECT 1 FROM {folder_type} WHERE path = ?', (norm_path,))
            if not cur.fetchone():
                return False
            con.execute(f'DELETE FROM {folder_type} WHERE path = ?', (norm_path,))
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
    def set_setting(self, key, value):
        json_value = json.dumps(value, ensure_ascii=False)
        with self._conn() as con:
            con.execute('''
                INSERT INTO kv_store (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            ''', (key, json_value))

    @profiler.profile
    def get_setting(self, key, default=None):
        with self._conn(read_only=True) as con:
            cur = con.execute('SELECT value FROM kv_store WHERE key = ?', (key,))
            row = cur.fetchone()
            if not row:
                return default
            return try_json_loads(row[0], default, on_error=lambda _e: AppLogger.warning(f'Failed to decode JSON for key: {key}'))

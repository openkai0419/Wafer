import contextlib
import json
import sqlite3
from ..common.paths import normalize_path
from ..common.helpers import try_json_loads
from ..profiling import profiler
from ..logs import AppLogger
from .db_utils import connect_with_retry

_ENTRY_TABLE_COLUMNS = {
    "parent_folders": "path",
    "ignore_folders": "path",
    "ignore_patterns": "pattern",
}


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
        con = connect_with_retry(self.db_name, timeout=3.0, retries=30, delay=0.1)
        con.execute("PRAGMA foreign_keys=ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
            if con.in_transaction:
                con.commit()
        except Exception as e:
            if con.in_transaction:
                try:
                    con.rollback()
                except Exception as re:
                    AppLogger.debug(f"rollback failed: {re}")
            AppLogger.error(f"SQLite error during DB operation: {e}", exc=e)
            raise
        finally:
            con.close()

    @profiler.profile
    def _ensure_schema(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS parent_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE
                );
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS ignore_folders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    path TEXT NOT NULL UNIQUE
                );
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS ignore_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern TEXT NOT NULL UNIQUE
                );
            """)
            con.execute("""
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def _validate_table(self, table):
        column = _ENTRY_TABLE_COLUMNS.get(table)
        if column is None:
            raise ValueError(f"Invalid folder type: {table}")
        return column

    def _normalize_entry(self, column, value):
        return normalize_path(value) if column == "path" else value.strip().replace("\\", "/")

    def _sync_folders(self, table, new_values):
        column = self._validate_table(table)
        norm_values = {self._normalize_entry(column, v) for v in new_values if v and v.strip()}
        with self._conn() as con:
            current = {row[0] for row in con.execute(f"SELECT {column} FROM {table}")}
            to_add = norm_values - current
            to_remove = current - norm_values
            if to_add:
                con.executemany(f"INSERT OR IGNORE INTO {table}({column}) VALUES (?)", ((v,) for v in to_add))
            if to_remove:
                con.executemany(f"DELETE FROM {table} WHERE {column} = ?", ((v,) for v in to_remove))
        return {"added": list(to_add), "removed": list(to_remove)}

    def _add_folder(self, table, value):
        column = self._validate_table(table)
        norm_value = self._normalize_entry(column, value)
        if not norm_value:
            return False
        with self._conn() as con:
            cur = con.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (norm_value,))
            if cur.fetchone():
                return False
            con.execute(f"INSERT INTO {table}({column}) VALUES (?)", (norm_value,))
        return True

    def _remove_folder(self, table, value):
        column = self._validate_table(table)
        norm_value = self._normalize_entry(column, value)
        with self._conn() as con:
            cur = con.execute(f"SELECT 1 FROM {table} WHERE {column} = ?", (norm_value,))
            if not cur.fetchone():
                return False
            con.execute(f"DELETE FROM {table} WHERE {column} = ?", (norm_value,))
        return True

    def _get_all_folders(self, table):
        column = self._validate_table(table)
        with self._conn(read_only=True) as con:
            cur = con.execute(f"SELECT {column} FROM {table} ORDER BY id ASC")
            return [row[0] for row in cur.fetchall()]

    @profiler.profile
    def sync_parent_folders(self, new_paths):
        return self._sync_folders("parent_folders", new_paths)

    @profiler.profile
    def add_parent_folder(self, path):
        return self._add_folder("parent_folders", path)

    @profiler.profile
    def remove_parent_folder(self, path):
        return self._remove_folder("parent_folders", path)

    @profiler.profile
    def get_all_parent_folders(self):
        return self._get_all_folders("parent_folders")

    @profiler.profile
    def sync_ignore_folders(self, new_paths):
        return self._sync_folders("ignore_folders", new_paths)

    @profiler.profile
    def add_ignore_folder(self, path):
        return self._add_folder("ignore_folders", path)

    @profiler.profile
    def remove_ignore_folder(self, path):
        return self._remove_folder("ignore_folders", path)

    @profiler.profile
    def get_all_ignore_folders(self):
        return self._get_all_folders("ignore_folders")

    @profiler.profile
    def sync_ignore_patterns(self, new_patterns):
        return self._sync_folders("ignore_patterns", new_patterns)

    @profiler.profile
    def add_ignore_pattern(self, pattern):
        return self._add_folder("ignore_patterns", pattern)

    @profiler.profile
    def remove_ignore_pattern(self, pattern):
        return self._remove_folder("ignore_patterns", pattern)

    @profiler.profile
    def get_all_ignore_patterns(self):
        return self._get_all_folders("ignore_patterns")

    @profiler.profile
    def set_setting(self, key, value):
        json_value = json.dumps(value, ensure_ascii=False)
        with self._conn() as con:
            con.execute(
                """
                INSERT INTO kv_store (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """,
                (key, json_value),
            )

    @profiler.profile
    def get_setting(self, key, default=None):
        with self._conn(read_only=True) as con:
            cur = con.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = cur.fetchone()
            if not row:
                return default
            return try_json_loads(row[0], default, on_error=lambda _e: AppLogger.warning(f"Failed to decode JSON for key: {key}"))

    def get_enabled_collectors(self) -> list[str] | None:
        val = self.get_setting("enabled_collectors")
        if val is None:
            return None
        if not isinstance(val, list):
            return None
        return val

    def set_enabled_collectors(self, names: list[str]):
        self.set_setting("enabled_collectors", list(names))

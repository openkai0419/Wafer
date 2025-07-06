import sqlite3
import contextlib
import json
from typing import List, Dict

from ..profiling import logger, profiler
from ..common import normalize_path
from .db_utils import retry_sqlite_connection


class SettingDB:
    def __init__(self, db_name: str):
        self.db_name = db_name
        self._ensure_schema()

    @profiler.profile
    @contextlib.contextmanager
    def _conn(self, read_only: bool = False):
        if read_only:
            uri = f'file:{self.db_name}?mode=ro'
            con = sqlite3.connect(uri, uri=True)
        else:
            con = retry_sqlite_connection(self.db_name)

        try:
            yield con
        except sqlite3.DatabaseError as e:
            logger.exception("SQLite error during DB operation")
            raise
        finally:
            con.close()

    @profiler.profile
    def _ensure_schema(self):
        # create schema only if it does not exist
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
                CREATE TABLE IF NOT EXISTS kv_store (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    # ----- common helpers -----
    def _sync_folders(self, folder_type: str, new_paths: List[str]) -> Dict[str, List[str]]:
        norm_paths = set(normalize_path(p) for p in new_paths)
        with self._conn() as con:
            current = {row[0] for row in con.execute(f"SELECT path FROM {folder_type}")}

            to_add = norm_paths - current
            to_remove = current - norm_paths

            with con:  # explicit transaction
                if to_add:
                    con.executemany(f"INSERT OR IGNORE INTO {folder_type}(path) VALUES (?)",
                                    ((p,) for p in to_add))
                if to_remove:
                    con.executemany(f"DELETE FROM {folder_type} WHERE path = ?",
                                    ((p,) for p in to_remove))

        return {
            "added": list(to_add),
            "removed": list(to_remove)
        }

    def _add_folder(self, folder_type: str, path: str) -> bool:
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute("BEGIN TRANSACTION")  # start transaction
            cur = con.execute(f"SELECT 1 FROM {folder_type} WHERE path = ?", (norm_path,))
            if cur.fetchone():
                con.execute("ROLLBACK")  # rollback if already exists
                return False
            con.execute(f"INSERT INTO {folder_type}(path) VALUES (?)", (norm_path,))
            con.execute("COMMIT")  # commit after insert
        return True

    def _remove_folder(self, folder_type: str, path: str) -> bool:
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute("BEGIN TRANSACTION")  # start transaction
            cur = con.execute(f"SELECT 1 FROM {folder_type} WHERE path = ?", (norm_path,))
            if not cur.fetchone():
                con.execute("ROLLBACK")  # rollback if missing
                return False
            con.execute(f"DELETE FROM {folder_type} WHERE path = ?", (norm_path,))
            con.execute("COMMIT")  # commit after delete
        return True

    def _get_all_folders(self, folder_type: str) -> List[str]:
        with self._conn(read_only=True) as con:
            cur = con.execute(f"SELECT path FROM {folder_type} ORDER BY id ASC")
            return [row[0] for row in cur.fetchall()]

    # ───── Parent Folder ─────
    @profiler.profile
    def sync_parent_folders(self, new_paths: List[str]) -> Dict[str, List[str]]:
        return self._sync_folders('parent_folders', new_paths)

    @profiler.profile
    def add_parent_folder(self, path: str) -> bool:
        return self._add_folder('parent_folders', path)

    @profiler.profile
    def remove_parent_folder(self, path: str) -> bool:
        return self._remove_folder('parent_folders', path)

    @profiler.profile
    def get_all_parent_folders(self) -> List[str]:
        return self._get_all_folders('parent_folders')

    # ───── Ignore Folder ─────
    @profiler.profile
    def sync_ignore_folders(self, new_paths: List[str]) -> Dict[str, List[str]]:
        return self._sync_folders('ignore_folders', new_paths)

    @profiler.profile
    def add_ignore_folder(self, path: str) -> bool:
        return self._add_folder('ignore_folders', path)

    @profiler.profile
    def remove_ignore_folder(self, path: str) -> bool:
        return self._remove_folder('ignore_folders', path)

    @profiler.profile
    def get_all_ignore_folders(self) -> List[str]:
        return self._get_all_folders('ignore_folders')

    # ───── Key-Value Store ─────
    @profiler.profile
    def set_kv(self, key: str, value):
        """Serialize value to JSON and save it under key."""
        json_value = json.dumps(value, ensure_ascii=False)
        with self._conn() as con:
            con.execute("""
                INSERT INTO kv_store (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, json_value))

    @profiler.profile
    def get_kv(self, key: str, default=None):
        """Retrieve value for key and decode JSON."""
        with self._conn(read_only=True) as con:
            cur = con.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = cur.fetchone()
            if row:
                try:
                    return json.loads(row[0])
                except json.JSONDecodeError:
                    logger.exception(f"Failed to decode JSON for key: {key}")
                    return default
            else:
                return default
    
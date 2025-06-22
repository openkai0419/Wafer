# folder_db.py
import sqlite3
import os
import contextlib
from typing import List, Dict
from ..constants import setting_db

def normalize_path(path: str) -> str:
    return os.path.abspath(os.path.normpath(path))

class FolderDB:
    def __init__(self, db_name: str = setting_db):
        self.db_name = db_name
        self._ensure_schema()

    @contextlib.contextmanager
    def _conn(self):
        con = sqlite3.connect(self.db_name, isolation_level=None)
        con.execute("PRAGMA foreign_keys = ON")
        con.execute("PRAGMA journal_mode=WAL")
        try:
            yield con
        finally:
            con.close()

    def _ensure_schema(self):
        with self._conn() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS parent_folders (
                    id   INTEGER PRIMARY KEY AUTOINCREMENT,
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

    # ───── Parent Folder ─────
    def sync_parent_folders(self, new_paths: List[str]) -> Dict[str, List[str]]:
        norm_paths = set(normalize_path(p) for p in new_paths)
        with self._conn() as con:
            cur = con.execute("SELECT path FROM parent_folders")
            current = set(row[0] for row in cur.fetchall())

            to_add = norm_paths - current
            to_remove = current - norm_paths

            con.executemany("INSERT OR IGNORE INTO parent_folders(path) VALUES (?)",
                            ((p,) for p in to_add))
            con.executemany("DELETE FROM parent_folders WHERE path = ?",
                            ((p,) for p in to_remove))

        return {
            "added": list(to_add),
            "removed": list(to_remove)
        }

    def get_all_parent_folders(self) -> List[str]:
        with self._conn() as con:
            cur = con.execute("SELECT path FROM parent_folders ORDER BY id ASC")
            return [row[0] for row in cur.fetchall()]

    # ───── Key-Value Store ─────
    def set_kv(self, key: str, value: str):
        with self._conn() as con:
            con.execute("""
                INSERT INTO kv_store (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, str(value)))

    def get_kv(self, key: str, default: str = None) -> str:
        with self._conn() as con:
            cur = con.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default

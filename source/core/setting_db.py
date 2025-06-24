import sqlite3
import os
import contextlib
import time
from typing import List, Dict

from ..constants import setting_db_name
from ..profiling import init_env
logger, profiler = init_env()

def normalize_path(path: str) -> str:
    return os.path.abspath(os.path.normpath(path))

@profiler.profile
def retry_sqlite_connection(db_name: str, timeout: float = 3.0, interval: float = 0.1):
    start_time = time.time()
    last_exception = None
    while time.time() - start_time < timeout:
        try:
            con = sqlite3.connect(db_name, isolation_level=None)
            con.execute("PRAGMA foreign_keys = ON")
            con.execute("PRAGMA journal_mode=WAL")
            return con
        except sqlite3.OperationalError as e:
            last_exception = e
            logger.warning(f"SQLite connection failed, retrying... ({e})")
            time.sleep(interval)
    logger.error(f"Could not acquire DB write connection within {timeout:.1f}s")
    raise TimeoutError(f"Could not acquire DB write connection within {timeout:.1f}s") from last_exception

class SettingDB:
    def __init__(self, db_name: str = setting_db_name):
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
        # スキーマがまだ存在しない場合にのみ作成
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

    # ───── 共通処理 ─────
    def _sync_folders(self, folder_type: str, new_paths: List[str]) -> Dict[str, List[str]]:
        """ parent_folders と ignore_folders の追加、削除処理を共通化 """
        norm_paths = set(normalize_path(p) for p in new_paths)
        with self._conn() as con:
            current = {row[0] for row in con.execute(f"SELECT path FROM {folder_type}")}

            to_add = norm_paths - current
            to_remove = current - norm_paths

            with con:  # トランザクションを明示
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
        """ parent_folders と ignore_folders に追加する処理を共通化 """
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute("BEGIN TRANSACTION")  # トランザクション開始
            cur = con.execute(f"SELECT 1 FROM {folder_type} WHERE path = ?", (norm_path,))
            if cur.fetchone():
                con.execute("ROLLBACK")  # すでに存在する場合はロールバック
                return False
            con.execute(f"INSERT INTO {folder_type}(path) VALUES (?)", (norm_path,))
            con.execute("COMMIT")  # 挿入後コミット
        return True

    def _remove_folder(self, folder_type: str, path: str) -> bool:
        """ parent_folders と ignore_folders から削除する処理を共通化 """
        norm_path = normalize_path(path)
        with self._conn() as con:
            con.execute("BEGIN TRANSACTION")  # トランザクション開始
            cur = con.execute(f"SELECT 1 FROM {folder_type} WHERE path = ?", (norm_path,))
            if not cur.fetchone():
                con.execute("ROLLBACK")  # 存在しない場合はロールバック
                return False
            con.execute(f"DELETE FROM {folder_type} WHERE path = ?", (norm_path,))
            con.execute("COMMIT")  # 削除後コミット
        return True

    def _get_all_folders(self, folder_type: str) -> List[str]:
        """ parent_folders と ignore_folders から全てのパスを取得する処理を共通化 """
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
    def set_kv(self, key: str, value: str):
        with self._conn() as con:
            con.execute("""
                INSERT INTO kv_store (key, value)
                VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE
                SET value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
            """, (key, str(value)))

    @profiler.profile
    def get_kv(self, key: str, default: str = None) -> str:
        with self._conn(read_only=True) as con:
            cur = con.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else default

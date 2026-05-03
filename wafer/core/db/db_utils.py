import errno
import glob
import os
import sqlite3
import stat
import time
from pathlib import Path
from collections.abc import Sequence

from ...utils.paths import data_db_path, list_data_db_names, list_setting_db_names
from ...utils.hashes import fast_signature_hash
from ...utils.profiling import profiler
from ...utils.logs import AppLogger


def apply_write_pragmas(conn: sqlite3.Connection):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA locking_mode=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")


def apply_read_pragmas(conn: sqlite3.Connection):
    conn.execute("PRAGMA query_only=ON")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-50000")
    conn.execute("PRAGMA mmap_size=536870912")
    conn.execute("PRAGMA foreign_keys=ON")


@profiler.profile
def connect_with_retry(path, timeout=3.0, retries=3, delay=1.0, **kwargs):
    last_exception = None
    for attempt in range(retries):
        try:
            return sqlite3.connect(path, timeout=timeout, **kwargs)
        except sqlite3.OperationalError as e:
            last_exception = e
            AppLogger.warning(f"[connect_with_retry] Attempt {attempt + 1} failed: {e}")
            time.sleep(delay)
        except Exception as e:
            AppLogger.error(f"[connect_with_retry] Unexpected error: {e}", exc=e)
            raise
    AppLogger.error("[connect_with_retry] All attempts failed.", exc=last_exception)
    raise last_exception


@profiler.profile
def delete_database_files(dbname, retries=10, delay=1.0, force=False):
    base = os.path.abspath(dbname)
    AppLogger.info(f"Deleting database files: {base}")
    patterns = [base, f"{base}-journal", f"{base}-wal", f"{base}-shm"] + glob.glob(f"{base}*")
    targets = {p for p in patterns if os.path.isfile(p)}
    if not targets:
        AppLogger.info("No database files found to delete.")
        return True

    def remove(path):
        try:
            os.remove(path)
            AppLogger.info(f"Deleted: {path}")
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError) as e:
            if getattr(e, "errno", None) not in (None, errno.EACCES, errno.EBUSY):
                AppLogger.error(f"Unexpected error on {path}: {e}", exc=e)
            else:
                AppLogger.warning(f"Failed to delete {path}: {e}")
            if force:
                try:
                    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
                    os.remove(path)
                    AppLogger.info(f"Force-deleted: {path}")
                    return True
                except Exception as fe:
                    AppLogger.warning(f"Force delete failed on {path}: {fe}")
            return False

    for attempt in range(1, retries + 1):
        remaining = {p for p in targets if not remove(p)}
        if not remaining:
            AppLogger.info("All database files deleted successfully.")
            return True
        AppLogger.info(f"Retry {attempt}/{retries} in {delay:.1f}s… (remaining: {remaining})")
        time.sleep(delay)
    AppLogger.warning(f"Failed to delete DB files after {retries} attempts: {remaining}")
    return False


def escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def build_like_condition(field: str, keywords: list[str] | tuple[str, ...], op: str, query_mode: str = "LIKE") -> tuple[str, list[str]]:
    if not keywords:
        return "", []
    if query_mode.upper() == "GLOB":
        clauses = [f"{field} GLOB ?" for _ in keywords]
        values = [f"*{kw}*" for kw in keywords]
    else:
        clauses = [f"{field} LIKE ? ESCAPE '\\'" for _ in keywords]
        values = [f"%{escape_like(kw)}%" for kw in keywords]
    return f" {op} ".join(clauses), values


def build_basic_entries(paths: Sequence[str], file_info: dict, aspect_map: dict, now: float):
    source_entries = []
    file_entries = []
    for p in paths:
        mtime, fsize, ctime = file_info.get(p, (0.0, 0, 0.0))
        file_hash = fast_signature_hash(p, fsize, 256)
        source_entries.append((p, file_hash, fsize, mtime, ctime, now))
        file_entries.append((p, p, Path(p).name, aspect_map.get(p, 1.0), None))
    return source_entries, file_entries


def remove_orphan_databases():
    AppLogger.info("CLEAN DATABASES")
    settings = set(list_setting_db_names())
    AppLogger.info(settings)
    datas = set(list_data_db_names())
    AppLogger.info(datas)
    diff = datas - settings
    AppLogger.info(f"[DIFF] {diff}")
    for d in diff:
        delete_database_files(data_db_path(d))

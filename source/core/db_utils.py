import sqlite3
import os
import time
import glob
import errno
import stat

from ..common import get_data_file_names, get_setting_file_names, get_data_db
from ..profiling import logger, profiler

@profiler.profile
def connect_with_retry(path, timeout: float = 3.0, retries: int = 3, delay: float = 1.0, **kwargs):
    """Connect to SQLite with retry logic."""
    last_exception = None
    for attempt in range(retries):
        try:
            return sqlite3.connect(path, timeout=timeout, **kwargs)
        except sqlite3.OperationalError as e:
            last_exception = e
            logger.warning(f"[connect_with_retry] Attempt {attempt + 1} failed: {e}")
            time.sleep(delay)
        except Exception as e:
            logger.error(f"[connect_with_retry] Unexpected error: {e}")
            raise
    logger.error("[connect_with_retry] All attempts failed. Raising last exception.")
    raise last_exception

@profiler.profile
def retry_sqlite_connection(db_name: str, timeout: float = 3.0, interval: float = 0.1):
    """Connect to SQLite with WAL and foreign key pragmas."""
    retries = max(1, int(timeout / interval)) if interval > 0 else 1
    conn = connect_with_retry(
        db_name,
        timeout=timeout,
        retries=retries,
        delay=interval,
        isolation_level=None,
    )
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

@profiler.profile
def delete_database_files(dbname: str, retries: int = 1000, delay: float = 1.0, force: bool = False) -> bool:
    """
    指定された DB 名のファイルおよび関連ファイルを削除する。
    他プロセスが開いている場合はリトライする。
    `force=True` なら属性を変更して強制削除を試みる。
    成功すれば True、失敗すれば False。
    """
    base = os.path.abspath(dbname)
    logger.info(f"Deleting database files: {base}")

    patterns = [base, f"{base}-journal", f"{base}-wal", f"{base}-shm"] + glob.glob(f"{base}*")
    targets = {p for p in patterns if os.path.isfile(p)}

    if not targets:
        logger.info("No database files found to delete.")
        return True

    def remove(path: str) -> bool:
        try:
            os.remove(path)
            logger.info(f"Deleted: {path}")
            return True
        except FileNotFoundError:
            return True
        except (PermissionError, OSError) as e:
            if getattr(e, "errno", None) not in (None, errno.EACCES, errno.EBUSY):
                logger.exception(f"Unexpected error on {path}")
                raise
            logger.warning(f"Failed to delete {path}: {e}")
            if force:
                try:
                    os.chmod(path, os.stat(path).st_mode | stat.S_IWUSR)
                    os.remove(path)
                    logger.info(f"Force-deleted: {path}")
                    return True
                except Exception as fe:
                    logger.error(f"Force delete failed on {path}: {fe}")
            return False

    for attempt in range(1, retries + 1):
        remaining = {p for p in targets if not remove(p)}
        if not remaining:
            logger.info("All database files deleted successfully.")
            return True
        logger.info(f"Retry {attempt}/{retries} in {delay:.1f}s… (remaining: {remaining})")
        time.sleep(delay)

    logger.error(f"Failed to delete DB files after {retries} attempts: {remaining}")
    return False

def clean_database():
    logger.info("CLEAN DATABASES")
    settings = set(get_setting_file_names())
    logger.info(settings)
    datas = set(get_data_file_names())
    logger.info(datas)
    diff = datas - settings
    logger.info(f"[DIFF] {diff}")
    for d in diff:
        delete_database_files(get_data_db(d))
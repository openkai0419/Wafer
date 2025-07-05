import sqlite3
import time
import os
import glob
import errno

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
def delete_database_files(dbname, retries: int = 1000, delay: float = 1) -> bool:
    """
    このインスタンスのDBファイルおよび関連ファイルを削除する。
    他プロセスが開いている場合はリトライする。

    成功すれば True、失敗すれば False。
    """
    base = os.path.abspath(dbname)
    logger.info(base)
    patterns = [
        base,
        base + "-journal",
        base + "-wal",
        base + "-shm",
    ]
    # 念のため類似ファイルも削除候補に
    patterns.extend(glob.glob(base + "*"))
    targets = {path for path in patterns if os.path.isfile(path)}

    for attempt in range(1, retries + 1):
        still_exists = set()
        for path in targets:
            try:
                os.remove(path)
                logger.info(f"Deleted: {path}")
            except FileNotFoundError:
                continue  # もう無いならOK
            except PermissionError as e:
                logger.warning(f"PermissionError on {path} (attempt {attempt})")
                still_exists.add(path)
            except OSError as e:
                if e.errno in (errno.EACCES, errno.EBUSY):
                    logger.warning(f"OSError on {path} (attempt {attempt}): {e}")
                    still_exists.add(path)
                else:
                    logger.exception(f"Unexpected OSError on {path}")
                    return False

        if not still_exists:
            logger.info("All database files deleted successfully.")
            return True

        logger.info(f"Retrying in {delay:.1f}s… (remaining: {still_exists})")
        time.sleep(delay)

    logger.error(f"Failed to delete DB files after {retries} attempts: {still_exists}")
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
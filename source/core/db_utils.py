import sqlite3
import time

from ..profiling import init_env
logger, profiler = init_env()

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

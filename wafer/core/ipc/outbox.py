from __future__ import annotations
import os
import sqlite3
import threading
import time
from collections.abc import Iterable
from pathlib import Path
from typing import Any, NamedTuple

import msgpack
import psutil

from ..common.paths import resolve_data_path
from ..logs import AppLogger

_OUTBOX_DIR = resolve_data_path(".outbox/")
OUTBOX_MAX_AGE_DAYS = 30
OUTBOX_CLEANUP_INTERVAL = 600.0
_DB_SUFFIXES = ("", "-wal", "-shm")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic      TEXT    NOT NULL,
    payload    BLOB    NOT NULL,
    dst        TEXT    NOT NULL,
    db         TEXT    DEFAULT '',
    created_at REAL    NOT NULL
)
"""


def _extract_pid(node_id: str) -> int | None:
    parts = node_id.rsplit("-", 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def _created_at(path: str) -> float:
    try:
        st = os.stat(path)
    except OSError:
        return 0.0
    return getattr(st, "st_birthtime", st.st_ctime)


def owner_alive(db_path: str) -> bool:
    pid = _extract_pid(Path(db_path).stem)
    if pid is None:
        return False
    try:
        started = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        return False
    except psutil.AccessDenied:
        return True
    return started <= _created_at(db_path)


def _delete_db_files(db_path: str):
    for suffix in _DB_SUFFIXES:
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass
        except PermissionError:
            AppLogger.debug(f"outbox file busy, skipping: {db_path}{suffix}")
        except Exception as e:
            AppLogger.warning(f"outbox file delete failed: {db_path}{suffix}", exc=e)


def _connect(path: str) -> sqlite3.Connection:
    return sqlite3.connect(path, timeout=5.0, check_same_thread=False)


class OutboxRecord(NamedTuple):
    id: int
    topic: str
    payload: Any
    dst: str
    db: str
    created_at: float
    source_db: str


class OutboxStore:
    def __init__(self, node_id: str):
        self._path = os.path.join(_OUTBOX_DIR, f"{node_id}.db")
        self._lock = threading.Lock()
        self._conn = self._open(self._path)

    @staticmethod
    def _open(path: str) -> sqlite3.Connection:
        conn = _connect(path)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute(_SCHEMA)
            conn.commit()
        except sqlite3.Error:
            conn.close()
            raise
        return conn

    def push(self, topic: str, payload: Any, dst: str, db: str = "") -> int:
        blob = msgpack.packb(payload, use_bin_type=True)
        with self._lock, self._conn:
            cur = self._conn.execute(
                "INSERT INTO outbox (topic, payload, dst, db, created_at) VALUES (?, ?, ?, ?, ?)",
                (topic, blob, dst, db, time.time()),
            )
            return cur.lastrowid

    def remove(self, record_id: int):
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM outbox WHERE id = ?", (record_id,))

    def remove_batch(self, record_ids: list[int]):
        if not record_ids:
            return
        with self._lock, self._conn:
            self._conn.executemany("DELETE FROM outbox WHERE id = ?", [(rid,) for rid in record_ids])

    def pending(self) -> list[OutboxRecord]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, topic, payload, dst, db, created_at FROM outbox ORDER BY id",
            ).fetchall()
        return [
            OutboxRecord(
                id=r[0],
                topic=r[1],
                payload=msgpack.unpackb(r[2], raw=False),
                dst=r[3],
                db=r[4],
                created_at=r[5],
                source_db=self._path,
            )
            for r in rows
        ]

    def has_pending(self, topic: str, dst: str) -> bool:
        with self._lock:
            row = self._conn.execute("SELECT 1 FROM outbox WHERE topic = ? AND dst = ? LIMIT 1", (topic, dst)).fetchone()
        return row is not None

    def close(self):
        try:
            self._conn.close()
        except Exception as e:
            AppLogger.debug(f"OutboxStore.close failed: {e}")

    def delete_if_empty(self) -> bool:
        count = self._conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
        if count > 0:
            return False
        self.close()
        _delete_db_files(self._path)
        return True


def _has_outbox_table(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='outbox'").fetchone() is not None


def _drop_expired_rows(db_path: str, cutoff: float) -> int:
    conn = _connect(db_path)
    try:
        if not _has_outbox_table(conn):
            return 0
        removed = conn.execute("DELETE FROM outbox WHERE created_at < ?", (cutoff,)).rowcount
        conn.commit()
        if removed:
            AppLogger.info(f"outbox: dropped {removed} undelivered messages older than {OUTBOX_MAX_AGE_DAYS} days from {Path(db_path).name}")
        return conn.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]
    finally:
        conn.close()


def cleanup_dead_outbox_files():
    outbox_dir = Path(_OUTBOX_DIR)
    if not outbox_dir.is_dir():
        return
    cutoff = time.time() - OUTBOX_MAX_AGE_DAYS * 86400
    for db_file in outbox_dir.glob("*.db"):
        db_path = str(db_file)
        if owner_alive(db_path):
            continue
        try:
            remaining = _drop_expired_rows(db_path, cutoff)
        except sqlite3.OperationalError as e:
            AppLogger.debug(f"outbox file busy, skipping: {db_path} ({e})")
            continue
        except sqlite3.DatabaseError:
            _delete_db_files(db_path)
            continue
        if remaining == 0:
            _delete_db_files(db_path)


class DeadOutboxCleaner:
    def __init__(self, interval: float = OUTBOX_CLEANUP_INTERVAL):
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="outbox-cleaner", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=5.0)

    def _run(self):
        while not self._stop.is_set():
            try:
                cleanup_dead_outbox_files()
            except Exception as e:
                AppLogger.warning("outbox cleanup failed; it runs again later", exc=e)
            self._stop.wait(self._interval)


def _read_records(db_path: str, dst_filter: set[str] | None, db_filter: str | None) -> list[OutboxRecord]:
    records: list[OutboxRecord] = []
    conditions, params = [], []
    if dst_filter:
        conditions.append(f"dst IN ({','.join('?' * len(dst_filter))})")
        params.extend(dst_filter)
    if db_filter is not None:
        conditions.append("db = ?")
        params.append(db_filter)
    where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
    try:
        conn = _connect(db_path)
        try:
            if not _has_outbox_table(conn):
                return records
            rows = conn.execute(f"SELECT id, topic, payload, dst, db, created_at FROM outbox{where} ORDER BY id", params).fetchall()
            for r in rows:
                records.append(
                    OutboxRecord(
                        id=r[0],
                        topic=r[1],
                        payload=msgpack.unpackb(r[2], raw=False),
                        dst=r[3],
                        db=r[4],
                        created_at=r[5],
                        source_db=db_path,
                    )
                )
        finally:
            conn.close()
    except Exception as e:
        AppLogger.warning(f"outbox read failed: {db_path}", exc=e)
    return records


def scan_all_outbox(dst_filter: set[str] | None = None, db_filter: str | None = None) -> list[OutboxRecord]:
    outbox_dir = Path(_OUTBOX_DIR)
    if not outbox_dir.is_dir():
        return []
    return [record for db_file in outbox_dir.glob("*.db") for record in _read_records(str(db_file), dst_filter, db_filter)]


def read_outbox_of(node_ids: Iterable[str], dst_filter: set[str] | None = None, db_filter: str | None = None) -> list[OutboxRecord]:
    records: list[OutboxRecord] = []
    for node_id in node_ids:
        db_path = os.path.join(_OUTBOX_DIR, f"{os.path.basename(node_id)}.db")
        if os.path.exists(db_path):
            records.extend(_read_records(db_path, dst_filter, db_filter))
    return records


def remove_outbox_batch_from(db_path: str, record_ids: list[int]):
    if not record_ids:
        return
    try:
        conn = _connect(db_path)
        try:
            conn.executemany("DELETE FROM outbox WHERE id = ?", [(rid,) for rid in record_ids])
            conn.commit()
        finally:
            conn.close()
    except Exception as e:
        AppLogger.warning(f"outbox remove_batch_from failed: {db_path}", exc=e)

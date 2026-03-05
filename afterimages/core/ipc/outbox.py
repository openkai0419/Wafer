from __future__ import annotations
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, NamedTuple

import msgpack
import psutil

from afterimages.utils.paths import resolve_data_path
from afterimages.utils.logs import AppLogger
_OUTBOX_DIR = resolve_data_path('.outbox/')

_SCHEMA = '''
CREATE TABLE IF NOT EXISTS outbox (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    topic      TEXT    NOT NULL,
    payload    BLOB    NOT NULL,
    dst        TEXT    NOT NULL,
    db         TEXT    DEFAULT '',
    created_at REAL    NOT NULL
)
'''


def _extract_pid(node_id: str) -> int | None:
    parts = node_id.rsplit('-', 1)
    if len(parts) == 2 and parts[1].isdigit():
        return int(parts[1])
    return None


def _delete_db_files(db_path: str):
    for suffix in ('', '-wal', '-shm'):
        try:
            os.remove(db_path + suffix)
        except FileNotFoundError:
            pass
        except Exception as e:
            AppLogger.warning(f'outbox file delete failed: {db_path}{suffix}', exc=e)


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5.0, check_same_thread=False)
    conn.execute('PRAGMA journal_mode=WAL')
    return conn


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
        self._path = os.path.join(_OUTBOX_DIR, f'{node_id}.db')
        self._conn = self._open(self._path)

    @staticmethod
    def _open(path: str) -> sqlite3.Connection:
        conn = _connect(path)
        conn.execute('PRAGMA synchronous=NORMAL')
        conn.execute(_SCHEMA)
        conn.commit()
        return conn

    def push(self, topic: str, payload: Any, dst: str, db: str = '') -> int:
        blob = msgpack.packb(payload, use_bin_type=True)
        cur = self._conn.execute(
            'INSERT INTO outbox (topic, payload, dst, db, created_at) VALUES (?, ?, ?, ?, ?)',
            (topic, blob, dst, db, time.time()),
        )
        self._conn.commit()
        return cur.lastrowid

    def remove(self, record_id: int):
        self._conn.execute('DELETE FROM outbox WHERE id = ?', (record_id,))
        self._conn.commit()

    def remove_batch(self, record_ids: list[int]):
        if not record_ids:
            return
        self._conn.executemany('DELETE FROM outbox WHERE id = ?', [(rid,) for rid in record_ids])
        self._conn.commit()

    def pending(self) -> list[OutboxRecord]:
        rows = self._conn.execute(
            'SELECT id, topic, payload, dst, db, created_at FROM outbox ORDER BY id',
        ).fetchall()
        return [
            OutboxRecord(
                id=r[0], topic=r[1], payload=msgpack.unpackb(r[2], raw=False),
                dst=r[3], db=r[4], created_at=r[5], source_db=self._path,
            )
            for r in rows
        ]

    def cleanup(self, max_age_days: int = 30):
        cutoff = time.time() - max_age_days * 86400
        self._conn.execute('DELETE FROM outbox WHERE created_at < ?', (cutoff,))
        self._conn.commit()

    def close(self):
        try:
            self._conn.close()
        except Exception:
            pass

    def delete_if_empty(self) -> bool:
        count = self._conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
        if count > 0:
            return False
        self.close()
        _delete_db_files(self._path)
        return True


def cleanup_empty_outbox_files():
    outbox_dir = Path(_OUTBOX_DIR)
    if not outbox_dir.is_dir():
        return
    for db_file in outbox_dir.glob('*.db'):
        pid = _extract_pid(db_file.stem)
        if pid is not None and psutil.pid_exists(pid):
            continue
        db_path = str(db_file)
        try:
            conn = _connect(db_path)
            count = conn.execute('SELECT COUNT(*) FROM outbox').fetchone()[0]
            conn.close()
        except Exception:
            _delete_db_files(db_path)
            continue
        if count == 0:
            _delete_db_files(db_path)


def scan_all_outbox(dst_filter: set[str] | None = None, db_filter: str | None = None) -> list[OutboxRecord]:
    records: list[OutboxRecord] = []
    outbox_dir = Path(_OUTBOX_DIR)
    if not outbox_dir.is_dir():
        return records
    for db_file in outbox_dir.glob('*.db'):
        db_path = str(db_file)
        try:
            conn = _connect(db_path)
            rows = conn.execute(
                'SELECT id, topic, payload, dst, db, created_at FROM outbox ORDER BY id',
            ).fetchall()
            for r in rows:
                if dst_filter and r[3] not in dst_filter:
                    continue
                if db_filter is not None and r[4] != db_filter:
                    continue
                records.append(OutboxRecord(
                    id=r[0], topic=r[1], payload=msgpack.unpackb(r[2], raw=False),
                    dst=r[3], db=r[4], created_at=r[5], source_db=db_path,
                ))
            conn.close()
        except Exception as e:
            AppLogger.warning(f'outbox scan failed: {db_path}', exc=e)
    return records


def remove_outbox_from(db_path: str, record_id: int):
    try:
        conn = _connect(db_path)
        conn.execute('DELETE FROM outbox WHERE id = ?', (record_id,))
        conn.commit()
        conn.close()
    except Exception as e:
        AppLogger.warning(f'outbox remove_from failed: {db_path} id={record_id}', exc=e)


def remove_outbox_batch_from(db_path: str, record_ids: list[int]):
    if not record_ids:
        return
    try:
        conn = _connect(db_path)
        conn.executemany('DELETE FROM outbox WHERE id = ?', [(rid,) for rid in record_ids])
        conn.commit()
        conn.close()
    except Exception as e:
        AppLogger.warning(f'outbox remove_batch_from failed: {db_path}', exc=e)

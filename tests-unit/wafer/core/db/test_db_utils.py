import py_compile
import sqlite3

import pytest

from wafer.core.db.db_utils import (
    apply_read_pragmas,
    apply_write_pragmas,
    connect_with_retry,
    delete_database_files,
)


def test_compile():
    py_compile.compile("wafer/core/db/db_utils.py")


def test_apply_write_pragmas(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply_write_pragmas(conn)
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_apply_read_pragmas(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply_read_pragmas(conn)
    assert conn.execute("PRAGMA query_only").fetchone()[0] == 1
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_connect_with_retry_success(tmp_path):
    db_path = str(tmp_path / "test.db")
    conn = connect_with_retry(db_path)
    assert conn is not None
    conn.close()


def test_connect_with_retry_raises_on_failure():
    with pytest.raises(sqlite3.OperationalError):
        connect_with_retry("file:nonexistent?mode=ro", retries=1, delay=0, uri=True)


def test_delete_database_files_removes_all(tmp_path):
    db = tmp_path / "test.db"
    wal = tmp_path / "test.db-wal"
    shm = tmp_path / "test.db-shm"
    db.write_bytes(b"")
    wal.write_bytes(b"")
    shm.write_bytes(b"")
    assert delete_database_files(str(db), retries=1) is True
    assert not db.exists()
    assert not wal.exists()
    assert not shm.exists()


def test_delete_database_files_noop(tmp_path):
    assert delete_database_files(str(tmp_path / "nonexistent.db"), retries=1) is True


def test_delete_database_files_default_retries():
    import inspect

    sig = inspect.signature(delete_database_files)
    assert sig.parameters["retries"].default == 10

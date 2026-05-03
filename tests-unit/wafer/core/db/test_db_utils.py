import py_compile
import sqlite3

import pytest

from wafer.core.db.db_utils import (
    apply_read_pragmas,
    apply_write_pragmas,
    build_basic_entries,
    connect_with_retry,
    delete_database_files,
)
from wafer.utils.hashes import fast_signature_hash


def test_compile():
    py_compile.compile("wafer/core/db/db_utils.py")
    py_compile.compile("wafer/app/indexer/scanner.py")


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
    assert delete_database_files(str(db), retries=1, delay=0) is True
    assert not db.exists()
    assert not wal.exists()
    assert not shm.exists()


def test_delete_database_files_noop(tmp_path):
    assert delete_database_files(str(tmp_path / "nonexistent.db"), retries=1, delay=0) is True


def test_delete_database_files_default_retries():
    import inspect

    sig = inspect.signature(delete_database_files)
    assert sig.parameters["retries"].default == 10


def test_build_basic_entries_source_fields():
    paths = ["/a/b.jpg"]
    file_info = {"/a/b.jpg": (1.0, 1000, 0.5)}
    sources, _ = build_basic_entries(paths, file_info, {}, 100.0)
    assert len(sources) == 1
    p, _hash, fsize, mtime, ctime, now = sources[0]
    assert p == "/a/b.jpg"
    assert fsize == 1000
    assert mtime == 1.0
    assert ctime == 0.5
    assert now == 100.0


def test_build_basic_entries_file_fields():
    paths = ["/a/b.jpg"]
    file_info = {"/a/b.jpg": (1.0, 1000, 0.5)}
    aspect_map = {"/a/b.jpg": 2.5}
    _, files = build_basic_entries(paths, file_info, aspect_map, 100.0)
    assert len(files) == 1
    p, folder, name, aspect, _ = files[0]
    assert p == "/a/b.jpg"
    assert name == "b.jpg"
    assert aspect == 2.5


def test_build_basic_entries_missing_info_defaults():
    paths = ["/a/unknown.jpg"]
    sources, _ = build_basic_entries(paths, {}, {}, 100.0)
    assert len(sources) == 1
    _, _hash, fsize, mtime, ctime, _ = sources[0]
    assert fsize == 0
    assert mtime == 0.0
    assert ctime == 0.0


def test_build_basic_entries_default_aspect():
    paths = ["/a/b.jpg"]
    file_info = {"/a/b.jpg": (1.0, 100, 0.5)}
    _, files = build_basic_entries(paths, file_info, {}, 100.0)
    assert files[0][3] == 1.0


def test_build_basic_entries_multiple_paths():
    paths = ["/a/b.jpg", "/a/c.png"]
    file_info = {"/a/b.jpg": (1.0, 100, 0.5), "/a/c.png": (2.0, 200, 1.0)}
    aspect_map = {"/a/b.jpg": 1.5, "/a/c.png": 1.0}
    sources, files = build_basic_entries(paths, file_info, aspect_map, 100.0)
    assert len(sources) == 2
    assert len(files) == 2
    names = {f[2] for f in files}
    assert "b.jpg" in names
    assert "c.png" in names


def test_build_basic_entries_hash_from_file_info():
    paths = ["/a/img.jpg"]
    file_info = {"/a/img.jpg": (42.0, 512, 1.0)}
    sources, _ = build_basic_entries(paths, file_info, {}, 0.0)
    expected_hash = fast_signature_hash("/a/img.jpg", 512, 256)
    assert sources[0][1] == expected_hash



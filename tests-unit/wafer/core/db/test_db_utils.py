import sqlite3

import pytest

from wafer.core.db.db_utils import (
    apply_read_pragmas,
    apply_write_pragmas,
    build_basic_entries,
    build_like_condition,
    connect_with_retry,
    delete_database_files,
    escape_like,
)
from wafer.core.common.hashes import fast_signature_hash


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


def test_build_basic_entries_fills_all_fields():
    paths = ["/a/b.jpg", "/a/c.png"]
    file_info = {"/a/b.jpg": (1.0, 1000, 0.5), "/a/c.png": (2.0, 200, 1.0)}
    aspect_map = {"/a/b.jpg": 2.5, "/a/c.png": 1.5}
    sources, files = build_basic_entries(paths, file_info, aspect_map, 100.0)
    assert sources == [
        ("/a/b.jpg", fast_signature_hash("/a/b.jpg", 1000, 256), 1000, 1.0, 0.5, 100.0),
        ("/a/c.png", fast_signature_hash("/a/c.png", 200, 256), 200, 2.0, 1.0, 100.0),
    ]
    assert files == [("/a/b.jpg", "/a/b.jpg", "b.jpg", 2.5, None), ("/a/c.png", "/a/c.png", "c.png", 1.5, None)]


def test_build_basic_entries_defaults_for_missing_info_and_aspect():
    sources, files = build_basic_entries(["/a/unknown.jpg"], {}, {}, 100.0)
    _, _hash, fsize, mtime, ctime, _ = sources[0]
    assert (fsize, mtime, ctime) == (0, 0.0, 0.0)
    assert files[0][3] == 1.0


def test_escape_like():
    assert escape_like(r"100%_\x") == r"100\%\_\\x"


def test_build_like_condition_like_escapes_wildcards():
    clause, values = build_like_condition("v", ["100%", "a_b", r"a\b"], "OR")
    assert clause == " OR ".join([r"v LIKE ? ESCAPE '\'"] * 3)
    assert values == [r"%100\%%", r"%a\_b%", r"%a\\b%"]


def test_build_like_condition_glob_wraps_wildcard():
    clause, values = build_like_condition("v", ["a", "b"], "AND", "GLOB")
    assert clause == "v GLOB ? AND v GLOB ?"
    assert values == ["*a*", "*b*"]


def test_build_like_condition_empty():
    assert build_like_condition("v", [], "OR") == ("", [])


def test_delete_database_files_treats_glob_metacharacters_literally(tmp_path):
    db = tmp_path / "[ab].db"
    neighbours = [tmp_path / "a.db", tmp_path / "b.db"]
    db.write_bytes(b"")
    for path in neighbours:
        path.write_bytes(b"")
    assert delete_database_files(str(tmp_path / "[ab]"), retries=1, delay=0) is True
    assert not db.exists()
    assert all(path.exists() for path in neighbours)


@pytest.mark.parametrize("op, joined", [("AND", " AND "), ("and", " AND "), ("OR", " OR "), ("1) OR (1", " OR ")])
def test_build_like_condition_only_joins_with_and_or_or(op, joined):
    clause, _ = build_like_condition("v", ["a", "b"], op)
    assert clause == joined.join([r"v LIKE ? ESCAPE '\'"] * 2)

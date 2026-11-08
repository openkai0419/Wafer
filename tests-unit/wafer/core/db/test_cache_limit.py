import os
import sqlite3

import pytest

from wafer.core.common.paths import resolve_data_path
from wafer.core.db.cache_limit import DB_CACHE_DEFAULT_MB, db_cache_limit_mb, process_db_cache_limit_mb, save_db_cache_limit
from wafer.core.db.db_utils import apply_read_pragmas, apply_write_pragmas

MEBIBYTE = 1024 * 1024
INI = resolve_data_path("cache_settings.ini")
DAMAGED_FILES = [b"\x00" * 64, b"garbage line\n", b"[database]\ncache_limit_mb = 1\ncache_limit_mb = 2\n", b"\xff\xfe not utf-8"]


@pytest.fixture(autouse=True)
def clean(tmp_path):
    if os.path.exists(INI):
        os.remove(INI)
    process_db_cache_limit_mb.cache_clear()
    conn = sqlite3.connect(":memory:")
    before = conn.execute("PRAGMA soft_heap_limit").fetchone()[0]
    yield
    if os.path.exists(INI):
        os.remove(INI)
    process_db_cache_limit_mb.cache_clear()
    conn.execute(f"PRAGMA soft_heap_limit={before}")
    conn.close()


def _limit(conn) -> int:
    return conn.execute("PRAGMA soft_heap_limit").fetchone()[0]


def test_default_is_512_mib():
    assert DB_CACHE_DEFAULT_MB == 512 and db_cache_limit_mb() == 512


def test_saved_limit_is_read_back():
    save_db_cache_limit(300)
    assert db_cache_limit_mb() == 300


def test_broken_value_falls_back_to_the_default():
    with open(INI, "w", encoding="utf-8") as f:
        f.write("[database]\ncache_limit_mb = lots\n")
    assert db_cache_limit_mb() == DB_CACHE_DEFAULT_MB


@pytest.mark.parametrize("content", DAMAGED_FILES)
def test_a_damaged_file_falls_back_to_the_default(content):
    with open(INI, "wb") as f:
        f.write(content)
    assert db_cache_limit_mb() == DB_CACHE_DEFAULT_MB


@pytest.mark.parametrize("apply", [apply_read_pragmas, apply_write_pragmas])
def test_a_damaged_file_does_not_stop_database_connections(tmp_path, apply):
    with open(INI, "wb") as f:
        f.write(DAMAGED_FILES[0])
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply(conn)
    assert _limit(conn) == DB_CACHE_DEFAULT_MB * MEBIBYTE
    conn.close()


def test_saving_repairs_a_damaged_file():
    with open(INI, "wb") as f:
        f.write(DAMAGED_FILES[0])
    save_db_cache_limit(300)
    assert db_cache_limit_mb() == 300


@pytest.mark.parametrize("apply", [apply_read_pragmas, apply_write_pragmas])
def test_connections_apply_the_saved_limit_to_the_process(tmp_path, apply):
    save_db_cache_limit(300)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply(conn)
    assert _limit(conn) == 300 * MEBIBYTE
    conn.close()


def test_a_saved_limit_waits_for_the_next_process(tmp_path):
    save_db_cache_limit(300)
    first = sqlite3.connect(str(tmp_path / "first.db"))
    apply_read_pragmas(first)
    save_db_cache_limit(128)
    second = sqlite3.connect(str(tmp_path / "second.db"))
    apply_read_pragmas(second)
    assert _limit(second) == 300 * MEBIBYTE
    assert db_cache_limit_mb() == 128
    first.close()
    second.close()


def test_read_connections_keep_their_page_cache(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply_read_pragmas(conn)
    assert conn.execute("PRAGMA cache_size").fetchone()[0] == -50000
    conn.close()

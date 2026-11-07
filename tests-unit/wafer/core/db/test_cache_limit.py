import os
import sqlite3

import pytest

from wafer.core.common.paths import resolve_data_path
from wafer.core.db.cache_limit import DB_CACHE_DEFAULT_MB, db_cache_limit_mb, save_db_cache_limit
from wafer.core.db.db_utils import apply_read_pragmas, apply_write_pragmas

MEBIBYTE = 1024 * 1024
INI = resolve_data_path("cache_settings.ini")


@pytest.fixture(autouse=True)
def clean(tmp_path):
    if os.path.exists(INI):
        os.remove(INI)
    conn = sqlite3.connect(":memory:")
    before = conn.execute("PRAGMA soft_heap_limit").fetchone()[0]
    yield
    if os.path.exists(INI):
        os.remove(INI)
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


@pytest.mark.parametrize("apply", [apply_read_pragmas, apply_write_pragmas])
def test_new_connections_apply_the_limit_to_the_process(tmp_path, apply):
    save_db_cache_limit(300)
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply(conn)
    assert _limit(conn) == 300 * MEBIBYTE
    conn.close()


def test_read_connections_keep_their_page_cache(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "test.db"))
    apply_read_pragmas(conn)
    assert conn.execute("PRAGMA cache_size").fetchone()[0] == -50000
    conn.close()

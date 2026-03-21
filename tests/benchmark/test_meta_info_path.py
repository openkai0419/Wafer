import os
import sqlite3
import time
import random
import string

import pytest

from wafer.core.db.file_db import _TABLES, _VIEWS, _INDEXES_SQL

pytestmark = pytest.mark.benchmark

SIZES = [10_000, 50_000, 100_000]
WARMUP = 2
ITERATIONS = 5


def _create_schema(conn):
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=OFF')
    conn.execute('PRAGMA foreign_keys=ON')
    for _, _, sql in _TABLES:
        conn.execute(sql)
    conn.commit()
    for name, _ in reversed(_VIEWS):
        conn.execute(f'DROP VIEW IF EXISTS {name}')
    for _, sql in _VIEWS:
        conn.execute(sql)
    conn.commit()
    conn.executescript(_INDEXES_SQL)


def _populate(conn, n, seed=42):
    rng = random.Random(seed)
    folders = [f'C:/images/folder{i:03d}' for i in range(50)]
    extensions = ['.png', '.jpg', '.webp', '.gif', '.bmp']

    hash_entries = []
    source_entries = []
    file_entries = []
    meta_entries = []

    for i in range(n):
        folder = rng.choice(folders)
        ext = rng.choice(extensions)
        fname = f'img_{i:06d}{ext}'
        path = f'{folder}/{fname}'
        file_hash = f'hash_{i:08x}'
        size = rng.randint(10_000, 50_000_000)
        modified = 1700000000.0 + rng.random() * 86400 * 365

        hash_entries.append((file_hash,))
        source_entries.append((path, file_hash, size, modified))
        file_entries.append((path, path, rng.uniform(0.3, 3.0)))
        meta_entries.append((path, 'path', path, None))
        meta_entries.append((path, 'name', fname, None))
        meta_entries.append((path, 'size', str(size), float(size)))
        meta_entries.append((path, 'modified', str(modified), modified))
        meta_entries.append((path, 'file_hash', file_hash, None))

    conn.executemany('INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)', hash_entries)
    conn.executemany(
        'INSERT INTO sources (source, file_hash, size, modified) VALUES (?, ?, ?, ?)',
        source_entries,
    )
    conn.executemany(
        'INSERT INTO files (path, source, aspect_ratio) VALUES (?, ?, ?)',
        file_entries,
    )
    conn.executemany(
        'INSERT INTO meta_info (path, key, value, value_num) VALUES (?, ?, ?, ?)',
        meta_entries,
    )
    conn.commit()
    conn.execute('ANALYZE')
    conn.commit()


def _populate_proposed_extra(conn, n, seed=42):
    rows = conn.execute('SELECT path FROM files').fetchall()
    path_entries = [(r[0], 'path', r[0], None) for r in rows]

    conn.executemany(
        '''INSERT OR IGNORE INTO meta_info (path, key, value, value_num)
           VALUES (?, ?, ?, ?)''',
        path_entries,
    )
    conn.commit()
    conn.execute('ANALYZE')
    conn.commit()


def _measure(conn, sql, params=(), warmup=WARMUP, iterations=ITERATIONS):
    cur = conn.cursor()
    for _ in range(warmup):
        cur.execute(sql, params).fetchall()

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        rows = cur.execute(sql, params).fetchall()
        elapsed = time.perf_counter() - t0
        times.append(elapsed)
    cur.close()

    avg = sum(times) / len(times)
    return avg, len(rows), min(times), max(times)


SQL_CURRENT_PATH_SEARCH = """
    SELECT i.path FROM files AS i
    WHERE i.path LIKE ?
"""

SQL_PROPOSED_PATH_SEARCH = """
    SELECT DISTINCT mi.path FROM meta_info AS mi
    WHERE mi."key" = 'path' AND mi.value LIKE ?
"""

SQL_CURRENT_FILEPATH_KV = """
    SELECT path, "key", value FROM kv_all
    WHERE "key" = 'path' AND value LIKE ?
"""

SQL_PROPOSED_PATH_KV = """
    SELECT path, "key", value FROM kv_all
    WHERE "key" = 'path' AND value LIKE ?
"""

SQL_CURRENT_NAME_FROM_FILES_FULL = """
    SELECT mi.path, mi.value AS name
    FROM meta_info AS mi
    WHERE mi."key" = 'name'
    LIMIT ?
"""

SQL_PROPOSED_NAME_FROM_META = """
    SELECT mi.path, mi.value AS name
    FROM meta_info AS mi
    WHERE mi."key" = 'name'
    LIMIT ?
"""

SQL_CURRENT_LIST_ALL_KEYS = """
    SELECT "key", COUNT(*) AS freq FROM (
        SELECT DISTINCT path, 'path' AS "key" FROM files
        UNION ALL
        SELECT DISTINCT path, "key" FROM meta_info
        UNION ALL
        SELECT DISTINCT i.path, t."key"
        FROM tags AS t
        JOIN sources AS s ON s.file_hash = t.file_hash
        JOIN files AS i ON i.source = s.source
    ) AS items
    GROUP BY "key" ORDER BY freq DESC
"""

SQL_PROPOSED_LIST_ALL_KEYS = """
    SELECT "key", COUNT(*) AS freq FROM (
        SELECT DISTINCT path, "key" FROM meta_info
        UNION ALL
        SELECT DISTINCT i.path, t."key"
        FROM tags AS t
        JOIN sources AS s ON s.file_hash = t.file_hash
        JOIN files AS i ON i.source = s.source
    ) AS items
    GROUP BY "key" ORDER BY freq DESC
"""

SQL_CURRENT_FILTER_COMBINED = """
    SELECT DISTINCT path FROM (
        SELECT i.path FROM files AS i WHERE i.path LIKE ?
        UNION ALL
        SELECT mi.path FROM meta_info AS mi
        WHERE mi."key" IN ('name', 'size', 'modified', 'file_hash')
        AND mi.value LIKE ?
    )
"""

SQL_PROPOSED_FILTER_COMBINED = """
    SELECT DISTINCT path FROM (
        SELECT mi.path FROM meta_info AS mi
        WHERE mi."key" IN ('path', 'name', 'size', 'modified', 'file_hash')
        AND mi.value LIKE ?
    )
"""


_db_sizes: dict[int, tuple[int, int]] = {}


@pytest.fixture(params=SIZES, scope='module')
def populated_db(request, tmp_path_factory):
    n = request.param
    db_path = tmp_path_factory.mktemp(f'bench_{n}') / 'test.db'
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    _populate(conn, n)
    size_before = os.path.getsize(db_path)
    _populate_proposed_extra(conn, n)
    size_after = os.path.getsize(db_path)
    _db_sizes[n] = (size_before, size_after)
    yield conn, n
    conn.close()


class TestPathSearchBenchmark:

    def test_path_like_search(self, populated_db):
        conn, n = populated_db
        keyword = '%folder010%'

        avg_cur, rows_cur, min_cur, max_cur = _measure(
            conn, SQL_CURRENT_PATH_SEARCH, (keyword,),
        )
        avg_prop, rows_prop, min_prop, max_prop = _measure(
            conn, SQL_PROPOSED_PATH_SEARCH, (keyword,),
        )
        print(f'\n--- Path LIKE search (n={n:,}, keyword={keyword}) ---')
        print(f'  Current (files PK scan):  avg={avg_cur*1000:.2f}ms  min={min_cur*1000:.2f}  max={max_cur*1000:.2f}  rows={rows_cur}')
        print(f'  Proposed (meta_info):      avg={avg_prop*1000:.2f}ms  min={min_prop*1000:.2f}  max={max_prop*1000:.2f}  rows={rows_prop}')
        ratio = avg_prop / avg_cur if avg_cur > 0 else float('inf')
        print(f'  Ratio (proposed/current):  {ratio:.2f}x')

    def test_kv_all_path_search(self, populated_db):
        conn, n = populated_db
        keyword = '%folder010%'

        avg_cur, rows_cur, min_cur, max_cur = _measure(
            conn, SQL_CURRENT_FILEPATH_KV, (keyword,),
        )
        avg_prop, rows_prop, min_prop, max_prop = _measure(
            conn, SQL_PROPOSED_PATH_KV, (keyword,),
        )
        print(f'\n--- kv_all path search (n={n:,}, keyword={keyword}) ---')
        print(f'  Current (__filepath__):    avg={avg_cur*1000:.2f}ms  min={min_cur*1000:.2f}  max={max_cur*1000:.2f}  rows={rows_cur}')
        print(f'  Proposed (path key):       avg={avg_prop*1000:.2f}ms  min={min_prop*1000:.2f}  max={max_prop*1000:.2f}  rows={rows_prop}')
        ratio = avg_prop / avg_cur if avg_cur > 0 else float('inf')
        print(f'  Ratio (proposed/current):  {ratio:.2f}x')

    def test_name_lookup(self, populated_db):
        conn, n = populated_db
        limit = min(n, 5000)

        avg_cur, rows_cur, min_cur, max_cur = _measure(
            conn, SQL_CURRENT_NAME_FROM_FILES_FULL, (limit,),
        )
        avg_prop, rows_prop, min_prop, max_prop = _measure(
            conn, SQL_PROPOSED_NAME_FROM_META, (limit,),
        )
        print(f'\n--- Name lookup (n={n:,}, limit={limit}) ---')
        print(f'  Current (files_full):      avg={avg_cur*1000:.2f}ms  min={min_cur*1000:.2f}  max={max_cur*1000:.2f}  rows={rows_cur}')
        print(f'  Proposed (meta_info):       avg={avg_prop*1000:.2f}ms  min={min_prop*1000:.2f}  max={max_prop*1000:.2f}  rows={rows_prop}')
        ratio = avg_prop / avg_cur if avg_cur > 0 else float('inf')
        print(f'  Ratio (proposed/current):  {ratio:.2f}x')

    def test_list_all_keys(self, populated_db):
        conn, n = populated_db

        avg_cur, rows_cur, min_cur, max_cur = _measure(
            conn, SQL_CURRENT_LIST_ALL_KEYS,
        )
        avg_prop, rows_prop, min_prop, max_prop = _measure(
            conn, SQL_PROPOSED_LIST_ALL_KEYS,
        )
        print(f'\n--- list_all_keys (n={n:,}) ---')
        print(f'  Current (virtual __filepath__): avg={avg_cur*1000:.2f}ms  min={min_cur*1000:.2f}  max={max_cur*1000:.2f}  keys={rows_cur}')
        print(f'  Proposed (meta_info only):      avg={avg_prop*1000:.2f}ms  min={min_prop*1000:.2f}  max={max_prop*1000:.2f}  keys={rows_prop}')
        ratio = avg_prop / avg_cur if avg_cur > 0 else float('inf')
        print(f'  Ratio (proposed/current):  {ratio:.2f}x')

    def test_combined_filter_query(self, populated_db):
        conn, n = populated_db
        keyword = '%img_00001%'

        avg_cur, rows_cur, min_cur, max_cur = _measure(
            conn, SQL_CURRENT_FILTER_COMBINED, (keyword, keyword),
        )
        avg_prop, rows_prop, min_prop, max_prop = _measure(
            conn, SQL_PROPOSED_FILTER_COMBINED, (keyword,),
        )
        print(f'\n--- Combined filter (n={n:,}, keyword={keyword}) ---')
        print(f'  Current (files+meta_info): avg={avg_cur*1000:.2f}ms  min={min_cur*1000:.2f}  max={max_cur*1000:.2f}  rows={rows_cur}')
        print(f'  Proposed (meta_info only): avg={avg_prop*1000:.2f}ms  min={min_prop*1000:.2f}  max={max_prop*1000:.2f}  rows={rows_prop}')
        ratio = avg_prop / avg_cur if avg_cur > 0 else float('inf')
        print(f'  Ratio (proposed/current):  {ratio:.2f}x')

    def test_db_size_impact(self, populated_db):
        conn, n = populated_db
        before, after = _db_sizes[n]
        meta_count = conn.execute('SELECT COUNT(*) FROM meta_info').fetchone()[0]

        print(f'\n--- DB size impact (n={n:,}) ---')
        print(f'  Before (no path in meta): {before / 1024 / 1024:.2f} MB')
        print(f'  After  (+path in meta):   {after / 1024 / 1024:.2f} MB')
        print(f'  Delta:                    {(after - before) / 1024:.1f} KB ({(after - before) / before * 100:.1f}%)')
        print(f'  meta_info rows total:     {meta_count:,}')

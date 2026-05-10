"""Schema comparison benchmark: OLD (meta_info-centric) vs NEW (normalized) vs COMPAT (view-based).

Purpose
-------
Plan: Move standard keys (name/size/modified/created/collected) out of meta_info
into sources/files columns. This benchmark measures the speed impact and
verifies that builtin/extension filter & sort plugins still resolve correctly.

Three schemas compared
----------------------
- OLD     : current production schema (standard keys live in meta_info AND sources.size/modified)
- NEW     : standard keys ONLY in sources/files columns (created/collected added to sources, name added to files)
- COMPAT  : NEW schema + a compatibility VIEW `meta_info_full` that re-exposes standard keys
            via UNION ALL so existing SQL written against `meta_info` keeps working.

Run
---
    pytest tests/benchmark/test_schema_comparison.py -s -m benchmark
"""

from __future__ import annotations

import random
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

import pytest

from wafer.core.db.db_utils import apply_read_pragmas

pytestmark = [pytest.mark.benchmark, pytest.mark.timeout(600)]

GENERATED_SIZES = [10_000, 50_000]
WARMUP = 2
ITERATIONS = 5

STANDARD_NUM_KEYS = ("size", "modified", "created", "collected")
STANDARD_TEXT_KEYS = ("name", "path", "file_hash")


# -----------------------------------------------------------------------------
# Schema definitions
# -----------------------------------------------------------------------------

OLD_SCHEMA = [
    "CREATE TABLE hash_index (file_hash TEXT PRIMARY KEY)",
    """CREATE TABLE sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )""",
    """CREATE TABLE files (
        path TEXT PRIMARY KEY, source TEXT NOT NULL,
        aspect_ratio REAL, source_extension TEXT,
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    """CREATE TABLE meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    """CREATE TABLE tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
]

OLD_VIEWS = [
    """CREATE VIEW files_full AS
       SELECT i.path, i.source, i.aspect_ratio, s.file_hash, s.size, s.modified
       FROM files i JOIN sources s ON s.source = i.source""",
]

OLD_INDEXES = [
    "CREATE INDEX idx_sources_file_hash ON sources(file_hash)",
    "CREATE INDEX idx_files_source ON files(source)",
    "CREATE INDEX idx_meta_info_key_fid ON meta_info(key, path)",
    "CREATE INDEX idx_meta_info_key_value ON meta_info(key, value)",
    "CREATE INDEX idx_meta_info_key_num ON meta_info(key, value_num)",
    "CREATE INDEX idx_tags_key_fid ON tags(key, file_hash)",
    "CREATE INDEX idx_tags_key_num ON tags(key, value_num)",
    "CREATE INDEX idx_sources_modified_source ON sources(modified, source)",
    "CREATE INDEX idx_sources_size_source ON sources(size, source)",
]

NEW_SCHEMA = [
    "CREATE TABLE hash_index (file_hash TEXT PRIMARY KEY)",
    """CREATE TABLE sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL, created REAL, collected REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON DELETE CASCADE
    )""",
    """CREATE TABLE files (
        path TEXT PRIMARY KEY, source TEXT NOT NULL,
        name TEXT, aspect_ratio REAL, source_extension TEXT,
        FOREIGN KEY(source) REFERENCES sources(source) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    """CREATE TABLE meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
    """CREATE TABLE tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        locked INTEGER NOT NULL DEFAULT 0,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash) ON UPDATE CASCADE ON DELETE CASCADE
    )""",
]

NEW_VIEWS = [
    """CREATE VIEW files_full AS
       SELECT i.path, i.name, i.source, i.aspect_ratio,
              s.file_hash, s.size, s.modified, s.created, s.collected
       FROM files i JOIN sources s ON s.source = i.source""",
]

NEW_INDEXES = [
    "CREATE INDEX idx_sources_file_hash ON sources(file_hash)",
    "CREATE INDEX idx_files_source ON files(source)",
    "CREATE INDEX idx_files_name ON files(name)",
    "CREATE INDEX idx_meta_info_key_fid ON meta_info(key, path)",
    "CREATE INDEX idx_meta_info_key_value ON meta_info(key, value)",
    "CREATE INDEX idx_meta_info_key_num ON meta_info(key, value_num)",
    "CREATE INDEX idx_tags_key_fid ON tags(key, file_hash)",
    "CREATE INDEX idx_tags_key_num ON tags(key, value_num)",
    "CREATE INDEX idx_sources_modified ON sources(modified)",
    "CREATE INDEX idx_sources_created ON sources(created)",
    "CREATE INDEX idx_sources_collected ON sources(collected)",
    "CREATE INDEX idx_sources_size ON sources(size)",
]

COMPAT_VIEW = """CREATE VIEW meta_info_full AS
    SELECT path, key, value, value_num, locked FROM meta_info
    UNION ALL
    SELECT i.path, 'name', i.name, NULL, 0 FROM files i WHERE i.name IS NOT NULL
    UNION ALL
    SELECT i.path, 'path', i.path, NULL, 0 FROM files i
    UNION ALL
    SELECT i.path, 'size', CAST(s.size AS TEXT), CAST(s.size AS REAL), 0
    FROM files i JOIN sources s ON s.source = i.source WHERE s.size IS NOT NULL
    UNION ALL
    SELECT i.path, 'modified', CAST(s.modified AS TEXT), s.modified, 0
    FROM files i JOIN sources s ON s.source = i.source WHERE s.modified IS NOT NULL
    UNION ALL
    SELECT i.path, 'created', CAST(s.created AS TEXT), s.created, 0
    FROM files i JOIN sources s ON s.source = i.source WHERE s.created IS NOT NULL
    UNION ALL
    SELECT i.path, 'collected', CAST(s.collected AS TEXT), s.collected, 0
    FROM files i JOIN sources s ON s.source = i.source WHERE s.collected IS NOT NULL
"""


# -----------------------------------------------------------------------------
# Population
# -----------------------------------------------------------------------------


def _generate(n: int, seed: int = 42, exif_prob: float = 0.7):
    rng = random.Random(seed)
    folders = [f"C:/images/folder{i:03d}" for i in range(50)]
    subs = [f"sub{j:02d}" for j in range(10)]
    exts = [".png", ".jpg", ".webp", ".gif", ".bmp"]
    exif_keys = ["exif.Software", "exif.Comment", "exif.Title", "exif.dpi"]

    rows = []
    for i in range(n):
        folder = rng.choice(folders)
        sub = rng.choice(subs) if rng.random() < 0.6 else ""
        ext = rng.choice(exts)
        fname = f"img_{i:06d}{ext}"
        base = f"{folder}/{sub}" if sub else folder
        path = f"{base}/{fname}"
        file_hash = f"hash_{i:08x}"
        size = rng.randint(10_000, 50_000_000)
        modified = 1700000000.0 + rng.random() * 86400 * 365
        created = modified - rng.random() * 86400 * 30
        collected = modified + 10
        aspect = rng.uniform(0.3, 3.0)
        exifs = {}
        if rng.random() < exif_prob:
            for ek in exif_keys:
                if rng.random() < 0.7:
                    exifs[ek] = "".join(rng.choices("abcdefghijklmnop ", k=rng.randint(10, 60)))
        rows.append((path, fname, file_hash, size, modified, created, collected, aspect, exifs))
    return rows


def _populate_old(conn, rows):
    hashes = [(r[2],) for r in rows]
    sources = [(r[0], r[2], r[3], r[4]) for r in rows]
    files = [(r[0], r[0], r[7]) for r in rows]
    metas = []
    for path, name, file_hash, size, modified, created, collected, _aspect, exifs in rows:
        metas.append((path, "path", path, None))
        metas.append((path, "name", name, None))
        metas.append((path, "size", str(size), float(size)))
        metas.append((path, "modified", str(modified), modified))
        metas.append((path, "created", str(created), created))
        metas.append((path, "collected", str(collected), collected))
        metas.append((path, "file_hash", file_hash, None))
        for k, v in exifs.items():
            metas.append((path, k, v, None))
    conn.execute("BEGIN")
    conn.executemany("INSERT OR IGNORE INTO hash_index VALUES (?)", hashes)
    conn.executemany("INSERT INTO sources (source,file_hash,size,modified) VALUES (?,?,?,?)", sources)
    conn.executemany("INSERT INTO files (path,source,aspect_ratio) VALUES (?,?,?)", files)
    conn.executemany("INSERT INTO meta_info (path,key,value,value_num) VALUES (?,?,?,?)", metas)
    conn.commit()


def _populate_new(conn, rows):
    hashes = [(r[2],) for r in rows]
    sources = [(r[0], r[2], r[3], r[4], r[5], r[6]) for r in rows]
    files = [(r[0], r[0], r[1], r[7]) for r in rows]
    metas = []
    for path, _name, _file_hash, _size, _modified, _created, _collected, _aspect, exifs in rows:
        for k, v in exifs.items():
            metas.append((path, k, v, None))
    conn.execute("BEGIN")
    conn.executemany("INSERT OR IGNORE INTO hash_index VALUES (?)", hashes)
    conn.executemany("INSERT INTO sources (source,file_hash,size,modified,created,collected) VALUES (?,?,?,?,?,?)", sources)
    conn.executemany("INSERT INTO files (path,source,name,aspect_ratio) VALUES (?,?,?,?)", files)
    if metas:
        conn.executemany("INSERT INTO meta_info (path,key,value,value_num) VALUES (?,?,?,?)", metas)
    conn.commit()


def _build_db(path: Path, schema: list[str], views: list[str], indexes: list[str], rows, populator):
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    for sql in schema:
        conn.execute(sql)
    conn.commit()
    populator(conn, rows)
    for sql in views:
        conn.execute(sql)
    for sql in indexes:
        conn.execute(sql)
    conn.execute("ANALYZE")
    conn.commit()
    apply_read_pragmas(conn)
    return conn


# -----------------------------------------------------------------------------
# Measurement helpers
# -----------------------------------------------------------------------------


def _measure_sql(conn, sql, params=()):
    cur = conn.cursor()
    for _ in range(WARMUP):
        cur.execute(sql, params).fetchall()
    times = []
    rows = None
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        rows = cur.execute(sql, params).fetchall()
        times.append(time.perf_counter() - t0)
    cur.close()
    return sum(times) / len(times), len(rows), rows


_results: dict[int, dict[str, dict[str, tuple[float, int]]]] = defaultdict(lambda: defaultdict(dict))


def _record(n: int, schema: str, scenario: str, avg: float, rowcount: int):
    _results[n][scenario][schema] = (avg, rowcount)


def _print_result(n: int, scenario: str, schema: str, avg: float, rowcount: int):
    print(f"  [{schema:7s}] {scenario:40s} avg={avg * 1000:8.2f}ms  rows={rowcount}")


# -----------------------------------------------------------------------------
# Fixtures: build OLD / NEW dbs once per size
# -----------------------------------------------------------------------------


@pytest.fixture(params=GENERATED_SIZES, scope="module")
def schemas(request, tmp_path_factory):
    n = request.param
    rows = _generate(n)
    base = tmp_path_factory.mktemp(f"schemabench_{n}")

    old_conn = _build_db(base / "old.db", OLD_SCHEMA, OLD_VIEWS, OLD_INDEXES, rows, _populate_old)
    new_conn = _build_db(base / "new.db", NEW_SCHEMA, NEW_VIEWS, NEW_INDEXES, rows, _populate_new)
    compat_conn = _build_db(base / "compat.db", NEW_SCHEMA, NEW_VIEWS + [COMPAT_VIEW], NEW_INDEXES, rows, _populate_new)

    yield {"OLD": old_conn, "NEW": new_conn, "COMPAT": compat_conn}, n
    old_conn.close()
    new_conn.close()
    compat_conn.close()


# -----------------------------------------------------------------------------
# SQL templates per schema
# -----------------------------------------------------------------------------


# Sort by standard numeric key (modified)
SQL_SORT_OLD = """
SELECT m.path, m.source, m.aspect_ratio
FROM files_full AS m
LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = ?
LEFT JOIN (
    SELECT i.path, t.value_num FROM tags t
    JOIN sources s ON s.file_hash = t.file_hash
    JOIN files i ON i.source = s.source
    WHERE t."key" = ?
) AS _tg ON _tg.path = m.path
ORDER BY COALESCE(_tg.value_num, _mi.value_num) DESC
"""

SQL_SORT_NEW_DIRECT = """
SELECT m.path, m.source, m.aspect_ratio
FROM files_full AS m
ORDER BY m.{col} DESC
"""

# Sort by name
SQL_SORT_NAME_OLD = """
SELECT m.path, m.source, m.aspect_ratio,
       COALESCE(_tg.value, _mi.value) AS name
FROM files_full AS m
LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = 'name'
LEFT JOIN (
    SELECT i.path, t.value FROM tags t
    JOIN sources s ON s.file_hash = t.file_hash
    JOIN files i ON i.source = s.source
    WHERE t."key" = 'name'
) AS _tg ON _tg.path = m.path
"""

SQL_SORT_NAME_NEW = """
SELECT m.path, m.source, m.aspect_ratio, m.name
FROM files_full AS m
"""

# Date range filter (DateRangeFilter behaviour)
SQL_DATE_RANGE_OLD = """
SELECT path FROM meta_info WHERE "key" = ? AND value_num BETWEEN ? AND ?
"""

SQL_DATE_RANGE_NEW = """
SELECT i.path FROM files i JOIN sources s ON s.source = i.source
WHERE s.{col} BETWEEN ? AND ?
"""

SQL_DATE_RANGE_COMPAT = SQL_DATE_RANGE_OLD.replace("meta_info", "meta_info_full")

# Text filter on name (TextFilter behaviour)
SQL_TEXT_NAME_OLD = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi
    WHERE mi."key" = 'name' AND mi."value" LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" = 'name' AND t."value" LIKE ? ESCAPE '\\'
)
"""

SQL_TEXT_NAME_NEW = """
SELECT DISTINCT path FROM (
    SELECT i.path FROM files i WHERE i.name LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" = 'name' AND t."value" LIKE ? ESCAPE '\\'
)
"""

SQL_TEXT_NAME_COMPAT = SQL_TEXT_NAME_OLD.replace("meta_info", "meta_info_full")

# Text filter searching ALL keys (query_all)
SQL_TEXT_ALL_OLD = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi WHERE mi."value" LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."value" LIKE ? ESCAPE '\\'
)
"""

SQL_TEXT_ALL_NEW = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi WHERE mi."value" LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM files i WHERE i.name LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM files i WHERE i.path LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM files i JOIN sources s ON s.source = i.source
    WHERE s.file_hash LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."value" LIKE ? ESCAPE '\\'
)
"""

SQL_TEXT_ALL_COMPAT = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info_full AS mi WHERE mi."value" LIKE ? ESCAPE '\\'
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."value" LIKE ? ESCAPE '\\'
)
"""

# Numeric range on size
SQL_SIZE_RANGE_OLD = """
SELECT path FROM meta_info WHERE "key" = 'size' AND value_num BETWEEN ? AND ?
"""

SQL_SIZE_RANGE_NEW = """
SELECT i.path FROM files i JOIN sources s ON s.source = i.source
WHERE s.size BETWEEN ? AND ?
"""

SQL_SIZE_RANGE_COMPAT = SQL_SIZE_RANGE_OLD.replace("meta_info", "meta_info_full")

# get_all_metadata for one path (file_viewer)
SQL_META_FOR_PATH_OLD = "SELECT key, value FROM meta_info WHERE path = ?"
SQL_META_FOR_PATH_NEW = "SELECT key, value FROM meta_info WHERE path = ?"  # only ext keys
SQL_META_FOR_PATH_COMPAT = "SELECT key, value FROM meta_info_full WHERE path = ?"

# list_all_keys (full DB)
SQL_LIST_KEYS_OLD = """
SELECT key, COUNT(*) AS freq FROM (
    SELECT DISTINCT path, key FROM meta_info
    UNION ALL
    SELECT DISTINCT i.path, t.key FROM tags t
    JOIN sources s ON s.file_hash = t.file_hash
    JOIN files i ON i.source = s.source
) GROUP BY key
"""

SQL_LIST_KEYS_NEW = """
SELECT key, freq FROM (
    SELECT 'name' AS key, COUNT(*) AS freq FROM files WHERE name IS NOT NULL
    UNION ALL SELECT 'modified', COUNT(*) FROM sources WHERE modified IS NOT NULL
    UNION ALL SELECT 'size',     COUNT(*) FROM sources WHERE size IS NOT NULL
    UNION ALL SELECT 'created',  COUNT(*) FROM sources WHERE created IS NOT NULL
    UNION ALL SELECT 'collected',COUNT(*) FROM sources WHERE collected IS NOT NULL
    UNION ALL SELECT key, COUNT(*) FROM (SELECT DISTINCT path, key FROM meta_info) GROUP BY key
    UNION ALL SELECT t.key, COUNT(*) FROM (
        SELECT DISTINCT i.path, t.key FROM tags t
        JOIN sources s ON s.file_hash = t.file_hash
        JOIN files i ON i.source = s.source
    ) t GROUP BY t.key
)
"""

SQL_LIST_KEYS_COMPAT = SQL_LIST_KEYS_OLD.replace("meta_info", "meta_info_full")


# -----------------------------------------------------------------------------
# Benchmark scenarios
# -----------------------------------------------------------------------------


class TestSchemaComparison:
    def test_01_sort_by_modified(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Sort by modified ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SORT_OLD, ("modified", "modified"))
        _record(n, "OLD", "sort:modified", avg, rc)
        _print_result(n, "sort:modified", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SORT_NEW_DIRECT.format(col="modified"))
        _record(n, "NEW", "sort:modified", avg, rc)
        _print_result(n, "sort:modified", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_SORT_NEW_DIRECT.format(col="modified"))
        _record(n, "COMPAT", "sort:modified", avg, rc)
        _print_result(n, "sort:modified", "COMPAT", avg, rc)

    def test_02_sort_by_size(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Sort by size ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SORT_OLD, ("size", "size"))
        _record(n, "OLD", "sort:size", avg, rc)
        _print_result(n, "sort:size", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SORT_NEW_DIRECT.format(col="size"))
        _record(n, "NEW", "sort:size", avg, rc)
        _print_result(n, "sort:size", "NEW", avg, rc)

    def test_03_sort_by_created(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Sort by created ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SORT_OLD, ("created", "created"))
        _record(n, "OLD", "sort:created", avg, rc)
        _print_result(n, "sort:created", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SORT_NEW_DIRECT.format(col="created"))
        _record(n, "NEW", "sort:created", avg, rc)
        _print_result(n, "sort:created", "NEW", avg, rc)

    def test_04_sort_by_collected(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Sort by collected ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SORT_OLD, ("collected", "collected"))
        _record(n, "OLD", "sort:collected", avg, rc)
        _print_result(n, "sort:collected", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SORT_NEW_DIRECT.format(col="collected"))
        _record(n, "NEW", "sort:collected", avg, rc)
        _print_result(n, "sort:collected", "NEW", avg, rc)

    def test_05_sort_by_name(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Sort by name (fetch only, Python sort applied separately) ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SORT_NAME_OLD)
        _record(n, "OLD", "sort:name(fetch)", avg, rc)
        _print_result(n, "sort:name(fetch)", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SORT_NAME_NEW)
        _record(n, "NEW", "sort:name(fetch)", avg, rc)
        _print_result(n, "sort:name(fetch)", "NEW", avg, rc)

    def test_06_filter_date_range(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Filter modified BETWEEN (DateRangeFilter) ===")
        lo, hi = 1700000000.0 + 86400 * 30, 1700000000.0 + 86400 * 60
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_DATE_RANGE_OLD, ("modified", lo, hi))
        _record(n, "OLD", "filter:date_range", avg, rc)
        _print_result(n, "filter:date_range", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_DATE_RANGE_NEW.format(col="modified"), (lo, hi))
        _record(n, "NEW", "filter:date_range", avg, rc)
        _print_result(n, "filter:date_range", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_DATE_RANGE_COMPAT, ("modified", lo, hi))
        _record(n, "COMPAT", "filter:date_range", avg, rc)
        _print_result(n, "filter:date_range", "COMPAT", avg, rc)

    def test_07_filter_size_range(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Filter size BETWEEN ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_SIZE_RANGE_OLD, (100_000, 10_000_000))
        _record(n, "OLD", "filter:size_range", avg, rc)
        _print_result(n, "filter:size_range", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_SIZE_RANGE_NEW, (100_000, 10_000_000))
        _record(n, "NEW", "filter:size_range", avg, rc)
        _print_result(n, "filter:size_range", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_SIZE_RANGE_COMPAT, (100_000, 10_000_000))
        _record(n, "COMPAT", "filter:size_range", avg, rc)
        _print_result(n, "filter:size_range", "COMPAT", avg, rc)

    def test_08_text_filter_name(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Text filter on name ===")
        kw = "%img_0001%"
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_TEXT_NAME_OLD, (kw, kw))
        _record(n, "OLD", "filter:text_name", avg, rc)
        _print_result(n, "filter:text_name", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_TEXT_NAME_NEW, (kw, kw))
        _record(n, "NEW", "filter:text_name", avg, rc)
        _print_result(n, "filter:text_name", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_TEXT_NAME_COMPAT, (kw, kw))
        _record(n, "COMPAT", "filter:text_name", avg, rc)
        _print_result(n, "filter:text_name", "COMPAT", avg, rc)

    def test_09_text_filter_all_keys(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Text filter ALL keys (query_all) ===")
        kw = "%folder01%"
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_TEXT_ALL_OLD, (kw, kw))
        _record(n, "OLD", "filter:text_all", avg, rc)
        _print_result(n, "filter:text_all", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_TEXT_ALL_NEW, (kw, kw, kw, kw, kw))
        _record(n, "NEW", "filter:text_all", avg, rc)
        _print_result(n, "filter:text_all", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_TEXT_ALL_COMPAT, (kw, kw))
        _record(n, "COMPAT", "filter:text_all", avg, rc)
        _print_result(n, "filter:text_all", "COMPAT", avg, rc)

    def test_10_meta_for_one_path(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Get all metadata for one path (MetaViewer) ===")
        sample = conns["NEW"].execute("SELECT path FROM files LIMIT 1").fetchone()[0]
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_META_FOR_PATH_OLD, (sample,))
        _record(n, "OLD", "meta:for_path", avg, rc)
        _print_result(n, "meta:for_path", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_META_FOR_PATH_NEW, (sample,))
        _record(n, "NEW", "meta:for_path", avg, rc)
        _print_result(n, "meta:for_path", "NEW(ext only)", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_META_FOR_PATH_COMPAT, (sample,))
        _record(n, "COMPAT", "meta:for_path", avg, rc)
        _print_result(n, "meta:for_path", "COMPAT", avg, rc)

    def test_11_list_all_keys(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === list_all_keys (full DB) ===")
        avg, rc, _ = _measure_sql(conns["OLD"], SQL_LIST_KEYS_OLD)
        _record(n, "OLD", "list_all_keys", avg, rc)
        _print_result(n, "list_all_keys", "OLD", avg, rc)
        avg, rc, _ = _measure_sql(conns["NEW"], SQL_LIST_KEYS_NEW)
        _record(n, "NEW", "list_all_keys", avg, rc)
        _print_result(n, "list_all_keys", "NEW", avg, rc)
        avg, rc, _ = _measure_sql(conns["COMPAT"], SQL_LIST_KEYS_COMPAT)
        _record(n, "COMPAT", "list_all_keys", avg, rc)
        _print_result(n, "list_all_keys", "COMPAT", avg, rc)

    def test_12_db_size(self, schemas):
        conns, n = schemas
        print(f"\n[n={n:,}] === Database file size ===")
        for label, conn in conns.items():
            page_count = conn.execute("PRAGMA page_count").fetchone()[0]
            page_size = conn.execute("PRAGMA page_size").fetchone()[0]
            size_mb = page_count * page_size / (1024 * 1024)
            print(f"  [{label:7s}] {size_mb:.2f} MB ({page_count:,} pages * {page_size}B)")

    def test_99_summary(self, schemas):
        _conns, n = schemas
        print(f"\n[n={n:,}] === SUMMARY (NEW vs OLD speedup, COMPAT vs OLD) ===")
        scenarios = _results.get(n, {})
        print(f"  {'scenario':40s} {'OLD':>10s} {'NEW':>10s} {'COMPAT':>10s}  {'NEW/OLD':>9s}  {'COMPAT/OLD':>11s}")
        for scenario, schema_results in scenarios.items():
            old = schema_results.get("OLD")
            new = schema_results.get("NEW")
            compat = schema_results.get("COMPAT")
            old_ms = old[0] * 1000 if old else float("nan")
            new_ms = new[0] * 1000 if new else float("nan")
            compat_ms = compat[0] * 1000 if compat else float("nan")
            new_ratio = (new[0] / old[0]) if (old and new) else float("nan")
            compat_ratio = (compat[0] / old[0]) if (old and compat) else float("nan")
            print(f"  {scenario:40s} {old_ms:>8.2f}ms {new_ms:>8.2f}ms {compat_ms:>8.2f}ms  {new_ratio:>8.2f}x  {compat_ratio:>10.2f}x")


# -----------------------------------------------------------------------------
# Plugin resolution check (does NOT need bench DB; runs once)
# -----------------------------------------------------------------------------


class TestPluginResolution:
    """Verify that all builtin & extension Sort/Filter plugins can be imported and have valid attributes."""

    def test_builtin_sorts_attributes(self):
        from wafer.builtins.sorts import (
            NaturalPathSort,
            NaturalNameSort,
            ModifiedSort,
            CreatedSort,
            SizeSort,
            CollectedSort,
            RandomSort,
        )

        sorts = [NaturalPathSort, NaturalNameSort, ModifiedSort, CreatedSort, SizeSort, CollectedSort, RandomSort]
        print("\n=== Builtin Sort Plugins ===")
        for cls in sorts:
            meta_key = getattr(cls, "META_KEY", None)
            sort_col = getattr(cls, "SORT_COLUMN", None)
            has_custom = "sort_rows" in vars(cls)
            print(f"  {cls.__name__:20s} NAME={cls.NAME:12s} META_KEY={meta_key!s:10s} SORT_COLUMN={sort_col!s:10s} custom_sort={has_custom}")
            assert cls.NAME

    def test_builtin_filters_attributes(self):
        from wafer.builtins.filters import TextFilter, DirectoryFilter
        from wafer.builtins.mark.filter import MarkFilter

        filters = [TextFilter, DirectoryFilter, MarkFilter]
        print("\n=== Builtin Filter Plugins ===")
        for cls in filters:
            print(f"  {cls.__name__:20s} NAME={cls.NAME}")

    def test_extension_filters_attributes(self):
        try:
            from extensions.additional_filters.filter import DateRangeFilter
            from extensions.additional_filters.regex_filter import RegexFilter
        except Exception as e:
            pytest.skip(f"extension import failed: {e}")
        print("\n=== Extension Filter Plugins ===")
        for cls in (DateRangeFilter, RegexFilter):
            print(f"  {cls.__name__:25s} NAME={cls.NAME}")

    def test_filter_plugins_call_build_path_query(self):
        """Smoke: each filter plugin's build_path_query returns (sql, params) without raising."""
        from wafer.builtins.filters import TextFilter, DirectoryFilter
        from wafer.builtins.mark.filter import MarkFilter

        cases = [
            (TextFilter, {"keywords": "img", "keys": ["name"]}),
            (DirectoryFilter, {"directory": "C:/images/folder010"}),
            (MarkFilter, {"marks": ["fav"], "match_mode": "any"}),
        ]
        print("\n=== build_path_query smoke ===")
        for cls, params in cases:
            try:
                sql, p = cls.build_path_query(params, lambda x: x)
                print(f"  {cls.__name__:20s} OK  sql_len={len(sql or '')}  params={len(p)}")
            except Exception as e:
                print(f"  {cls.__name__:20s} FAIL {type(e).__name__}: {e}")
                raise

    def test_extension_date_range_call(self):
        try:
            from extensions.additional_filters.filter import DateRangeFilter
        except Exception as e:
            pytest.skip(f"extension import failed: {e}")
        params = {
            "target_key": "modified",
            "mode": "preset",
            "preset_value": 7,
            "preset_unit": "days",
            "preset_ref": "today",
        }
        sql, p = DateRangeFilter.build_path_query(params, lambda x: x)
        print(f"\n=== DateRangeFilter ===\n  sql={sql}\n  params={p}")
        assert sql and "sources AS s JOIN files AS i" in sql
        assert "s.modified" in sql
        assert "meta_info" not in sql

        fallback_sql, _ = DateRangeFilter.build_path_query(
            {"target_key": "custom.date", "mode": "range", "range_from": "2024/01/01", "range_to": "2024/01/02"},
            lambda x: x,
        )
        assert fallback_sql and "meta_info" in fallback_sql

import os
import random
import sqlite3
import time
from pathlib import Path

import pytest

from wafer.core.db.file_db import _TABLES, _VIEWS, _INDEXES_SQL
from wafer.core.db.db_utils import apply_read_pragmas

pytestmark = pytest.mark.benchmark

GENERATED_SIZES = [10_000, 50_000]
WARMUP = 2
ITERATIONS = 5

REAL_DB_DIR = Path(os.environ.get("WAFER_DATA_DIR", "C:/Users/openk/AppData/Local/Wafer/data"))
REAL_DBS = ["default", "nai"]


def _create_schema(conn):
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA foreign_keys=ON")
    for _, _, sql in _TABLES:
        conn.execute(sql)
    conn.commit()
    for name, _ in reversed(_VIEWS):
        conn.execute(f"DROP VIEW IF EXISTS {name}")
    for _, sql in _VIEWS:
        conn.execute(sql)
    conn.commit()
    conn.executescript(_INDEXES_SQL)


def _populate(conn, n, seed=42, with_exif=False):
    rng = random.Random(seed)
    folders = [f"C:/images/folder{i:03d}" for i in range(50)]
    subfolders = [f"sub{j:02d}" for j in range(10)]
    extensions = [".png", ".jpg", ".webp", ".gif", ".bmp"]
    exif_keys = ["exif.Software", "exif.Comment", "exif.Description", "exif.Source", "exif.Title", "exif.dpi"]

    hash_e, source_e, file_e, meta_e = [], [], [], []

    for i in range(n):
        folder = rng.choice(folders)
        sub = rng.choice(subfolders) if rng.random() < 0.6 else ""
        ext = rng.choice(extensions)
        fname = f"img_{i:06d}{ext}"
        base = f"{folder}/{sub}" if sub else folder
        path = f"{base}/{fname}"
        file_hash = f"hash_{i:08x}"
        size = rng.randint(10_000, 50_000_000)
        modified = 1700000000.0 + rng.random() * 86400 * 365
        created = modified - rng.random() * 86400 * 30

        hash_e.append((file_hash,))
        source_e.append((path, file_hash, size, modified))
        file_e.append((path, path, rng.uniform(0.3, 3.0)))
        meta_e.extend(
            [
                (path, "path", path, None),
                (path, "name", fname, None),
                (path, "size", str(size), float(size)),
                (path, "modified", str(modified), modified),
                (path, "created", str(created), created),
                (path, "file_hash", file_hash, None),
            ]
        )
        if with_exif and rng.random() < 0.75:
            meta_e.append((path, "collected", str(modified + 10), modified + 10))
            for ek in exif_keys:
                if rng.random() < 0.7:
                    val = "".join(rng.choices("abcdefghijklmnop ", k=rng.randint(10, 80)))
                    meta_e.append((path, ek, val, None))

    conn.executemany("INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)", hash_e)
    conn.executemany("INSERT INTO sources (source, file_hash, size, modified) VALUES (?, ?, ?, ?)", source_e)
    conn.executemany("INSERT INTO files (path, source, aspect_ratio) VALUES (?, ?, ?)", file_e)
    conn.executemany("INSERT INTO meta_info (path, key, value, value_num) VALUES (?, ?, ?, ?)", meta_e)
    conn.commit()
    conn.execute("ANALYZE")
    conn.commit()


def _measure(func, warmup=WARMUP, iterations=ITERATIONS):
    for _ in range(warmup):
        func()
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = func()
        times.append(time.perf_counter() - t0)
    avg = sum(times) / len(times)
    return avg, min(times), max(times), result


def _measure_sql(conn, sql, params=(), warmup=WARMUP, iterations=ITERATIONS):
    cur = conn.cursor()
    for _ in range(warmup):
        cur.execute(sql, params).fetchall()
    times = []
    rows = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        rows = cur.execute(sql, params).fetchall()
        times.append(time.perf_counter() - t0)
    cur.close()
    avg = sum(times) / len(times)
    return avg, min(times), max(times), len(rows)


def _fmt(avg, mn, mx, rows=None, label=""):
    row_str = f"  rows={rows}" if rows is not None else ""
    return f"{label}avg={avg * 1000:.2f}ms  min={mn * 1000:.2f}  max={mx * 1000:.2f}{row_str}"


def _open_readonly(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=True)
    conn.row_factory = sqlite3.Row
    apply_read_pragmas(conn)
    return conn


@pytest.fixture(params=GENERATED_SIZES, scope="module")
def gen_db(request, tmp_path_factory):
    n = request.param
    db_path = tmp_path_factory.mktemp(f"qbench_{n}") / "test.db"
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    _create_schema(conn)
    _populate(conn, n, with_exif=(n >= 50_000))
    apply_read_pragmas(conn)
    yield conn, n, str(db_path)
    conn.close()


@pytest.fixture(params=REAL_DBS, scope="module")
def real_db(request):
    name = request.param
    db_path = REAL_DB_DIR / f"{name}.db"
    if not db_path.exists():
        pytest.skip(f"{db_path} not found")
    conn = _open_readonly(str(db_path))
    n = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    yield conn, n, name
    conn.close()


SQL_TEXT_FILTER_SINGLE = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi
    WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
)
"""

SQL_TEXT_FILTER_AND = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi
    WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\' AND mi."value" LIKE ? ESCAPE '\\')
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\' AND t."value" LIKE ? ESCAPE '\\')
)
"""

SQL_DIR_FILTER = """
SELECT DISTINCT path FROM files WHERE path LIKE ? ESCAPE '\\'
"""

SQL_DIR_FILTER_NO_SUB = """
SELECT DISTINCT path FROM files WHERE (path LIKE ? ESCAPE '\\' AND path NOT LIKE ? ESCAPE '\\')
"""

SQL_FETCH_BASIC = """
SELECT m.path, m.source, m.aspect_ratio
FROM files_full AS m JOIN ({path_query}) AS s USING(path)
"""

SQL_FETCH_SORT_MODIFIED = """
SELECT m.path, m.source, m.aspect_ratio
FROM files_full AS m JOIN ({path_query}) AS s USING(path)
LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = ?
LEFT JOIN (
    SELECT i.path, t.value, t.value_num
    FROM tags t JOIN sources s ON s.file_hash = t.file_hash
    JOIN files i ON i.source = s.source
    WHERE t."key" = ?
) AS _tg ON _tg.path = m.path
ORDER BY COALESCE(_tg.value_num, _mi.value_num) DESC
"""

SQL_FETCH_SORT_NAME_COL = """
SELECT m.path, m.source, m.aspect_ratio,
    COALESCE(_tg.value, _mi.value) AS name,
    COALESCE(_tg.value_num, _mi.value_num) AS name_num
FROM files_full AS m JOIN ({path_query}) AS s USING(path)
LEFT JOIN meta_info AS _mi ON _mi.path = m.path AND _mi."key" = ?
LEFT JOIN (
    SELECT i.path, t.value, t.value_num
    FROM tags t JOIN sources s ON s.file_hash = t.file_hash
    JOIN files i ON i.source = s.source
    WHERE t."key" = ?
) AS _tg ON _tg.path = m.path
"""

SQL_ALL_PATHS = "SELECT path FROM files"

SQL_LIST_ALL_KEYS = """
WITH matched_paths AS ({path_query})
SELECT "key", COUNT(*) AS freq FROM (
    SELECT DISTINCT mp.path, kv."key"
    FROM matched_paths AS mp
    JOIN meta_info AS kv ON kv.path = mp.path
    UNION ALL
    SELECT DISTINCT mp.path, t."key"
    FROM matched_paths AS mp
    JOIN files AS f ON f.path = mp.path
    JOIN sources AS s ON s.source = f.source
    JOIN tags AS t ON t.file_hash = s.file_hash
) AS items GROUP BY "key" ORDER BY freq DESC
"""

SQL_EXCLUDE = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi
    WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
) AS sq
WHERE sq.path NOT IN (
    SELECT em.path FROM meta_info AS em
    WHERE em."key" IN ('name','path') AND (em."value" LIKE ? ESCAPE '\\')
    UNION
    SELECT ei.path FROM tags AS et
    JOIN sources AS es ON es.file_hash = et.file_hash
    JOIN files AS ei ON ei.source = es.source
    WHERE et."key" IN ('name','path') AND (et."value" LIKE ? ESCAPE '\\')
)
"""

SQL_TEXT_AND_DIR = """
SELECT DISTINCT path FROM (
    SELECT path FROM (
        SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
            UNION ALL
            SELECT i.path FROM tags AS t
            JOIN sources AS s ON s.file_hash = t.file_hash
            JOIN files AS i ON i.source = s.source
            WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
        )
    )
    INTERSECT
    SELECT DISTINCT path FROM files WHERE path LIKE ? ESCAPE '\\'
)
"""

SQL_MULTI_KEY_SEARCH = """
SELECT DISTINCT path FROM (
    SELECT mi.path FROM meta_info AS mi
    WHERE mi."key" IN ('name','path','exif.Comment','exif.Description','exif.Title')
    AND (mi."value" LIKE ? ESCAPE '\\')
    UNION ALL
    SELECT i.path FROM tags AS t
    JOIN sources AS s ON s.file_hash = t.file_hash
    JOIN files AS i ON i.source = s.source
    WHERE t."key" IN ('name','path','exif.Comment','exif.Description','exif.Title')
    AND (t."value" LIKE ? ESCAPE '\\')
)
"""

SQL_COUNT_ONLY = """
SELECT COUNT(*) FROM ({path_query})
"""


class TestGeneratedDB:
    def test_01_full_scan_no_filter(self, gen_db):
        conn, n, _ = gen_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_BASIC.format(path_query=path_q)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[gen n={n:,}] Full scan (no filter):  {_fmt(avg, mn, mx, rows)}")

    def test_02_text_single_keyword(self, gen_db):
        conn, n, _ = gen_db
        kw = "%img_0001%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"\n[gen n={n:,}] Text filter single kw:  {_fmt(avg, mn, mx, rows)}")

    def test_03_text_rare_keyword(self, gen_db):
        conn, n, _ = gen_db
        kw = "%img_000001%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"\n[gen n={n:,}] Text filter rare kw:    {_fmt(avg, mn, mx, rows)}")

    def test_04_text_broad_keyword(self, gen_db):
        conn, n, _ = gen_db
        kw = "%folder01%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"\n[gen n={n:,}] Text filter broad kw:   {_fmt(avg, mn, mx, rows)}")

    def test_05_text_and_keywords(self, gen_db):
        conn, n, _ = gen_db
        kw1, kw2 = "%folder01%", "%png%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_AND, (kw1, kw2, kw1, kw2))
        print(f"\n[gen n={n:,}] Text AND keywords:      {_fmt(avg, mn, mx, rows)}")

    def test_06_dir_filter(self, gen_db):
        conn, n, _ = gen_db
        d = "C:/images/folder010/%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_DIR_FILTER, (d,))
        print(f"\n[gen n={n:,}] Dir filter:             {_fmt(avg, mn, mx, rows)}")

    def test_07_dir_filter_no_subfolder(self, gen_db):
        conn, n, _ = gen_db
        d1 = "C:/images/folder010/%"
        d2 = "C:/images/folder010/%/%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_DIR_FILTER_NO_SUB, (d1, d2))
        print(f"\n[gen n={n:,}] Dir filter (no sub):    {_fmt(avg, mn, mx, rows)}")

    def test_08_text_plus_dir(self, gen_db):
        conn, n, _ = gen_db
        kw = "%img_0001%"
        d = "C:/images/folder01%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_AND_DIR, (kw, kw, d))
        print(f"\n[gen n={n:,}] Text + Dir INTERSECT:   {_fmt(avg, mn, mx, rows)}")

    def test_09_exclude_filter(self, gen_db):
        conn, n, _ = gen_db
        inc = "%folder01%"
        exc = "%gif%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_EXCLUDE, (inc, inc, exc, exc))
        print(f"\n[gen n={n:,}] Include - Exclude:      {_fmt(avg, mn, mx, rows)}")

    def test_10_full_fetch_no_sort(self, gen_db):
        conn, n, _ = gen_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_BASIC.format(path_query=path_q)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[gen n={n:,}] Full fetch (no sort):   {_fmt(avg, mn, mx, rows)}")

    def test_11_full_fetch_sort_modified(self, gen_db):
        conn, n, _ = gen_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        avg, mn, mx, rows = _measure_sql(conn, sql, ("modified", "modified"))
        print(f"\n[gen n={n:,}] Full + sort modified:   {_fmt(avg, mn, mx, rows)}")

    def test_12_full_fetch_sort_name_python(self, gen_db):
        conn, n, _ = gen_db
        from wafer.utils.formatting import natural_key

        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_NAME_COL.format(path_query=path_q)

        def run():
            rows = list(conn.execute(sql, ("name", "name")).fetchall())
            rows.sort(key=lambda r: natural_key(r["name"] or ""))
            return rows

        avg, mn, mx, result = _measure(run)
        print(f"\n[gen n={n:,}] Full + name (python):   {_fmt(avg, mn, mx, len(result))}")

    def test_13_filtered_fetch_sort_modified(self, gen_db):
        conn, n, _ = gen_db
        kw = "%folder01%"
        path_q = SQL_TEXT_FILTER_SINGLE.replace("?", "?", 2)
        path_q_filled = """SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
            UNION ALL
            SELECT i.path FROM tags AS t
            JOIN sources AS s ON s.file_hash = t.file_hash
            JOIN files AS i ON i.source = s.source
            WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
        )"""
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q_filled)
        avg, mn, mx, rows = _measure_sql(conn, sql, (kw, kw, "modified", "modified"))
        print(f"\n[gen n={n:,}] Filtered + sort mod:    {_fmt(avg, mn, mx, rows)}")

    def test_14_list_all_keys_full(self, gen_db):
        conn, n, _ = gen_db
        sql = SQL_LIST_ALL_KEYS.format(path_query=SQL_ALL_PATHS)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[gen n={n:,}] list_all_keys (full):   {_fmt(avg, mn, mx, rows)}")

    def test_15_list_all_keys_filtered(self, gen_db):
        conn, n, _ = gen_db
        kw = "%folder01%"
        filter_q = """SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
            UNION ALL
            SELECT i.path FROM tags AS t
            JOIN sources AS s ON s.file_hash = t.file_hash
            JOIN files AS i ON i.source = s.source
            WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
        )"""
        sql = SQL_LIST_ALL_KEYS.format(path_query=filter_q)
        avg, mn, mx, rows = _measure_sql(conn, sql, (kw, kw))
        print(f"\n[gen n={n:,}] list_all_keys (filt):   {_fmt(avg, mn, mx, rows)}")

    def test_16_count_only_full(self, gen_db):
        conn, n, _ = gen_db
        sql = SQL_COUNT_ONLY.format(path_query=SQL_ALL_PATHS)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[gen n={n:,}] COUNT(*) full:          {_fmt(avg, mn, mx)}")

    def test_17_count_only_filtered(self, gen_db):
        conn, n, _ = gen_db
        kw = "%folder01%"
        filter_q = """SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" IN ('name','path') AND (mi."value" LIKE ? ESCAPE '\\')
            UNION ALL
            SELECT i.path FROM tags AS t
            JOIN sources AS s ON s.file_hash = t.file_hash
            JOIN files AS i ON i.source = s.source
            WHERE t."key" IN ('name','path') AND (t."value" LIKE ? ESCAPE '\\')
        )"""
        sql = SQL_COUNT_ONLY.format(path_query=filter_q)
        avg, mn, mx, rows = _measure_sql(conn, sql, (kw, kw))
        print(f"\n[gen n={n:,}] COUNT(*) filtered:      {_fmt(avg, mn, mx)}")

    def test_18_step_breakdown_path_query(self, gen_db):
        conn, n, _ = gen_db
        kw = "%folder01%"
        cur = conn.cursor()

        print(f"\n[gen n={n:,}] === Step Breakdown ===")

        avg1, mn1, mx1, rows1 = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"  Step1 path_subquery:      {_fmt(avg1, mn1, mx1, rows1)}")

        path_q = SQL_TEXT_FILTER_SINGLE
        sql2 = SQL_FETCH_BASIC.format(path_query=path_q)
        avg2, mn2, mx2, rows2 = _measure_sql(conn, sql2, (kw, kw))
        print(f"  Step2 JOIN files_full:    {_fmt(avg2, mn2, mx2, rows2)}")

        sql3 = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        avg3, mn3, mx3, rows3 = _measure_sql(conn, sql3, (kw, kw, "modified", "modified"))
        print(f"  Step3 + SQL sort mod:     {_fmt(avg3, mn3, mx3, rows3)}")

        sql4 = SQL_FETCH_SORT_NAME_COL.format(path_query=path_q)
        from wafer.utils.formatting import natural_key

        def run_py_sort():
            rows = list(cur.execute(sql4, (kw, kw, "name", "name")).fetchall())
            rows.sort(key=lambda r: natural_key(r["name"] or ""))
            return rows

        avg4, mn4, mx4, result4 = _measure(run_py_sort)
        print(f"  Step4 + Py sort name:     {_fmt(avg4, mn4, mx4, len(result4))}")

    def test_19_multi_key_search(self, gen_db):
        conn, n, _ = gen_db
        kw = "%img_0001%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_MULTI_KEY_SEARCH, (kw, kw))
        print(f"\n[gen n={n:,}] Multi-key search:       {_fmt(avg, mn, mx, rows)}")

    def test_20_explain_query_plan(self, gen_db):
        conn, n, _ = gen_db
        if n != GENERATED_SIZES[0]:
            pytest.skip("explain only on smallest")
        kw = "%folder01%"
        cur = conn.cursor()

        queries = {
            "text_filter": (SQL_TEXT_FILTER_SINGLE, (kw, kw)),
            "dir_filter": (SQL_DIR_FILTER, ("C:/images/folder010/%",)),
            "full_fetch": (SQL_FETCH_BASIC.format(path_query=SQL_ALL_PATHS), ()),
            "sort_modified": (SQL_FETCH_SORT_MODIFIED.format(path_query=SQL_ALL_PATHS), ("modified", "modified")),
            "list_keys": (SQL_LIST_ALL_KEYS.format(path_query=SQL_ALL_PATHS), ()),
        }
        print(f"\n[gen n={n:,}] === EXPLAIN QUERY PLAN ===")
        for name, (sql, params) in queries.items():
            print(f"\n  --- {name} ---")
            for row in cur.execute(f"EXPLAIN QUERY PLAN {sql}", params):
                print(f"    {dict(row)}")


class TestRealDB:
    def test_01_full_scan_no_filter(self, real_db):
        conn, n, name = real_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_BASIC.format(path_query=path_q)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[{name} n={n:,}] Full scan:              {_fmt(avg, mn, mx, rows)}")

    def test_02_text_single_keyword(self, real_db):
        conn, n, name = real_db
        first_name = conn.execute("SELECT value FROM meta_info WHERE key='name' LIMIT 1").fetchone()
        if not first_name:
            pytest.skip("no name metadata")
        fragment = first_name[0][:6]
        kw = f"%{fragment}%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"\n[{name} n={n:,}] Text filter ({fragment}):  {_fmt(avg, mn, mx, rows)}")

    def test_03_text_broad_keyword(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"\n[{name} n={n:,}] Text broad (.png):     {_fmt(avg, mn, mx, rows)}")

    def test_04_dir_filter(self, real_db):
        conn, n, name = real_db
        sample = conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("no files")
        parts = sample[0].replace("\\", "/").split("/")
        if len(parts) >= 3:
            d = "/".join(parts[:3]) + "/%"
        else:
            d = parts[0] + "/%"
        d_escaped = d.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        d_escaped = d_escaped[:-2] + "%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_DIR_FILTER, (d,))
        print(f"\n[{name} n={n:,}] Dir filter:             {_fmt(avg, mn, mx, rows)}")

    def test_05_full_fetch_sort_modified(self, real_db):
        conn, n, name = real_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        avg, mn, mx, rows = _measure_sql(conn, sql, ("modified", "modified"))
        print(f"\n[{name} n={n:,}] Full + sort modified:   {_fmt(avg, mn, mx, rows)}")

    def test_06_full_fetch_sort_name_python(self, real_db):
        conn, n, name = real_db
        from wafer.utils.formatting import natural_key

        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_NAME_COL.format(path_query=path_q)

        def run():
            rows = list(conn.execute(sql, ("name", "name")).fetchall())
            rows.sort(key=lambda r: natural_key(r["name"] or ""))
            return rows

        avg, mn, mx, result = _measure(run)
        print(f"\n[{name} n={n:,}] Full + name (python):   {_fmt(avg, mn, mx, len(result))}")

    def test_07_list_all_keys_full(self, real_db):
        conn, n, name = real_db
        sql = SQL_LIST_ALL_KEYS.format(path_query=SQL_ALL_PATHS)
        avg, mn, mx, rows = _measure_sql(conn, sql)
        print(f"\n[{name} n={n:,}] list_all_keys (full):   {_fmt(avg, mn, mx, rows)}")

    def test_08_step_breakdown(self, real_db):
        conn, n, name = real_db
        first_name = conn.execute("SELECT value FROM meta_info WHERE key='name' LIMIT 1").fetchone()
        if not first_name:
            pytest.skip("no name metadata")
        fragment = first_name[0][:6]
        kw = f"%{fragment}%"
        cur = conn.cursor()

        print(f"\n[{name} n={n:,}] === Step Breakdown (kw={fragment}) ===")

        avg1, mn1, mx1, rows1 = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"  Step1 path_subquery:      {_fmt(avg1, mn1, mx1, rows1)}")

        path_q = SQL_TEXT_FILTER_SINGLE
        sql2 = SQL_FETCH_BASIC.format(path_query=path_q)
        avg2, mn2, mx2, rows2 = _measure_sql(conn, sql2, (kw, kw))
        print(f"  Step2 JOIN files_full:    {_fmt(avg2, mn2, mx2, rows2)}")

        sql3 = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        avg3, mn3, mx3, rows3 = _measure_sql(conn, sql3, (kw, kw, "modified", "modified"))
        print(f"  Step3 + SQL sort mod:     {_fmt(avg3, mn3, mx3, rows3)}")

        sql4 = SQL_FETCH_SORT_NAME_COL.format(path_query=path_q)
        from wafer.utils.formatting import natural_key

        def run_py_sort():
            rows = list(cur.execute(sql4, (kw, kw, "name", "name")).fetchall())
            rows.sort(key=lambda r: natural_key(r["name"] or ""))
            return rows

        avg4, mn4, mx4, result4 = _measure(run_py_sort)
        print(f"  Step4 + Py sort name:     {_fmt(avg4, mn4, mx4, len(result4))}")

    def test_09_explain_query_plan(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        cur = conn.cursor()
        sample = conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        d = "/".join(sample[0].replace("\\", "/").split("/")[:3]) + "/%" if sample else "X/%"

        queries = {
            "text_filter": (SQL_TEXT_FILTER_SINGLE, (kw, kw)),
            "dir_filter": (SQL_DIR_FILTER, (d,)),
            "full_fetch": (SQL_FETCH_BASIC.format(path_query=SQL_ALL_PATHS), ()),
            "sort_modified": (SQL_FETCH_SORT_MODIFIED.format(path_query=SQL_ALL_PATHS), ("modified", "modified")),
            "list_keys": (SQL_LIST_ALL_KEYS.format(path_query=SQL_ALL_PATHS), ()),
        }
        print(f"\n[{name} n={n:,}] === EXPLAIN QUERY PLAN ===")
        for qname, (sql, params) in queries.items():
            print(f"\n  --- {qname} ---")
            for row in cur.execute(f"EXPLAIN QUERY PLAN {sql}", params):
                print(f"    {dict(row)}")

    def test_10_full_fetch_sort_size(self, real_db):
        conn, n, name = real_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q).replace("modified", "size")
        avg, mn, mx, rows = _measure_sql(conn, sql, ("size", "size"))
        print(f"\n[{name} n={n:,}] Full + sort size:       {_fmt(avg, mn, mx, rows)}")

    def test_11_full_fetch_sort_created(self, real_db):
        conn, n, name = real_db
        path_q = SQL_ALL_PATHS
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q).replace("modified", "created")
        avg, mn, mx, rows = _measure_sql(conn, sql, ("created", "created"))
        print(f"\n[{name} n={n:,}] Full + sort created:    {_fmt(avg, mn, mx, rows)}")

    def test_12_multi_key_search(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        avg, mn, mx, rows = _measure_sql(conn, SQL_MULTI_KEY_SEARCH, (kw, kw))
        print(f"\n[{name} n={n:,}] Multi-key search:       {_fmt(avg, mn, mx, rows)}")

    def test_13_text_filter_name_only(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        sql = """
        SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" = 'name' AND (mi."value" LIKE ? ESCAPE '\\')
        )
        """
        avg, mn, mx, rows = _measure_sql(conn, sql, (kw,))
        print(f"\n[{name} n={n:,}] Name-only filter:       {_fmt(avg, mn, mx, rows)}")

    def test_14_text_filter_path_only(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        sql = """
        SELECT DISTINCT path FROM (
            SELECT mi.path FROM meta_info AS mi
            WHERE mi."key" = 'path' AND (mi."value" LIKE ? ESCAPE '\\')
        )
        """
        avg, mn, mx, rows = _measure_sql(conn, sql, (kw,))
        print(f"\n[{name} n={n:,}] Path-only filter:       {_fmt(avg, mn, mx, rows)}")

    def test_15_composer_full_pipeline(self, real_db):
        conn, n, name = real_db
        kw = "%.png%"
        text_q = SQL_TEXT_FILTER_SINGLE
        full_sql = SQL_FETCH_SORT_MODIFIED.format(path_query=text_q)
        avg, mn, mx, rows = _measure_sql(conn, full_sql, (kw, kw, "modified", "modified"))
        print(f"\n[{name} n={n:,}] Full pipeline (text+sort): {_fmt(avg, mn, mx, rows)}")


class TestPragmaImpact:
    def test_cache_size_impact(self, gen_db):
        conn, n, db_path = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        kw = "%folder01%"
        path_q = SQL_TEXT_FILTER_SINGLE
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        params = (kw, kw, "modified", "modified")

        print(f"\n[gen n={n:,}] === Cache Size Impact ===")
        for cache_kb in [2000, 10000, 50000, 100000]:
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.row_factory = sqlite3.Row
            conn2.execute(f"PRAGMA cache_size=-{cache_kb}")
            conn2.execute("PRAGMA temp_store=MEMORY")
            conn2.execute("PRAGMA mmap_size=134217728")
            avg, mn, mx, rows = _measure_sql(conn2, sql, params)
            conn2.close()
            print(f"  cache={cache_kb}KB: {_fmt(avg, mn, mx, rows)}")

    def test_mmap_impact(self, gen_db):
        conn, n, db_path = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        kw = "%folder01%"
        path_q = SQL_TEXT_FILTER_SINGLE
        sql = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        params = (kw, kw, "modified", "modified")

        print(f"\n[gen n={n:,}] === mmap_size Impact ===")
        for mmap_mb in [0, 64, 128, 256, 512]:
            conn2 = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn2.row_factory = sqlite3.Row
            conn2.execute("PRAGMA cache_size=-10000")
            conn2.execute("PRAGMA temp_store=MEMORY")
            conn2.execute(f"PRAGMA mmap_size={mmap_mb * 1024 * 1024}")
            avg, mn, mx, rows = _measure_sql(conn2, sql, params)
            conn2.close()
            print(f"  mmap={mmap_mb}MB: {_fmt(avg, mn, mx, rows)}")


class TestAlternativeApproaches:
    def test_covering_index_simulation(self, gen_db):
        conn, n, db_path = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        conn2 = sqlite3.connect(db_path)
        conn2.row_factory = sqlite3.Row
        apply_read_pragmas(conn2)

        conn2.execute("PRAGMA query_only=OFF")
        conn2.execute("CREATE INDEX IF NOT EXISTS idx_meta_info_covering ON meta_info(key, value, path)")
        conn2.execute("ANALYZE")
        conn2.execute("PRAGMA query_only=ON")

        kw = "%folder01%"
        print(f"\n[gen n={n:,}] === Covering Index Test ===")

        avg1, mn1, mx1, rows1 = _measure_sql(conn, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        avg2, mn2, mx2, rows2 = _measure_sql(conn2, SQL_TEXT_FILTER_SINGLE, (kw, kw))
        print(f"  Original:   {_fmt(avg1, mn1, mx1, rows1)}")
        print(f"  +Covering:  {_fmt(avg2, mn2, mx2, rows2)}")
        ratio = avg2 / avg1 if avg1 > 0 else float("inf")
        print(f"  Ratio: {ratio:.2f}x")

        conn2.close()

    def test_meta_info_value_startswith(self, gen_db):
        conn, n, _ = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        kw_like = "%folder010%"
        kw_prefix = "C:/images/folder010/%"
        print(f"\n[gen n={n:,}] === LIKE vs prefix match ===")

        avg1, mn1, mx1, rows1 = _measure_sql(
            conn,
            "SELECT DISTINCT mi.path FROM meta_info AS mi WHERE mi.key='path' AND mi.value LIKE ? ESCAPE '\\'",
            (kw_like,),
        )
        avg2, mn2, mx2, rows2 = _measure_sql(
            conn,
            "SELECT DISTINCT mi.path FROM meta_info AS mi WHERE mi.key='path' AND mi.value >= ? AND mi.value < ?",
            ("C:/images/folder010/", "C:/images/folder010" + chr(0x10FFFF)),
        )
        print(f"  LIKE infix:  {_fmt(avg1, mn1, mx1, rows1)}")
        print(f"  Range prefix:{_fmt(avg2, mn2, mx2, rows2)}")

    def test_sort_sql_vs_python_natural(self, gen_db):
        conn, n, _ = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        from wafer.utils.formatting import natural_key

        path_q = SQL_ALL_PATHS

        sql_only = SQL_FETCH_SORT_MODIFIED.format(path_query=path_q)
        avg1, mn1, mx1, rows1 = _measure_sql(conn, sql_only, ("modified", "modified"))

        sql_fetch = SQL_FETCH_SORT_NAME_COL.format(path_query=path_q)

        def py_sort():
            rows = list(conn.execute(sql_fetch, ("name", "name")).fetchall())
            rows.sort(key=lambda r: natural_key(r["name"] or ""))
            return rows

        avg2, mn2, mx2, result2 = _measure(py_sort)

        sql_nosort = SQL_FETCH_BASIC.format(path_query=path_q)
        avg3, mn3, mx3, rows3 = _measure_sql(conn, sql_nosort)

        print(f"\n[gen n={n:,}] === Sort Cost Comparison ===")
        print(f"  No sort:        {_fmt(avg3, mn3, mx3, rows3)}")
        print(f"  SQL sort (mod): {_fmt(avg1, mn1, mx1, rows1)}")
        print(f"  Python natural: {_fmt(avg2, mn2, mx2, len(result2))}")
        print(f"  Sort overhead (SQL):  {(avg1 - avg3) * 1000:.2f}ms")
        print(f"  Sort overhead (Py):   {(avg2 - avg3) * 1000:.2f}ms")

    def test_files_full_view_vs_direct_join(self, gen_db):
        conn, n, _ = gen_db
        if n != GENERATED_SIZES[-1]:
            pytest.skip("only largest")

        path_q = SQL_ALL_PATHS
        sql_view = f"""
        SELECT m.path, m.source, m.aspect_ratio
        FROM files_full AS m JOIN ({path_q}) AS s USING(path)
        """
        sql_direct = f"""
        SELECT f.path, f.source, f.aspect_ratio
        FROM files AS f
        JOIN sources AS s ON s.source = f.source
        JOIN ({path_q}) AS s2 ON s2.path = f.path
        """

        print(f"\n[gen n={n:,}] === files_full view vs direct join ===")
        avg1, mn1, mx1, rows1 = _measure_sql(conn, sql_view)
        avg2, mn2, mx2, rows2 = _measure_sql(conn, sql_direct)
        print(f"  files_full view: {_fmt(avg1, mn1, mx1, rows1)}")
        print(f"  Direct join:     {_fmt(avg2, mn2, mx2, rows2)}")

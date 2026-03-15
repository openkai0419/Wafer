from __future__ import annotations

import hashlib
import os
import re
import sqlite3
import time
from pathlib import Path

import pytest

from wafer.core.db.db_utils import apply_read_pragmas, apply_write_pragmas


SIZES = [1000, 5000, 10000, 50000]
WARMUP = 1
ITERATIONS = 5
PATTERN = r'\d{4}_sunset'
HIT_RATIO = 0.1


def _setup_db(tmp_path, n):
    db_path = tmp_path / f'bench_{n}.db'
    conn = sqlite3.connect(str(db_path))
    apply_write_pragmas(conn)
    conn.execute('CREATE TABLE IF NOT EXISTS hash_index (file_hash TEXT PRIMARY KEY)')
    conn.execute('''CREATE TABLE IF NOT EXISTS sources (
        source TEXT PRIMARY KEY,
        file_hash TEXT NOT NULL,
        size INTEGER, modified REAL, created REAL, collected REAL, status TEXT,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS files (
        path TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        name TEXT,
        aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path))''')
    conn.execute('''CREATE TABLE IF NOT EXISTS tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))''')
    conn.execute('''CREATE VIEW IF NOT EXISTS files_full AS
        SELECT i.path, i.source, i.name, i.aspect_ratio,
               s.file_hash, s.size, s.modified, s.created, s.collected, s.status
        FROM files i JOIN sources s ON s.source = i.source''')
    conn.executescript('''
        CREATE INDEX IF NOT EXISTS idx_meta_info_key_fid ON meta_info(key, path);
        CREATE INDEX IF NOT EXISTS idx_tags_key_fid ON tags(key, file_hash);
    ''')

    hit_count = int(n * HIT_RATIO)
    sources_rows = []
    files_rows = []
    meta_rows = []
    tag_rows = []
    hash_rows = []

    for i in range(n):
        fhash = hashlib.md5(f'file_{i}'.encode()).hexdigest()
        source = f'c:/photos/dir_{i % 100}/file_{i}.jpg'
        if i < hit_count:
            path = f'c:/photos/dir_{i % 100}/{i:04d}_sunset_beach_{i}.jpg'
            meta_val = f'tag_{i:04d}_sunset_glow'
        else:
            path = f'c:/photos/dir_{i % 100}/normal_photo_{i}.jpg'
            meta_val = f'tag_normal_description_{i}'
        name = os.path.basename(path)
        hash_rows.append((fhash,))
        sources_rows.append((source, fhash, 1024 * i, float(i), float(i), float(i), 'ok'))
        files_rows.append((path, source, name, 1.5))
        meta_rows.append((path, 'description', meta_val))
        tag_rows.append((fhash, 'category', meta_val))

    conn.executemany('INSERT INTO hash_index VALUES (?)', hash_rows)
    conn.executemany('INSERT INTO sources VALUES (?,?,?,?,?,?,?)', sources_rows)
    conn.executemany('INSERT INTO files VALUES (?,?,?,?)', files_rows)
    conn.executemany('INSERT INTO meta_info VALUES (?,?,?)', meta_rows)
    conn.executemany('INSERT INTO tags VALUES (?,?,?)', tag_rows)
    conn.commit()
    conn.close()
    return db_path


def _open_readonly(db_path):
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    apply_read_pragmas(conn)
    return conn


def _regex_func(pattern, value):
    if value is None:
        return False
    return bool(re.search(pattern, value))


def _open_readonly_with_regexp(db_path):
    conn = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True)
    conn.row_factory = sqlite3.Row
    conn.create_function('regexp', 2, _regex_func, deterministic=True)
    apply_read_pragmas(conn)
    return conn


def _timeit(func, warmup=WARMUP, iterations=ITERATIONS):
    for _ in range(warmup):
        func()
    times = []
    for _ in range(iterations):
        start = time.perf_counter()
        result = func()
        elapsed = time.perf_counter() - start
        times.append(elapsed)
    avg = sum(times) / len(times)
    best = min(times)
    return avg, best, result


def approach_a_post_filter(conn, pattern):
    compiled = re.compile(pattern)
    rows = conn.execute('SELECT path FROM files').fetchall()
    return [r['path'] for r in rows if compiled.search(r['path'])]


def approach_a_post_filter_meta(conn, pattern, keys):
    compiled = re.compile(pattern)
    paths_from_files = conn.execute('SELECT path FROM files').fetchall()
    matched_paths = {r['path'] for r in paths_from_files if compiled.search(r['path'])}

    if keys:
        placeholders = ','.join('?' for _ in keys)
        meta_rows = conn.execute(
            f'SELECT path, value FROM meta_info WHERE key IN ({placeholders})', keys
        ).fetchall()
        for r in meta_rows:
            if compiled.search(r['value'] or ''):
                matched_paths.add(r['path'])

        tag_rows = conn.execute(
            f'''SELECT i.path, t.value FROM tags AS t
                JOIN sources AS s ON s.file_hash = t.file_hash
                JOIN files AS i ON i.source = s.source
                WHERE t.key IN ({placeholders})''', keys
        ).fetchall()
        for r in tag_rows:
            if compiled.search(r['value'] or ''):
                matched_paths.add(r['path'])

    return list(matched_paths)


def approach_b_like_then_post_filter(conn, pattern, like_hint):
    compiled = re.compile(pattern)
    esc = like_hint.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    rows = conn.execute(
        "SELECT path FROM files WHERE path LIKE ? ESCAPE '\\'",
        (f'%{esc}%',)
    ).fetchall()
    return [r['path'] for r in rows if compiled.search(r['path'])]


def approach_b_like_then_post_filter_meta(conn, pattern, like_hint, keys):
    compiled = re.compile(pattern)
    esc = like_hint.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')

    rows = conn.execute(
        "SELECT path FROM files WHERE path LIKE ? ESCAPE '\\'",
        (f'%{esc}%',)
    ).fetchall()
    matched_paths = {r['path'] for r in rows if compiled.search(r['path'])}

    if keys:
        placeholders = ','.join('?' for _ in keys)
        meta_rows = conn.execute(
            f"SELECT path, value FROM meta_info WHERE key IN ({placeholders}) AND value LIKE ? ESCAPE '\\'",
            [*keys, f'%{esc}%']
        ).fetchall()
        for r in meta_rows:
            if compiled.search(r['value'] or ''):
                matched_paths.add(r['path'])

        tag_rows = conn.execute(
            f'''SELECT i.path, t.value FROM tags AS t
                JOIN sources AS s ON s.file_hash = t.file_hash
                JOIN files AS i ON i.source = s.source
                WHERE t.key IN ({placeholders}) AND t.value LIKE ? ESCAPE '\\' ''',
            [*keys, f'%{esc}%']
        ).fetchall()
        for r in tag_rows:
            if compiled.search(r['value'] or ''):
                matched_paths.add(r['path'])

    return list(matched_paths)


def approach_c_sql_regexp(conn, pattern):
    rows = conn.execute(
        'SELECT DISTINCT path FROM files WHERE path REGEXP ?', (pattern,)
    ).fetchall()
    return [r['path'] for r in rows]


def approach_c_sql_regexp_meta(conn, pattern, keys):
    parts = []
    params = []

    parts.append('SELECT path FROM files WHERE path REGEXP ?')
    params.append(pattern)

    if keys:
        placeholders = ','.join('?' for _ in keys)
        parts.append(
            f'SELECT path FROM meta_info WHERE key IN ({placeholders}) AND value REGEXP ?'
        )
        params.extend(keys)
        params.append(pattern)
        parts.append(
            f'''SELECT i.path FROM tags AS t
                JOIN sources AS s ON s.file_hash = t.file_hash
                JOIN files AS i ON i.source = s.source
                WHERE t.key IN ({placeholders}) AND t.value REGEXP ?'''
        )
        params.extend(keys)
        params.append(pattern)

    sql = f"SELECT DISTINCT path FROM ({' UNION ALL '.join(parts)})"
    rows = conn.execute(sql, params).fetchall()
    return [r['path'] for r in rows]


def _extract_like_hint(pattern):
    literals = re.findall(r'[A-Za-z0-9_]+', pattern)
    return max(literals, key=len) if literals else ''


@pytest.mark.parametrize('n', SIZES)
class TestRegexBenchmark:

    def test_path_only(self, tmp_path, n):
        db_path = _setup_db(tmp_path, n)
        pattern = PATTERN
        like_hint = _extract_like_hint(pattern)

        conn_plain = _open_readonly(db_path)
        conn_regexp = _open_readonly_with_regexp(db_path)

        avg_a, best_a, res_a = _timeit(lambda: approach_a_post_filter(conn_plain, pattern))
        avg_b, best_b, res_b = _timeit(lambda: approach_b_like_then_post_filter(conn_plain, pattern, like_hint))
        avg_c, best_c, res_c = _timeit(lambda: approach_c_sql_regexp(conn_regexp, pattern))

        assert set(res_a) == set(res_b) == set(res_c), (
            f'Result mismatch: A={len(res_a)}, B={len(res_b)}, C={len(res_c)}'
        )

        expected_hits = int(n * HIT_RATIO)
        assert len(res_a) == expected_hits, f'Expected {expected_hits} hits, got {len(res_a)}'

        print(f'\n=== path_only  n={n:>6}  expected_hits={expected_hits} ===')
        print(f'  A (post_filter):     avg={avg_a*1000:8.2f}ms  best={best_a*1000:8.2f}ms')
        print(f'  B (LIKE+post):       avg={avg_b*1000:8.2f}ms  best={best_b*1000:8.2f}ms')
        print(f'  C (SQL REGEXP):      avg={avg_c*1000:8.2f}ms  best={best_c*1000:8.2f}ms')

        conn_plain.close()
        conn_regexp.close()

    def test_path_and_meta(self, tmp_path, n):
        db_path = _setup_db(tmp_path, n)
        pattern = PATTERN
        like_hint = _extract_like_hint(pattern)
        keys = ['description', 'category']

        conn_plain = _open_readonly(db_path)
        conn_regexp = _open_readonly_with_regexp(db_path)

        avg_a, best_a, res_a = _timeit(lambda: approach_a_post_filter_meta(conn_plain, pattern, keys))
        avg_b, best_b, res_b = _timeit(lambda: approach_b_like_then_post_filter_meta(conn_plain, pattern, like_hint, keys))
        avg_c, best_c, res_c = _timeit(lambda: approach_c_sql_regexp_meta(conn_regexp, pattern, keys))

        assert set(res_a) == set(res_b) == set(res_c), (
            f'Result mismatch: A={len(res_a)}, B={len(res_b)}, C={len(res_c)}'
        )

        expected_hits = int(n * HIT_RATIO)
        assert len(res_a) == expected_hits, f'Expected {expected_hits} hits, got {len(res_a)}'

        print(f'\n=== path+meta  n={n:>6}  expected_hits={expected_hits} ===')
        print(f'  A (post_filter):     avg={avg_a*1000:8.2f}ms  best={best_a*1000:8.2f}ms')
        print(f'  B (LIKE+post):       avg={avg_b*1000:8.2f}ms  best={best_b*1000:8.2f}ms')
        print(f'  C (SQL REGEXP):      avg={avg_c*1000:8.2f}ms  best={best_c*1000:8.2f}ms')

        conn_plain.close()
        conn_regexp.close()

    def test_complex_pattern(self, tmp_path, n):
        db_path = _setup_db(tmp_path, n)
        complex_pattern = r'(sunset|beach).*\d{3}'
        like_hint = 'sunset'
        keys = ['description', 'category']

        conn_plain = _open_readonly(db_path)
        conn_regexp = _open_readonly_with_regexp(db_path)

        avg_a, best_a, res_a = _timeit(lambda: approach_a_post_filter_meta(conn_plain, complex_pattern, keys))
        avg_b, best_b, res_b = _timeit(lambda: approach_b_like_then_post_filter_meta(conn_plain, complex_pattern, like_hint, keys))
        avg_c, best_c, res_c = _timeit(lambda: approach_c_sql_regexp_meta(conn_regexp, complex_pattern, keys))

        assert set(res_a) == set(res_b) == set(res_c), (
            f'Result mismatch: A={len(res_a)}, B={len(res_b)}, C={len(res_c)}'
        )

        print(f'\n=== complex    n={n:>6}  hits={len(res_a)} ===')
        print(f'  A (post_filter):     avg={avg_a*1000:8.2f}ms  best={best_a*1000:8.2f}ms')
        print(f'  B (LIKE+post):       avg={avg_b*1000:8.2f}ms  best={best_b*1000:8.2f}ms')
        print(f'  C (SQL REGEXP):      avg={avg_c*1000:8.2f}ms  best={best_c*1000:8.2f}ms')

        conn_plain.close()
        conn_regexp.close()

    def test_no_match_pattern(self, tmp_path, n):
        db_path = _setup_db(tmp_path, n)
        pattern = r'zzz_nonexistent_\d+'
        like_hint = 'zzz_nonexistent_'
        keys = ['description', 'category']

        conn_plain = _open_readonly(db_path)
        conn_regexp = _open_readonly_with_regexp(db_path)

        avg_a, best_a, res_a = _timeit(lambda: approach_a_post_filter_meta(conn_plain, pattern, keys))
        avg_b, best_b, res_b = _timeit(lambda: approach_b_like_then_post_filter_meta(conn_plain, pattern, like_hint, keys))
        avg_c, best_c, res_c = _timeit(lambda: approach_c_sql_regexp_meta(conn_regexp, pattern, keys))

        assert len(res_a) == 0
        assert set(res_a) == set(res_b) == set(res_c)

        print(f'\n=== no_match   n={n:>6}  hits=0 ===')
        print(f'  A (post_filter):     avg={avg_a*1000:8.2f}ms  best={best_a*1000:8.2f}ms')
        print(f'  B (LIKE+post):       avg={avg_b*1000:8.2f}ms  best={best_b*1000:8.2f}ms')
        print(f'  C (SQL REGEXP):      avg={avg_c*1000:8.2f}ms  best={best_c*1000:8.2f}ms')

        conn_plain.close()
        conn_regexp.close()

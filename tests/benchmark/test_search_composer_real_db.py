from __future__ import annotations

import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import pytest

from wafer.builtins.filters import DirectoryFilter, SourceChildrenFilter, TextFilter
from wafer.builtins.sorts import ModifiedSort, NaturalNameSort, NaturalPathSort, SizeSort
from wafer.core.db.query import FileSearchEngine
from wafer.plugin.query.base import BaseSortPlugin
from wafer.plugin.query.composer import SearchComposer
from wafer.utils.paths import resolve_data_path

pytestmark = pytest.mark.benchmark


def _resolve_real_db_dir() -> Path:
    configured = os.environ.get("WAFER_DATA_DIR", "").strip()
    return Path(configured) if configured else Path(resolve_data_path("data/"))


REAL_DB_DIR = _resolve_real_db_dir()
REAL_DBS = tuple(name.strip() for name in os.environ.get("WAFER_REAL_BENCH_DBS", "default,nai,sample,temp").split(",") if name.strip())
WARMUP = int(os.environ.get("WAFER_REAL_BENCH_WARMUP", "1"))
ITERATIONS = int(os.environ.get("WAFER_REAL_BENCH_ITERATIONS", "3"))


class NoSort(BaseSortPlugin):
    NAME = "none"
    PRIORITY = 0


@dataclass(frozen=True)
class RealDBCase:
    name: str
    path: Path
    engine: FileSearchEngine
    rows: int


def _measure(func):
    for _ in range(WARMUP):
        func()
    times = []
    result = None
    for _ in range(ITERATIONS):
        t0 = time.perf_counter()
        result = func()
        times.append(time.perf_counter() - t0)
    return sum(times) / len(times), min(times), max(times), result


def _fmt(avg, mn, mx, rows=None):
    row_text = f" rows={rows}" if rows is not None else ""
    return f"avg={avg * 1000:.2f}ms min={mn * 1000:.2f} max={mx * 1000:.2f}{row_text}"


def _execute(engine, entries, sort_cls=NoSort, ascending=True):
    paths, _, _ = SearchComposer().execute(engine, entries, sort_cls, ascending)
    return paths


def _bench_execute(label, db, entries, sort_cls=NoSort, ascending=True):
    avg, mn, mx, paths = _measure(lambda: _execute(db.engine, entries, sort_cls, ascending))
    print(f"  {label:<32} {_fmt(avg, mn, mx, len(paths))}")
    return paths, avg


def _bench_keys(label, db, entries):
    avg, mn, mx, keys = _measure(lambda: SearchComposer().list_all_keys(db.engine, entries, sort_by_freq=True))
    print(f"  {label:<32} {_fmt(avg, mn, mx, len(keys))}")
    return keys, avg


def _path_parts(path: str) -> list[str]:
    return [part for part in path.replace("\\", "/").split("/") if part]


def _prefix(path: str, depth: int) -> str | None:
    parts = _path_parts(path)
    if len(parts) <= depth:
        return None
    return "/".join(parts[:depth])


def _broad_directory(conn) -> str | None:
    counts = Counter()
    for (path,) in conn.execute("SELECT path FROM files"):
        for depth in range(2, min(6, len(_path_parts(path)))):
            prefix = _prefix(path, depth)
            if prefix:
                counts[prefix] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _direct_directory(conn) -> str | None:
    counts = Counter()
    for (path,) in conn.execute("SELECT path FROM files"):
        parent = path.replace("\\", "/").rsplit("/", 1)[0] if "/" in path.replace("\\", "/") else ""
        if parent:
            counts[parent] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _top_name_suffix(conn) -> str | None:
    counts = Counter()
    for (name,) in conn.execute("SELECT name FROM files"):
        suffix = Path(name or "").suffix.lower()
        if suffix:
            counts[suffix] += 1
    if not counts:
        return None
    return counts.most_common(1)[0][0]


def _top_virtual_source(conn) -> tuple[str, int] | None:
    row = conn.execute("SELECT source, COUNT(*) AS n FROM files WHERE path LIKE '%::%' GROUP BY source ORDER BY n DESC LIMIT 1").fetchone()
    if not row:
        return None
    return row["source"], row["n"]


@pytest.fixture(params=REAL_DBS, scope="module")
def real_composer_db(request):
    name = request.param
    path = REAL_DB_DIR / f"{name}.db"
    if not path.exists():
        pytest.skip(f"{path} not found")
    engine = FileSearchEngine(path)
    if not engine._connect_if_needed():
        pytest.skip(f"{path} could not be opened")
    rows = engine.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    yield RealDBCase(name=name, path=path, engine=engine, rows=rows)
    engine.close()


class TestSearchComposerRealDB:
    def test_full_fetch_sort_matrix(self, real_composer_db):
        db = real_composer_db
        print(f"\n[{db.name} n={db.rows:,}] === SearchComposer full fetch / sort matrix ===")
        _bench_execute("no sort", db, [], NoSort)
        _bench_execute("natural path", db, [], NaturalPathSort)
        _bench_execute("natural name", db, [], NaturalNameSort)
        _bench_execute("modified desc", db, [], ModifiedSort, False)
        _bench_execute("size desc", db, [], SizeSort, False)

    def test_text_directory_and_key_scope(self, real_composer_db):
        db = real_composer_db
        conn = db.engine.conn
        suffix = _top_name_suffix(conn)
        broad_dir = _broad_directory(conn)
        direct_dir = _direct_directory(conn)
        print(f"\n[{db.name} n={db.rows:,}] === SearchComposer filters / key scope ===")
        if suffix:
            text_entries = [(TextFilter, {"keys": ["name"], "keywords": suffix, "query_mode": "LIKE", "keyword_mode": "OR", "require_keys": True}, None)]
            _bench_execute(f"text name {suffix} no sort", db, text_entries, NoSort)
            _bench_execute(f"text name {suffix} modified", db, text_entries, ModifiedSort, False)
        if broad_dir:
            entries = [(DirectoryFilter, {"directories": [broad_dir], "include_subfolders": True}, None)]
            _bench_execute("broad dir include_subfolders", db, entries, NoSort)
            _bench_keys("keys broad dir", db, entries)
        if direct_dir:
            entries_true = [(DirectoryFilter, {"directories": [direct_dir], "include_subfolders": True}, None)]
            entries_false = [(DirectoryFilter, {"directories": [direct_dir], "include_subfolders": False}, None)]
            _bench_execute("direct dir include_subfolders", db, entries_true, NoSort)
            _bench_execute("direct dir no subfolders", db, entries_false, NoSort)
        _bench_keys("keys full", db, [])

    def test_virtual_source_children(self, real_composer_db):
        db = real_composer_db
        source = _top_virtual_source(db.engine.conn)
        if source is None:
            pytest.skip("no virtual paths")
        source_path, child_count = source
        parent = source_path.replace("\\", "/").rsplit("/", 1)[0]
        print(f"\n[{db.name} n={db.rows:,}] === SearchComposer virtual paths source_children={child_count:,} ===")
        source_entries = [(SourceChildrenFilter, {"source": source_path}, None)]
        _bench_execute("source children no sort", db, source_entries, NoSort)
        _bench_execute("source children natural name", db, source_entries, NaturalNameSort)
        _bench_execute("source children modified", db, source_entries, ModifiedSort, False)
        dir_entries = [(DirectoryFilter, {"directories": [parent], "include_subfolders": True}, None)]
        _bench_execute("parent dir virtual scope", db, dir_entries, NoSort)
        _bench_keys("keys parent dir virtual", db, dir_entries)

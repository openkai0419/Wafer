import os
import statistics
import time

import pytest

from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.utils.paths import normalize_path


def np(p):
    return normalize_path(p)


ITERATIONS = 10
FILE_COUNT_PER_DIR = 1000
DIRS = [
    "C:/photos/vacation_2023/day_1",
    "C:/photos/vacation_2023/day_2",
    "C:/photos/vacation_2023/day_10",
    "C:/photos/vacation_2023/day_20",
    "C:/photos/work/project_1",
    "C:/photos/work/project_2",
    "C:/photos/work/project_10",
    "C:/photos/personal/album_1",
    "C:/photos/personal/album_3",
    "C:/photos/personal/album_12",
]


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("profile")
    db_path = str(tmp / "profile.db")
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    sources, images, metas, tags = [], [], [], []
    idx = 0
    for d in DIRS:
        for i in range(FILE_COUNT_PER_DIR):
            num = i + 1
            name = f"IMG_{num}.jpg"
            path = f"{d}/{name}"
            fhash = f"hash_{idx:06d}"
            sources.append(
                (
                    path,
                    fhash,
                    1000 + idx,
                    float(1700000000 + idx),
                )
            )
            images.append((path, path, 1.0 + (idx % 10) * 0.1))
            metas.append((path, "path", path, None))
            metas.append((path, "name", name, None))
            metas.append((path, "dpi", f"{72 + (idx % 4) * 24}", None))
            metas.append((path, "size", str(1000 + idx), float(1000 + idx)))
            metas.append((path, "modified", str(float(1700000000 + idx)), float(1700000000 + idx)))
            metas.append((path, "created", str(float(1700000000 + idx)), float(1700000000 + idx)))
            metas.append((path, "collected", str(float(1700000000 + idx)), float(1700000000 + idx)))
            tags.append((fhash, "rating", f"{(idx % 5) + 1}", float((idx % 5) + 1)))
            idx += 1

    db.upsert_batches(sources, images, metas, tags)
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


@pytest.fixture
def real_db():
    path = os.environ.get("TEST_REAL_DB", "")
    if not path or not os.path.exists(path):
        pytest.skip("Set TEST_REAL_DB env var to a real .db path")
    return path


def _benchmark(engine, query, label, iterations=ITERATIONS):
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = engine.search(query)
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)

    avg = statistics.mean(times)
    median = statistics.median(times)
    best = min(times)
    worst = max(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0.0
    rows = len(result[0]) if result else 0
    print(f"\n  [{label}] rows={rows}  avg={avg:.2f}ms  median={median:.2f}ms  best={best:.2f}ms  worst={worst:.2f}ms  stdev={stdev:.2f}ms")
    return result, times


def _benchmark_multi(engine, queries, label, iterations=ITERATIONS):
    times = []
    result = None
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = engine.search_multi(queries)
        elapsed = (time.perf_counter() - t0) * 1000
        times.append(elapsed)

    avg = statistics.mean(times)
    median = statistics.median(times)
    best = min(times)
    worst = max(times)
    stdev = statistics.stdev(times) if len(times) > 1 else 0.0
    rows = len(result[0]) if result else 0
    print(f"\n  [{label}] rows={rows}  avg={avg:.2f}ms  median={median:.2f}ms  best={best:.2f}ms  worst={worst:.2f}ms  stdev={stdev:.2f}ms")
    return result, times


TOTAL_SYNTHETIC = FILE_COUNT_PER_DIR * len(DIRS)


class TestSortProfileSynthetic:
    @pytest.mark.parametrize(
        "sort_by,ascending",
        [
            ("name", True),
            ("name", False),
            ("path", True),
            ("path", False),
            ("modified", True),
            ("modified", False),
            ("created", True),
            ("size", True),
            ("random", True),
        ],
    )
    def test_sort_all_files(self, large_db, sort_by, ascending):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            sort_by=sort_by,
            ascending=ascending,
        )
        direction = "asc" if ascending else "desc"
        result, _ = _benchmark(engine, q, f"all_{sort_by}_{direction}")
        assert len(result[0]) == TOTAL_SYNTHETIC

    def test_sort_name_asc_with_keyword(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            keywords="vacation",
            sort_by="name",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, "keyword_vacation_name_asc")
        assert len(result[0]) == FILE_COUNT_PER_DIR * 4

    def test_sort_name_asc_with_directory(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            directories=["C:/photos/vacation_2023"],
            sort_by="name",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, "dir_vacation_name_asc")
        assert len(result[0]) == FILE_COUNT_PER_DIR * 4

    def test_sort_path_asc_with_directory(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            directories=["C:/photos/work"],
            sort_by="path",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, "dir_work_path_asc")
        assert len(result[0]) == FILE_COUNT_PER_DIR * 3

    def test_sort_name_asc_meta_key(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["dpi"],
            sort_by="name",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, "meta_dpi_name_asc")
        assert len(result[0]) == TOTAL_SYNTHETIC

    def test_sort_name_asc_tag_key(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["rating"],
            keywords="5",
            sort_by="name",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, "tag_rating5_name_asc")
        assert len(result[0]) > 0

    def test_sort_multi_query_intersect(self, large_db):
        engine = FileSearchEngine(large_db)
        q1 = SearchQuery(keys=["path"], append_mode="OR")
        q2 = SearchQuery(
            keys=["path"],
            keywords="vacation",
            sort_by="name",
            ascending=True,
            append_mode="AND",
        )
        result, _ = _benchmark_multi(engine, [q1, q2], "multi_intersect_name_asc")
        assert len(result[0]) == FILE_COUNT_PER_DIR * 4

    def test_sort_multi_query_union(self, large_db):
        engine = FileSearchEngine(large_db)
        q1 = SearchQuery(
            keys=["path"],
            keywords="vacation",
            sort_by="name",
            ascending=True,
            append_mode="OR",
        )
        q2 = SearchQuery(
            keys=["path"],
            keywords="work",
            sort_by="name",
            ascending=True,
            append_mode="OR",
        )
        result, _ = _benchmark_multi(engine, [q1, q2], "multi_union_name_asc")
        assert len(result[0]) == FILE_COUNT_PER_DIR * 7

    def test_verify_natural_order(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            directories=["C:/photos/vacation_2023/day_1"],
            sort_by="name",
            ascending=True,
        )
        paths, _, _ = engine.search(q)
        names = [os.path.basename(p) for p in paths]
        assert names[0] == "IMG_1.jpg"
        assert names[1] == "IMG_2.jpg"
        assert names[2] == "IMG_3.jpg"
        assert names[9] == "IMG_10.jpg"
        assert names[99] == "IMG_100.jpg"
        assert names[-1] == "IMG_1000.jpg"

    def test_verify_natural_order_desc(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            directories=["C:/photos/vacation_2023/day_1"],
            sort_by="name",
            ascending=False,
        )
        paths, _, _ = engine.search(q)
        names = [os.path.basename(p) for p in paths]
        assert names[0] == "IMG_1000.jpg"
        assert names[-1] == "IMG_1.jpg"

    def test_verify_natural_path_order(self, large_db):
        engine = FileSearchEngine(large_db)
        q = SearchQuery(
            keys=["path"],
            directories=["C:/photos/vacation_2023"],
            sort_by="path",
            ascending=True,
        )
        paths, _, _ = engine.search(q)
        assert "day_1/" in paths[0]
        assert "day_2/" in paths[FILE_COUNT_PER_DIR]
        assert "day_10/" in paths[FILE_COUNT_PER_DIR * 2]
        assert "day_20/" in paths[FILE_COUNT_PER_DIR * 3]


class TestSortProfileRealDB:
    @pytest.mark.parametrize(
        "sort_by,ascending",
        [
            ("name", True),
            ("name", False),
            ("path", True),
            ("path", False),
            ("modified", True),
            ("modified", False),
            ("created", True),
            ("size", True),
        ],
    )
    def test_sort_all(self, real_db, sort_by, ascending):
        engine = FileSearchEngine(real_db)
        q = SearchQuery(
            keys=["path"],
            sort_by=sort_by,
            ascending=ascending,
        )
        direction = "asc" if ascending else "desc"
        result, _ = _benchmark(engine, q, f"real_all_{sort_by}_{direction}")
        assert len(result[0]) > 0

    def test_sort_with_directory(self, real_db):
        engine = FileSearchEngine(real_db)
        assert engine._connect_if_needed()
        sample = engine.conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No data in real DB")
        parts = sample[0].replace("\\", "/").split("/")
        sample_dir = "/".join(parts[:4])

        for sort_by in ("name", "path"):
            q = SearchQuery(
                keys=["path"],
                directories=[sample_dir],
                sort_by=sort_by,
                ascending=True,
            )
            result, _ = _benchmark(engine, q, f"real_dir_{sort_by}_asc")
            assert len(result[0]) > 0

    def test_sort_with_keyword(self, real_db):
        engine = FileSearchEngine(real_db)
        assert engine._connect_if_needed()
        sample = engine.conn.execute("SELECT value FROM meta_info WHERE key = 'name' LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No data in real DB")
        fragment = sample[0][:3]

        q = SearchQuery(
            keys=["path"],
            keywords=fragment,
            sort_by="name",
            ascending=True,
        )
        result, _ = _benchmark(engine, q, f"real_keyword_{fragment}_name_asc")
        assert len(result[0]) > 0

    def test_db_stats(self, real_db):
        engine = FileSearchEngine(real_db)
        assert engine._connect_if_needed()
        cur = engine.conn.cursor()
        file_count = cur.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        meta_count = cur.execute("SELECT COUNT(*) FROM meta_info").fetchone()[0]
        tag_count = cur.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
        source_count = cur.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        print(f"\n  [DB stats] files={file_count}  meta_info={meta_count}  tags={tag_count}  sources={source_count}")

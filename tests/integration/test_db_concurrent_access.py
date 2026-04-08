import threading
import time

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.indexer import FileIndexer
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.collector_receiver import _parse_batch


def _create_test_image(path, width=100, height=80, fmt="JPEG"):
    Image.new("RGB", (width, height), color=(200, 100, 50)).save(str(path), format=fmt)


def _run_collector(db, collector_name):
    pending = db.get_pending_sources(collector_name)
    if not pending:
        return []
    paths = [row[0] for row in pending]
    file_info_map = {row[0]: (row[1], row[2]) for row in pending}
    db.mark_dispatched(paths, collector_name)
    plugin = collector_resolver.registry.get("exif")()
    results = []
    for p in paths:
        info = file_info_map.get(p, (0.0, 0))
        r = plugin.process(p, info).to_dict()
        r["collector"] = collector_name
        results.append(r)
    return results


def _write_results(db, results):
    data = _parse_batch(results)
    db.upsert_collection_results(
        data["image_entries"],
        data["meta_info_entries"],
        data["tag_entries"],
        data["collector_status"],
    )


class TestSearchDuringIndexing:
    def test_search_while_indexing_does_not_crash(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        for i in range(20):
            _create_test_image(img_dir / f"img_{i:03d}.jpg", 100 + i, 80 + i)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

        search_results = []
        search_errors = []

        def search_thread():
            try:
                engine = FileSearchEngine(str(db_path))
                paths, _, _ = engine.search(SearchQuery(require_keys=False))
                search_results.append(len(paths))
            except Exception as e:
                search_errors.append(e)

        threads = [threading.Thread(target=search_thread) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(search_errors) == 0
        assert all(count == 20 for count in search_results)

    def test_concurrent_search_with_write(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        for i in range(10):
            _create_test_image(img_dir / f"img_{i:02d}.jpg", 100, 80)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            results = _run_collector(idx.db, "exif")

        write_done = threading.Event()
        search_results = []
        errors = []

        def writer():
            try:
                db = FileDB(db_path)
                db.start()
                data = _parse_batch(results)
                db.upsert_collection_results(
                    data["image_entries"],
                    data["meta_info_entries"],
                    data["tag_entries"],
                    data["collector_status"],
                )
                db.close()
                write_done.set()
            except Exception as e:
                errors.append(e)
                write_done.set()

        def searcher():
            try:
                engine = FileSearchEngine(str(db_path))
                paths, _, _ = engine.search(SearchQuery(require_keys=False))
                search_results.append(len(paths))
            except Exception as e:
                errors.append(e)

        wt = threading.Thread(target=writer)
        st = threading.Thread(target=searcher)
        wt.start()
        st.start()
        wt.join(timeout=10)
        st.join(timeout=10)

        assert len(errors) == 0
        assert len(search_results) == 1
        assert search_results[0] == 10


class TestMultipleReadersNoCrash:
    def test_many_concurrent_searches(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        for i in range(15):
            _create_test_image(img_dir / f"img_{i:02d}.png", 100, 80, "PNG")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))
            results = _run_collector(idx.db, "exif")
            _write_results(idx.db, results)

        errors = []
        counts = []

        def reader(sort_by):
            try:
                engine = FileSearchEngine(str(db_path))
                paths, _, _ = engine.search(SearchQuery(sort_by=sort_by, require_keys=False))
                counts.append(len(paths))
            except Exception as e:
                errors.append(e)

        sorts = ["name", "modified", "size", "name", "created", "name", "modified", "size", "name", "created"]
        threads = [threading.Thread(target=reader, args=(s,)) for s in sorts]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert len(errors) == 0
        assert all(c == 15 for c in counts)


class TestDBConsistencyAfterConcurrentWrites:
    def test_sequential_index_and_collect(self, tmp_path):
        img_dir_a = tmp_path / "a"
        img_dir_b = tmp_path / "b"
        img_dir_a.mkdir()
        img_dir_b.mkdir()

        for i in range(5):
            _create_test_image(img_dir_a / f"a_{i}.jpg", 100, 80)
        for i in range(5):
            _create_test_image(img_dir_b / f"b_{i}.jpg", 100, 80)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index([str(img_dir_a), str(img_dir_b)])

            results = _run_collector(idx.db, "exif")
            assert len(results) == 10
            _write_results(idx.db, results)

        engine = FileSearchEngine(str(db_path))
        paths, _, _ = engine.search(SearchQuery(require_keys=False))
        assert len(paths) == 10

        db = FileDB(db_path)
        db.start()
        ok_count = db.read_conn.execute("SELECT COUNT(*) FROM collection_status WHERE collector='exif' AND status='ok'").fetchone()[0]
        db.close()
        assert ok_count == 10

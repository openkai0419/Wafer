import os
import time
from pathlib import Path

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.receivers.collector_receiver import _parse_batch
from test_support.scan_harness import ScanHarness


def _create_test_image(path, width=100, height=80, fmt="JPEG"):
    img = Image.new("RGB", (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _create_test_file(path, content=b"dummy"):
    Path(path).write_bytes(content)


def _run_collector_for_pending(db, plugin, collector_name):
    pending = db.get_pending_sources(collector_name)
    if not pending:
        return []
    paths = [row[0] for row in pending]
    file_info_map = {row[0]: (row[1], row[2]) for row in pending}
    db.mark_dispatched(paths, collector_name)
    results = []
    for p in paths:
        info = file_info_map.get(p, (0.0, 0))
        result = plugin.process(p, info).to_dict()
        result["collector"] = collector_name
        results.append(result)
    return results


def _write_results_to_db(db, results):
    data = _parse_batch(results)
    db.upsert_collection_results(
        data["image_entries"],
        data["meta_info_entries"],
        data["tag_entries"],
        data["collector_status"],
    )


def _get_exif_plugin():
    return collector_resolver.registry.get("exiftool")


def _build_populated_db(tmp_path, images):
    img_dir = tmp_path / "photos"
    img_dir.mkdir()
    created_paths = []
    for name, w, h, fmt in images:
        p = img_dir / name
        _create_test_image(p, w, h, fmt)
        created_paths.append(p)

    collectors = collector_resolver.summary()
    db_path = tmp_path / "test.db"

    with ScanHarness(db_path, collectors=collectors) as harness:
        harness.scan_and_wait(img_dir, expected=len(images))
        assert harness.wait_for(lambda: len(harness.db.get_pending_sources("exiftool")) >= len(images))
        plugin = _get_exif_plugin()()
        results = _run_collector_for_pending(harness.db, plugin, "exiftool")

    db = FileDB(db_path)
    db.start()
    _write_results_to_db(db, results)
    db.close()

    return db_path, img_dir, created_paths


class TestIndexToSearch:
    def test_indexed_files_searchable_by_name(self, tmp_path):
        db_path, img_dir, paths = _build_populated_db(
            tmp_path,
            [
                ("alpha.jpg", 200, 100, "JPEG"),
                ("beta.png", 64, 64, "PNG"),
                ("gamma.jpg", 300, 200, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        result_paths, _, _ = engine.search(
            SearchQuery(
                keys="path",
                keywords="alpha",
            )
        )
        norms = [normalize_path(str(p)) for p in paths]
        assert len(result_paths) == 1
        assert result_paths[0] == norms[0]

    def test_search_all_returns_all_indexed(self, tmp_path):
        db_path, img_dir, paths = _build_populated_db(
            tmp_path,
            [
                ("a.jpg", 100, 80, "JPEG"),
                ("b.png", 64, 64, "PNG"),
                ("c.jpg", 120, 90, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        result_paths, sources, aspects = engine.search(SearchQuery(require_keys=False))
        assert len(result_paths) == 3
        assert len(sources) == 3
        assert all(isinstance(a, float) for a in aspects)

    def test_collected_metadata_searchable(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        jpg_path = img_dir / "exif_test.jpg"
        img = Image.new("RGB", (200, 100), color=(0, 128, 255))
        img.save(str(jpg_path), format="JPEG")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=1)
            assert harness.wait_for(lambda: len(harness.db.get_pending_sources("exiftool")) >= 1)
            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(harness.db, plugin, "exiftool")
            _write_results_to_db(harness.db, results)

        engine = FileSearchEngine(str(db_path))
        db = FileDB(db_path)
        db.start()
        norm = normalize_path(str(jpg_path))
        meta_rows = db.read_conn.execute("SELECT key FROM meta_info WHERE path=?", (norm,)).fetchall()
        db.close()

        if meta_rows:
            key_name = meta_rows[0][0]
            all_paths, _, _ = engine.search(
                SearchQuery(
                    keys=(key_name,),
                    require_keys=True,
                )
            )
            assert norm in all_paths

    def test_directory_filter_after_index(self, tmp_path):
        dir_a = tmp_path / "dir_a"
        dir_b = tmp_path / "dir_b"
        dir_a.mkdir()
        dir_b.mkdir()
        _create_test_image(dir_a / "one.jpg", 100, 80)
        _create_test_image(dir_b / "two.jpg", 100, 80)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait([dir_a, dir_b], expected=2)

        engine = FileSearchEngine(str(db_path))
        norm_a = normalize_path(str(dir_a))

        filtered, _, _ = engine.search(
            SearchQuery(
                directories=(norm_a,),
                require_keys=False,
            )
        )
        assert len(filtered) == 1
        assert filtered[0].startswith(norm_a)

    def test_sort_order_reflects_db_state(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "aaa.jpg", 100, 80)
        time.sleep(0.05)
        _create_test_image(img_dir / "zzz.jpg", 100, 80)
        time.sleep(0.05)
        _create_test_image(img_dir / "mmm.jpg", 100, 80)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=3)

        engine = FileSearchEngine(str(db_path))

        asc_paths, _, _ = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )
        names_asc = [os.path.basename(p) for p in asc_paths]
        assert names_asc == sorted(names_asc)

        desc_paths, _, _ = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=False,
                require_keys=False,
            )
        )
        names_desc = [os.path.basename(p) for p in desc_paths]
        assert names_desc == sorted(names_desc, reverse=True)

    def test_deleted_file_not_in_search(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        keep = img_dir / "keep.jpg"
        remove = img_dir / "remove.jpg"
        _create_test_image(keep, 100, 80)
        _create_test_image(remove, 100, 80)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=2)

        remove.unlink()

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=1)

        engine = FileSearchEngine(str(db_path))
        result_paths, _, _ = engine.search(SearchQuery(require_keys=False))
        assert len(result_paths) == 1
        assert result_paths[0] == normalize_path(str(keep))

    def test_modified_file_recollected_and_searchable(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        img_path = img_dir / "evolving.jpg"
        _create_test_image(img_path, 80, 60)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=1)
            assert harness.wait_for(lambda: len(harness.db.get_pending_sources("exiftool")) >= 1)
            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(harness.db, plugin, "exiftool")
            _write_results_to_db(harness.db, results)

        engine = FileSearchEngine(str(db_path))
        pre_paths, _, pre_aspects = engine.search(SearchQuery(require_keys=False))
        assert len(pre_paths) == 1
        assert pre_aspects[0] != 0

        time.sleep(1.1)
        _create_test_image(img_path, 400, 100)

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan(img_dir)
            assert harness.wait_for(lambda: len(harness.db.get_pending_sources("exiftool")) >= 1)
            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(harness.db, plugin, "exiftool")
            _write_results_to_db(harness.db, results)

        engine2 = FileSearchEngine(str(db_path))
        post_paths, _, post_aspects = engine2.search(SearchQuery(require_keys=False))
        assert len(post_paths) == 1
        assert post_aspects[0] == 4.0

    def test_mixed_file_types_in_search(self, tmp_path):
        img_dir = tmp_path / "mixed"
        img_dir.mkdir()
        _create_test_image(img_dir / "photo.jpg", 200, 100)
        _create_test_file(img_dir / "readme.txt", b"hello")
        _create_test_file(img_dir / "data.bin", b"\x00" * 100)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with ScanHarness(db_path, collectors=collectors) as harness:
            harness.scan_and_wait(img_dir, expected=3)

        engine = FileSearchEngine(str(db_path))
        all_paths, _, _ = engine.search(SearchQuery(require_keys=False))
        assert len(all_paths) == 3

        txt_paths, _, _ = engine.search(
            SearchQuery(
                keys="path",
                keywords=".txt",
            )
        )
        assert len(txt_paths) == 1
        assert txt_paths[0].endswith("readme.txt")

    def test_aspect_ratio_reflects_image_dimensions(self, tmp_path):
        db_path, _, paths = _build_populated_db(
            tmp_path,
            [
                ("wide.jpg", 400, 100, "JPEG"),
                ("square.png", 200, 200, "PNG"),
                ("tall.jpg", 100, 300, "JPEG"),
            ],
        )

        engine = FileSearchEngine(str(db_path))
        result_paths, _, aspects = engine.search(
            SearchQuery(
                sort_by="name",
                ascending=True,
                require_keys=False,
            )
        )
        names = [os.path.basename(p) for p in result_paths]

        sq_idx = names.index("square.png")
        tall_idx = names.index("tall.jpg")
        wide_idx = names.index("wide.jpg")

        assert aspects[sq_idx] == 1.0
        assert aspects[wide_idx] == 4.0
        assert abs(aspects[tall_idx] - (100 / 300)) < 0.01

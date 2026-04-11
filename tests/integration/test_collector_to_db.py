import os
from pathlib import Path

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.utils.hashes import fast_signature_hash
from wafer.core.db.file_db import FileDB
from wafer.core.db.indexer import FileIndexer
from wafer.core.db.query import FileSearchEngine, SearchQuery
from wafer.plugin.collector.handler import collector_resolver
from wafer.app.indexer.collector_receiver import _parse_batch
from wafer.app.indexer.db_writer import DatabaseWriter


def _create_test_image(path, width=200, height=100, fmt="JPEG"):
    img = Image.new("RGB", (width, height), color=(128, 64, 200))
    img.save(str(path), format=fmt)


def _get_exif_plugin():
    return collector_resolver.registry.get("exiftool")


def _file_info(path):
    norm = normalize_path(str(path))
    st = os.stat(str(path))
    return norm, (st.st_mtime, st.st_size)


def _run_collector(db, plugin_cls, collector_name):
    pending = db.get_pending_sources(collector_name)
    if not pending:
        return []
    paths = [row[0] for row in pending]
    file_info_map = {row[0]: (row[1], row[2]) for row in pending}
    db.mark_dispatched(paths, collector_name)
    plugin = plugin_cls()
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


class TestCollectorPrefixAutoApply:
    def test_meta_info_keys_have_collector_prefix(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "test.jpg")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            plugin_cls = _get_exif_plugin()
            results = _run_collector(idx.db, plugin_cls, "exiftool")
            assert len(results) == 1

            parsed = _parse_batch(results)
            for path, key, value, value_num in parsed["meta_info_entries"]:
                assert key.startswith("exif."), f"Meta key '{key}' missing 'exif.' prefix"

    def test_collector_status_recorded(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "alpha.jpg")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            norm = normalize_path(str(img_dir / "alpha.jpg"))
            plugin_cls = _get_exif_plugin()
            results = _run_collector(idx.db, plugin_cls, "exiftool")
            _write_results(idx.db, results)

            row = idx.db.read_conn.execute(
                "SELECT status FROM collection_status WHERE source=? AND collector='exiftool'",
                (norm,),
            ).fetchone()
            assert row is not None
            assert row[0] == "ok"


class TestCollectorToSearch:
    def test_collected_metadata_searchable(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "landscape.jpg", width=400, height=200)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            plugin_cls = _get_exif_plugin()
            results = _run_collector(idx.db, plugin_cls, "exiftool")
            _write_results(idx.db, results)

        engine = FileSearchEngine(str(db_path))
        paths, _, aspects = engine.search(SearchQuery(require_keys=False))
        assert len(paths) == 1
        assert aspects[0] == 2.0

    def test_multiple_files_all_collected(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        names = ["a.jpg", "b.jpg", "c.png"]
        formats = ["JPEG", "JPEG", "PNG"]
        for name, fmt in zip(names, formats):
            _create_test_image(img_dir / name, fmt=fmt)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            plugin_cls = _get_exif_plugin()
            results = _run_collector(idx.db, plugin_cls, "exiftool")
            assert len(results) == 3
            _write_results(idx.db, results)

            for r in results:
                assert r["status"] is True

            rows = idx.db.read_conn.execute("SELECT COUNT(*) FROM collection_status WHERE collector='exiftool' AND status='ok'").fetchone()
            assert rows[0] == 3

        engine = FileSearchEngine(str(db_path))
        paths, _, _ = engine.search(SearchQuery(require_keys=False))
        assert len(paths) == 3


class TestParseBatchPrefixLogic:
    def test_prefix_applied_to_meta_keys(self):
        results = [
            {
                "source": "test/img.jpg",
                "path": "test/img.jpg",
                "status": True,
                "collector": "myext",
                "meta_info": {"width": "100", "height": "50"},
            }
        ]
        parsed = _parse_batch(results)
        keys = [entry[1] for entry in parsed["meta_info_entries"]]
        assert all(k.startswith("myext.") for k in keys)
        assert "myext.width" in keys
        assert "myext.height" in keys

    def test_prefix_applied_to_tag_keys(self):
        results = [
            {
                "source": "test/img.jpg",
                "path": "test/img.jpg",
                "status": True,
                "collector": "tagger",
                "file_hash": "abc123",
                "tags": {"category": "landscape", "rating": "5"},
            }
        ]
        parsed = _parse_batch(results)
        tag_keys = [entry[1] for entry in parsed["tag_entries"]]
        assert all(k.startswith("tagger.") for k in tag_keys)

    def test_no_prefix_when_collector_empty(self):
        results = [
            {
                "source": "test/img.jpg",
                "path": "test/img.jpg",
                "status": True,
                "collector": "",
                "meta_info": {"width": "100"},
            }
        ]
        parsed = _parse_batch(results)
        keys = [entry[1] for entry in parsed["meta_info_entries"]]
        assert "width" in keys

    def test_failed_status_no_meta(self):
        results = [
            {
                "source": "test/bad.jpg",
                "status": False,
                "collector": "exiftool",
                "meta_info": {"width": "100"},
            }
        ]
        parsed = _parse_batch(results)
        assert parsed["meta_info_entries"] == []
        assert len(parsed["collector_status"]) == 1
        assert parsed["collector_status"][0][2] == "fail"

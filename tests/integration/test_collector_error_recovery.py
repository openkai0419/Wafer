import os

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.core.db.file_db import FileDB
from wafer.core.db.indexer import FileIndexer
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.collector.base import CollectorResult, BaseCollectorPlugin
from wafer.app.indexer.collector_receiver import _parse_batch
from wafer.app.indexer.db_writer import DatabaseWriter


def _create_test_image(path, width=200, height=100, fmt="JPEG"):
    Image.new("RGB", (width, height), color=(128, 64, 200)).save(str(path), format=fmt)


def _file_info(path):
    st = os.stat(str(path))
    return st.st_mtime, st.st_size


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


class _FaultyCollector(BaseCollectorPlugin):
    NAME = "_test_faulty"
    EXTENSIONS = (".jpg", ".jpeg", ".png")
    PRIORITY = 50
    DEFAULT_ENABLED = True

    def process(self, path, file_info):
        raise RuntimeError("Simulated collector failure")


class TestCollectorExceptionMarksFailure:
    def test_exception_in_collector_produces_fail_status(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "test.jpg")
        norm = normalize_path(str(img_dir / "test.jpg"))

        results = [{
            "source": norm,
            "path": norm,
            "status": False,
            "collector": "_test_faulty",
            "meta_info": {},
        }]
        parsed = _parse_batch(results)
        assert len(parsed["collector_status"]) == 1
        assert parsed["collector_status"][0][2] == "fail"
        assert parsed["meta_info_entries"] == []

    def test_failed_status_does_not_store_meta(self):
        results = [{
            "source": "/fake/img.jpg",
            "path": "/fake/img.jpg",
            "status": False,
            "collector": "broken",
            "meta_info": {"width": "100", "height": "50"},
        }]
        parsed = _parse_batch(results)
        assert parsed["meta_info_entries"] == []
        assert len(parsed["collector_status"]) == 1


class TestOtherCollectorUnaffected:
    def test_one_fail_one_success_independent(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "test.jpg", 300, 200)
        norm = normalize_path(str(img_dir / "test.jpg"))

        results = [
            {
                "source": norm,
                "path": norm,
                "status": False,
                "collector": "faulty_plugin",
                "meta_info": {"will_be_ignored": "yes"},
            },
            {
                "source": norm,
                "path": norm,
                "status": True,
                "collector": "exif",
                "aspect": 1.5,
                "meta_info": {"width": "300", "height": "200"},
            },
        ]
        parsed = _parse_batch(results)

        statuses = {cs[1]: cs[2] for cs in parsed["collector_status"]}
        assert statuses["faulty_plugin"] == "fail"
        assert statuses["exif"] == "ok"

        meta_keys = [e[1] for e in parsed["meta_info_entries"]]
        assert all(k.startswith("exif.") for k in meta_keys)
        assert not any(k.startswith("faulty_plugin.") for k in meta_keys)

    def test_mixed_batch_partial_failure(self):
        results = [
            {"source": "/a.jpg", "path": "/a.jpg", "status": True, "collector": "exif", "meta_info": {"w": "10"}},
            {"source": "/b.jpg", "path": "/b.jpg", "status": False, "collector": "exif"},
            {"source": "/c.jpg", "path": "/c.jpg", "status": True, "collector": "exif", "meta_info": {"w": "30"}},
        ]
        parsed = _parse_batch(results)
        ok_statuses = [cs for cs in parsed["collector_status"] if cs[2] == "ok"]
        fail_statuses = [cs for cs in parsed["collector_status"] if cs[2] == "fail"]
        assert len(ok_statuses) == 2
        assert len(fail_statuses) == 1
        assert len(parsed["meta_info_entries"]) == 2


class TestFailedCollectorWrittenToDB:
    def test_fail_status_persisted_in_db(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "fail.jpg")

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))
            norm = normalize_path(str(img_dir / "fail.jpg"))

            results = [{
                "source": norm,
                "path": norm,
                "status": False,
                "collector": "exif",
            }]
            _write_results(idx.db, results)

            row = idx.db.read_conn.execute(
                "SELECT status FROM collection_status WHERE source=? AND collector='exif'",
                (norm,),
            ).fetchone()
            assert row is not None
            assert row[0] == "fail"

    def test_ok_overwrites_previous_fail(self, tmp_path):
        img_dir = tmp_path / "photos"
        img_dir.mkdir()
        _create_test_image(img_dir / "recover.jpg", 400, 200)

        collectors = collector_resolver.summary()
        db_path = tmp_path / "test.db"

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))
            norm = normalize_path(str(img_dir / "recover.jpg"))

            fail_results = [{"source": norm, "path": norm, "status": False, "collector": "exif"}]
            _write_results(idx.db, fail_results)

            row = idx.db.read_conn.execute(
                "SELECT status FROM collection_status WHERE source=? AND collector='exif'", (norm,)
            ).fetchone()
            assert row[0] == "fail"

            ok_results = [{
                "source": norm, "path": norm, "status": True, "collector": "exif",
                "aspect": 2.0, "meta_info": {"width": "400"},
            }]
            _write_results(idx.db, ok_results)

            row2 = idx.db.read_conn.execute(
                "SELECT status FROM collection_status WHERE source=? AND collector='exif'", (norm,)
            ).fetchone()
            assert row2[0] == "ok"

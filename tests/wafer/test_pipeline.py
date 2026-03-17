import os
import time
from pathlib import Path

from PIL import Image

from wafer.utils.paths import normalize_path
from wafer.utils.hashes import fast_signature_hash
from wafer.core.db.file_db import FileDB
from wafer.core.db.indexer import FileIndexer
from wafer.plugin.collector.handler import collector_resolver
from wafer.plugin.collector.base import CollectorResult
from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.app.indexer.collector_receiver import _parse_batch


def _get_exif_plugin():
    return collector_resolver.registry.get('exif')


def _create_test_image(path, width=100, height=80, fmt='JPEG'):
    img = Image.new('RGB', (width, height), color=(255, 0, 0))
    img.save(str(path), format=fmt)


def _create_test_file(path, content=b'dummy'):
    Path(path).write_bytes(content)


def _get_file_info(path):
    norm = normalize_path(str(path))
    st = os.stat(str(path))
    ctime = st.st_birthtime if hasattr(st, 'st_birthtime') else st.st_ctime
    return norm, (st.st_mtime, st.st_size, ctime)


def _run_collector_for_pending(db, plugin, collector_name):
    pending = db.get_pending_sources(collector_name)
    if not pending:
        return []
    paths = [row[0] for row in pending]
    file_info_map = {row[0]: (row[1], row[2], row[3]) for row in pending}
    db.mark_dispatched(paths, collector_name)
    results = []
    for p in paths:
        info = file_info_map.get(p, (0.0, 0, 0.0))
        result = plugin.process(p, info).to_dict()
        result['collector'] = collector_name
        results.append(result)
    return results


def _write_results_sync(writer, results, collector_name):
    for r in results:
        r.setdefault('collector', collector_name)
    data = _parse_batch(results)
    writer.upsert_results(
        data['source_updates'], data['image_entries'],
        data['meta_info_entries'], data['tag_entries'], data['collector_status'],
    )


class TestImagePipeline:

    def test_full_image_pipeline(self, tmp_path):
        img_dir = tmp_path / 'photos'
        img_dir.mkdir()
        jpg_path = img_dir / 'test.jpg'
        _create_test_image(jpg_path, width=200, height=100)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            norm = normalize_path(str(jpg_path))
            prev = idx.db.load_existing_sources()
            assert norm in prev

            row = idx.db.read_conn.execute(
                "SELECT status FROM sources WHERE source=?", (norm,)
            ).fetchone()
            assert row[0] == 'indexed'

            file_row = idx.db.read_conn.execute(
                "SELECT name, aspect_ratio FROM files WHERE path=?", (norm,)
            ).fetchone()
            assert file_row is not None
            assert file_row[0] == 'test.jpg'

            pending = idx.db.get_pending_sources('exif')
            assert len(pending) == 1
            assert pending[0][0] == norm

            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(idx.db, plugin, 'exif')
            assert len(results) == 1
            assert results[0]['status'] is True
            assert results[0]['source'] == norm
            assert results[0]['aspect'] == 2.0

            dispatched = idx.db.read_conn.execute(
                "SELECT status FROM collection_status WHERE source=? AND collector='exif'",
                (norm,),
            ).fetchone()
            assert dispatched[0] == 'dispatched'

            writer = DatabaseWriter(str(db_path))
            writer.start()
            _write_results_sync(writer, results, 'exif')
            writer.close()

            db = FileDB(db_path)
            db.start()
            try:
                src_row = db.read_conn.execute(
                    "SELECT status FROM sources WHERE source=?", (norm,)
                ).fetchone()
                assert src_row[0] == 'ok'

                file_row = db.read_conn.execute(
                    "SELECT name, aspect_ratio FROM files WHERE path=?", (norm,)
                ).fetchone()
                assert file_row[0] == 'test.jpg'
                assert file_row[1] == 2.0

                meta = db.read_conn.execute(
                    "SELECT key, value FROM meta_info WHERE path=?", (norm,)
                ).fetchall()
                assert len(meta) > 0

                cs = db.read_conn.execute(
                    "SELECT status FROM collection_status WHERE source=? AND collector='exif'",
                    (norm,),
                ).fetchone()
                assert cs[0] == 'ok'

                no_pending = db.get_pending_sources('exif')
                assert len(no_pending) == 0
            finally:
                db.close()

    def test_non_image_skips_collector(self, tmp_path):
        file_dir = tmp_path / 'docs'
        file_dir.mkdir()
        txt_path = file_dir / 'readme.txt'
        _create_test_file(txt_path, b'hello world')

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(file_dir))

            norm = normalize_path(str(txt_path))
            prev = idx.db.load_existing_sources()
            assert norm in prev

            file_row = idx.db.read_conn.execute(
                "SELECT name FROM files WHERE path=?", (norm,)
            ).fetchone()
            assert file_row[0] == 'readme.txt'

            pending = idx.db.get_pending_sources('exif')
            assert len(pending) == 0

    def test_mixed_files_extension_filter(self, tmp_path):
        mix_dir = tmp_path / 'mixed'
        mix_dir.mkdir()
        jpg_path = mix_dir / 'photo.jpg'
        png_path = mix_dir / 'icon.png'
        txt_path = mix_dir / 'notes.txt'
        bin_path = mix_dir / 'data.bin'
        _create_test_image(jpg_path, 160, 90, 'JPEG')
        _create_test_image(png_path, 64, 64, 'PNG')
        _create_test_file(txt_path, b'text content')
        _create_test_file(bin_path, b'\x00' * 256)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(mix_dir))

            all_files = idx.db.read_conn.execute("SELECT path FROM files").fetchall()
            assert len(all_files) == 4

            pending = idx.db.get_pending_sources('exif')
            pending_paths = {r[0] for r in pending}
            assert normalize_path(str(jpg_path)) in pending_paths
            assert normalize_path(str(png_path)) in pending_paths
            assert normalize_path(str(txt_path)) not in pending_paths
            assert normalize_path(str(bin_path)) not in pending_paths

            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(idx.db, plugin, 'exif')
            assert len(results) == 2
            ok_results = [r for r in results if r['status'] is True]
            assert len(ok_results) == 2

            writer = DatabaseWriter(str(db_path))
            writer.start()
            _write_results_sync(writer, results, 'exif')
            writer.close()

            db = FileDB(db_path)
            db.start()
            try:
                for img_p in [jpg_path, png_path]:
                    norm = normalize_path(str(img_p))
                    cs = db.read_conn.execute(
                        "SELECT status FROM collection_status WHERE source=? AND collector='exif'",
                        (norm,),
                    ).fetchone()
                    assert cs[0] == 'ok'
                    src = db.read_conn.execute(
                        "SELECT status FROM sources WHERE source=?", (norm,)
                    ).fetchone()
                    assert src[0] == 'ok'

                txt_norm = normalize_path(str(txt_path))
                txt_src = db.read_conn.execute(
                    "SELECT status FROM sources WHERE source=?", (txt_norm,)
                ).fetchone()
                assert txt_src[0] == 'indexed'

                txt_cs = db.read_conn.execute(
                    "SELECT count(*) FROM collection_status WHERE source=?",
                    (txt_norm,),
                ).fetchone()
                assert txt_cs[0] == 0
            finally:
                db.close()

    def test_file_deletion_reflected(self, tmp_path):
        file_dir = tmp_path / 'volatile'
        file_dir.mkdir()
        f1 = file_dir / 'keep.jpg'
        f2 = file_dir / 'remove.jpg'
        _create_test_image(f1, 50, 50)
        _create_test_image(f2, 50, 50)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(file_dir))

            all_sources = idx.db.read_conn.execute("SELECT source FROM sources").fetchall()
            assert len(all_sources) == 2

        f2.unlink()

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(file_dir))

            remaining = idx.db.read_conn.execute("SELECT source FROM sources").fetchall()
            assert len(remaining) == 1
            assert remaining[0][0] == normalize_path(str(f1))

            files = idx.db.read_conn.execute("SELECT path FROM files").fetchall()
            assert len(files) == 1

            cs = idx.db.read_conn.execute(
                "SELECT count(*) FROM collection_status"
            ).fetchone()
            assert cs[0] == 1

    def test_modified_file_re_registered(self, tmp_path):
        file_dir = tmp_path / 'mutable'
        file_dir.mkdir()
        img_path = file_dir / 'evolving.jpg'
        _create_test_image(img_path, 80, 60)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(file_dir))
            norm = normalize_path(str(img_path))

            plugin = _get_exif_plugin()()
            results = _run_collector_for_pending(idx.db, plugin, 'exif')

            writer = DatabaseWriter(str(db_path))
            writer.start()
            _write_results_sync(writer, results, 'exif')
            writer.close()

        db_check = FileDB(db_path)
        db_check.start()
        cs_before = db_check.read_conn.execute(
            "SELECT status FROM collection_status WHERE source=? AND collector='exif'",
            (norm,),
        ).fetchone()
        assert cs_before[0] == 'ok'
        old_mtime = db_check.read_conn.execute(
            "SELECT modified FROM sources WHERE source=?", (norm,)
        ).fetchone()[0]
        db_check.close()

        time.sleep(1.1)
        _create_test_image(img_path, 200, 100)
        new_st = os.stat(str(img_path))
        assert new_st.st_mtime != old_mtime

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(file_dir))

            src_row = idx.db.read_conn.execute(
                "SELECT status FROM sources WHERE source=?", (norm,)
            ).fetchone()
            assert src_row[0] == 'indexed'

            pending = idx.db.get_pending_sources('exif')
            assert len(pending) == 1
            assert pending[0][0] == norm


class TestDispatcherSimulation:

    def test_pending_to_dispatched_to_ok(self, tmp_path):
        img_dir = tmp_path / 'batch'
        img_dir.mkdir()
        paths = []
        for i in range(5):
            p = img_dir / f'img_{i}.png'
            _create_test_image(p, 100 + i * 10, 80 + i * 5, 'PNG')
            paths.append(p)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            pending = idx.db.get_pending_sources('exif')
            assert len(pending) == 5

            pending_paths = [r[0] for r in pending]
            file_info_map = {r[0]: (r[1], r[2], r[3]) for r in pending}
            idx.db.mark_dispatched(pending_paths, 'exif')

            dispatched_count = idx.db.read_conn.execute(
                "SELECT count(*) FROM collection_status WHERE collector='exif' AND status='dispatched'"
            ).fetchone()[0]
            assert dispatched_count == 5

            plugin = _get_exif_plugin()()
            results = []
            for p in pending_paths:
                info = file_info_map[p]
                r = plugin.process(p, info).to_dict()
                r['collector'] = 'exif'
                results.append(r)

            writer = DatabaseWriter(str(db_path))
            writer.start()
            _write_results_sync(writer, results, 'exif')
            writer.close()

            db = FileDB(db_path)
            db.start()
            try:
                ok_count = db.read_conn.execute(
                    "SELECT count(*) FROM collection_status WHERE collector='exif' AND status='ok'"
                ).fetchone()[0]
                assert ok_count == 5

                pending_after = db.get_pending_sources('exif')
                assert len(pending_after) == 0

                for p in paths:
                    norm = normalize_path(str(p))
                    row = db.read_conn.execute(
                        "SELECT status FROM sources WHERE source=?", (norm,)
                    ).fetchone()
                    assert row[0] == 'ok'
            finally:
                db.close()

    def test_reset_stale_dispatched(self, tmp_path):
        img_dir = tmp_path / 'stale'
        img_dir.mkdir()
        img = img_dir / 'orphan.jpg'
        _create_test_image(img, 50, 50)

        collectors = collector_resolver.summary()
        db_path = tmp_path / 'test.db'

        with FileIndexer(db_path, collectors=collectors) as idx:
            idx.initialize()
            idx.update_index(str(img_dir))

            pending = idx.db.get_pending_sources('exif')
            paths = [r[0] for r in pending]
            idx.db.mark_dispatched(paths, 'exif')

            dispatched = idx.db.read_conn.execute(
                "SELECT count(*) FROM collection_status WHERE status='dispatched'"
            ).fetchone()[0]
            assert dispatched == 1

            idx.db.reset_stale_dispatched(['exif'])

            restored = idx.db.get_pending_sources('exif')
            assert len(restored) == 1


class TestWriterCollectorField:

    def test_collector_name_from_payload(self, tmp_path):
        db_path = tmp_path / 'test.db'
        db = FileDB(db_path)
        db.start()
        db.initialize_database()

        db.conn.execute("INSERT INTO hash_index (file_hash) VALUES ('h1')")
        db.conn.execute(
            "INSERT INTO sources (source, file_hash, size, modified, created, collected, status) "
            "VALUES ('src1', 'h1', 100, 1.0, 1.0, NULL, 'indexed')"
        )
        db.conn.execute(
            "INSERT INTO files (path, source, name, aspect_ratio) VALUES ('src1', 'src1', 'test', 1.0)"
        )
        db.conn.commit()
        db.close()

        writer = DatabaseWriter(str(db_path))
        writer.start()

        results = [{
            'source': 'src1',
            'path': 'src1',
            'name': 'result.png',
            'aspect': 1.5,
            'file_hash': 'h1',
            'meta_info': {'width': '100'},
            'tags': {},
            'status': True,
        }]
        _write_results_sync(writer, results, 'custom_plugin')
        writer.close()

        db2 = FileDB(db_path)
        db2.start()
        cs = db2.read_conn.execute(
            "SELECT collector, status FROM collection_status WHERE source='src1'"
        ).fetchone()
        assert cs[0] == 'custom_plugin'
        assert cs[1] == 'ok'
        db2.close()

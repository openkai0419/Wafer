import py_compile
import sqlite3

from pathlib import Path

from source.core.db.file_db import FileDB, _table_signature, _expected_table_signature, _TABLES


def test_compile():
    py_compile.compile('source/core/db/file_db.py')


def test_filedb_start_exit(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    assert db.conn is not None
    assert db.read_conn is not None
    db.close()


def test_filedb_upsert_and_load(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    sources = [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')]
    images = [('c:/test/img.jpg', 'src1', 'img.jpg', 1.5)]
    metas = [('c:/test/img.jpg', 'dpi', '72')]
    tags = [('hash1', 'rating', '5')]
    db.upsert_batches(sources, images, metas, tags)
    prev = db.load_existing_sources()
    assert 'src1' in prev
    assert prev['src1'] == (1.0, 100)
    db.close()


def test_filedb_delete_sources(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    sources = [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')]
    db.upsert_batches(sources, [], [], [])
    db.delete_sources_by_paths(['src1'])
    prev = db.load_existing_sources()
    assert 'src1' not in prev
    db.close()


def test_schema_no_change_preserves_data(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)],
        [('c:/a.jpg', 'k', 'v')],
        [('hash1', 'tag', 'val')],
    )
    db.close()
    db2 = FileDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    prev = db2.load_existing_sources()
    assert 'src1' in prev
    db2.close()


def test_schema_change_drops_and_recreates(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)], [], [],
    )
    db.conn.execute('ALTER TABLE sources ADD COLUMN extra_col TEXT')
    db.conn.commit()
    db.close()
    db2 = FileDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    prev = db2.load_existing_sources()
    assert len(prev) == 0
    cols = [r[1] for r in db2.conn.execute("PRAGMA table_info('sources')").fetchall()]
    assert 'extra_col' not in cols
    db2.close()


def test_schema_change_cascades_to_children(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)],
        [('c:/a.jpg', 'k', 'v')], [],
    )
    db.conn.execute('ALTER TABLE sources ADD COLUMN extra_col TEXT')
    db.conn.commit()
    db.close()
    db2 = FileDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    imgs = db2.conn.execute('SELECT COUNT(*) FROM files').fetchone()[0]
    metas = db2.conn.execute('SELECT COUNT(*) FROM meta_info').fetchone()[0]
    assert imgs == 0
    assert metas == 0
    db2.close()


def test_detect_no_changes_on_fresh_db(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    changed = db._detect_changed_tables()
    assert changed == set()
    db.close()


def test_table_signature_matches_expected(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    for name, _, create_sql in _TABLES:
        actual = _table_signature(db.conn, name)
        expected = _expected_table_signature(name, create_sql)
        assert actual == expected, f'{name}: actual={actual} expected={expected}'
    db.close()


def test_collection_status_table_exists(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info('collection_status')").fetchall()]
    assert 'source' in cols
    assert 'collector' in cols
    assert 'status' in cols
    assert 'collected_at' in cols
    db.close()


def test_upsert_basic_sources(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    sources = [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')]
    images = [('c:/a.jpg', 'src1', 'a.jpg', None)]
    db.upsert_basic_sources(sources, images)
    prev = db.load_existing_sources()
    assert 'src1' in prev
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] is None
    db.close()


def test_upsert_basic_sources_preserves_existing_aspect(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.5)],
    )
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 2.0, 1.0, 2.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None)],
    )
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] == 1.5
    db.close()


def test_upsert_collection_results(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None)],
    )
    db.upsert_collection_results(
        [(2.0, 'ok', 'src1')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.5)],
        [('c:/a.jpg', 'width', '1920')],
        [('hash1', 'rating', '5')],
        [('src1', 'exif', 'ok', 2.0)],
    )
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] == 1.5
    status_row = db.read_conn.execute("SELECT status FROM sources WHERE source='src1'").fetchone()
    assert status_row[0] == 'ok'
    cs_row = db.read_conn.execute("SELECT status FROM collection_status WHERE source='src1' AND collector='exif'").fetchone()
    assert cs_row[0] == 'ok'
    meta_row = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/a.jpg' AND key='width'").fetchone()
    assert meta_row[0] == '1920'
    db.close()


def test_insert_pending_collection(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed'), ('src2', 'hash2', 200, 2.0, 2.0, 2.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None), ('c:/b.jpg', 'src2', 'b.jpg', None)],
    )
    db.insert_pending_collection(['src1', 'src2'], ['exif'])
    rows = db.get_pending_sources('exif')
    assert len(rows) == 2
    sources = {r[0] for r in rows}
    assert sources == {'src1', 'src2'}
    db.close()


def test_get_pending_sources_excludes_completed(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed'), ('src2', 'hash2', 200, 2.0, 2.0, 2.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None), ('c:/b.jpg', 'src2', 'b.jpg', None)],
    )
    db.insert_pending_collection(['src1', 'src2'], ['exif'])
    db.upsert_collection_results([], [], [], [], [('src1', 'exif', 'ok', 1.0)])
    rows = db.get_pending_sources('exif')
    assert len(rows) == 1
    assert rows[0][0] == 'src2'
    db.close()


def test_collection_status_cascade_delete(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None)],
    )
    db.insert_pending_collection(['src1'], ['exif'])
    db.delete_sources_by_paths(['src1'])
    rows = db.conn.execute("SELECT COUNT(*) FROM collection_status").fetchone()[0]
    assert rows == 0
    db.close()


def test_rename_paths_single_file(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('c:/old/img.jpg', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/old/img.jpg', 'c:/old/img.jpg', 'img.jpg', 1.5)],
        [('c:/old/img.jpg', 'width', '1920')],
        [('hash1', 'rating', '5')],
    )
    db.insert_pending_collection(['c:/old/img.jpg'], ['exif'])
    db.rename_paths([('c:/old/img.jpg', 'c:/new/img.jpg')])
    assert db.read_conn.execute("SELECT COUNT(*) FROM sources WHERE source='c:/old/img.jpg'").fetchone()[0] == 0
    src_row = db.read_conn.execute("SELECT file_hash, size FROM sources WHERE source='c:/new/img.jpg'").fetchone()
    assert src_row == ('hash1', 100)
    file_row = db.read_conn.execute("SELECT name, aspect_ratio FROM files WHERE path='c:/new/img.jpg'").fetchone()
    assert file_row == ('img.jpg', 1.5)
    meta_row = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/new/img.jpg' AND key='width'").fetchone()
    assert meta_row[0] == '1920'
    assert db.read_conn.execute("SELECT COUNT(*) FROM meta_info WHERE path='c:/old/img.jpg'").fetchone()[0] == 0
    tag_row = db.read_conn.execute("SELECT value FROM tags WHERE file_hash='hash1' AND key='rating'").fetchone()
    assert tag_row[0] == '5'
    cs_row = db.read_conn.execute("SELECT source FROM collection_status WHERE source='c:/new/img.jpg'").fetchone()
    assert cs_row is not None
    assert db.read_conn.execute("SELECT COUNT(*) FROM collection_status WHERE source='c:/old/img.jpg'").fetchone()[0] == 0
    db.close()


def test_rename_paths_batch(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [
            ('c:/dir/a.jpg', 'hash_a', 100, 1.0, 1.0, 1.0, 'ok'),
            ('c:/dir/b.jpg', 'hash_b', 200, 2.0, 2.0, 2.0, 'ok'),
        ],
        [
            ('c:/dir/a.jpg', 'c:/dir/a.jpg', 'a.jpg', 1.0),
            ('c:/dir/b.jpg', 'c:/dir/b.jpg', 'b.jpg', 2.0),
        ],
        [('c:/dir/a.jpg', 'k', 'v1'), ('c:/dir/b.jpg', 'k', 'v2')],
        [],
    )
    db.rename_paths([
        ('c:/dir/a.jpg', 'c:/new/a.jpg'),
        ('c:/dir/b.jpg', 'c:/new/b.jpg'),
    ])
    prev = db.load_existing_sources()
    assert 'c:/new/a.jpg' in prev
    assert 'c:/new/b.jpg' in prev
    assert 'c:/dir/a.jpg' not in prev
    assert 'c:/dir/b.jpg' not in prev
    meta_a = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/new/a.jpg' AND key='k'").fetchone()
    assert meta_a[0] == 'v1'
    db.close()


def test_rename_paths_updates_filename(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('c:/dir/old_name.jpg', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/dir/old_name.jpg', 'c:/dir/old_name.jpg', 'old_name.jpg', 1.0)],
        [], [],
    )
    db.rename_paths([('c:/dir/old_name.jpg', 'c:/dir/new_name.jpg')])
    row = db.read_conn.execute("SELECT name FROM files WHERE path='c:/dir/new_name.jpg'").fetchone()
    assert row[0] == 'new_name.jpg'
    db.close()


def test_rename_paths_nonexistent_source(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.rename_paths([('c:/nonexistent.jpg', 'c:/new.jpg')])
    assert db.read_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    db.close()


def _setup_db_with_pending(tmp_path, sources_count=3):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    srcs = [(f'src{i}', f'h{i}', 100, 1.0, 1.0, 1.0, 'indexed') for i in range(sources_count)]
    imgs = [(f'src{i}', f'src{i}', f'f{i}.jpg', 1.0) for i in range(sources_count)]
    db.upsert_basic_sources(srcs, imgs)
    db.insert_pending_collection([f'src{i}' for i in range(sources_count)], ['exif'])
    return db


def test_mark_dispatched(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(['src0', 'src1'], 'exif')
    pending = db.get_pending_sources('exif')
    assert len(pending) == 1
    assert pending[0][0] == 'src2'
    dispatched = db.read_conn.execute(
        "SELECT source FROM collection_status WHERE status='dispatched' ORDER BY source"
    ).fetchall()
    assert [r[0] for r in dispatched] == ['src0', 'src1']
    db.close()


def test_mark_dispatched_empty(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched([], 'exif')
    pending = db.get_pending_sources('exif')
    assert len(pending) == 3
    db.close()


def test_mark_dispatched_only_affects_pending(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.conn.execute(
        "UPDATE collection_status SET status='ok' WHERE source='src0'"
    )
    db.conn.commit()
    db.mark_dispatched(['src0', 'src1'], 'exif')
    ok = db.read_conn.execute(
        "SELECT status FROM collection_status WHERE source='src0'"
    ).fetchone()
    assert ok[0] == 'ok'
    db.close()


def test_reset_stale_dispatched(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(['src0', 'src1'], 'exif')
    changed = db.reset_stale_dispatched(['exif'])
    assert changed == 2
    pending = db.get_pending_sources('exif')
    assert len(pending) == 3
    db.close()


def test_reset_stale_dispatched_no_collectors(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(['src0'], 'exif')
    changed = db.reset_stale_dispatched()
    assert changed == 1
    pending = db.get_pending_sources('exif')
    assert len(pending) == 3
    db.close()


def test_reset_stale_dispatched_does_not_affect_ok(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.conn.execute(
        "UPDATE collection_status SET status='ok' WHERE source='src0'"
    )
    db.conn.commit()
    db.mark_dispatched(['src1'], 'exif')
    changed = db.reset_stale_dispatched(['exif'])
    assert changed == 1
    ok = db.read_conn.execute(
        "SELECT status FROM collection_status WHERE source='src0'"
    ).fetchone()
    assert ok[0] == 'ok'
    db.close()


def test_get_sources_without_collector(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'h1', 100, 1.0, 1.0, 1.0, 'indexed'),
         ('src2', 'h2', 200, 2.0, 2.0, 2.0, 'indexed'),
         ('src3', 'h3', 300, 3.0, 3.0, 3.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None),
         ('c:/b.jpg', 'src2', 'b.jpg', None),
         ('c:/c.jpg', 'src3', 'c.jpg', None)],
    )
    db.insert_pending_collection(['src1'], ['exif'])
    missing = db.get_sources_without_collector('exif')
    assert set(missing) == {'src2', 'src3'}
    db.close()


def test_get_sources_without_collector_empty_when_all_have(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'h1', 100, 1.0, 1.0, 1.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None)],
    )
    db.insert_pending_collection(['src1'], ['exif'])
    missing = db.get_sources_without_collector('exif')
    assert missing == []
    db.close()


def test_get_sources_without_collector_new_collector(tmp_path):
    db = FileDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [('src1', 'h1', 100, 1.0, 1.0, 1.0, 'indexed')],
        [('c:/a.jpg', 'src1', 'a.jpg', None)],
    )
    db.insert_pending_collection(['src1'], ['exif'])
    missing = db.get_sources_without_collector('ocr')
    assert missing == ['src1']
    db.close()

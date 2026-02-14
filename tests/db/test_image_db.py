import py_compile
import sqlite3

from pathlib import Path

from source.db.image_db import ImageDB, _table_signature, _expected_table_signature, _TABLES


def test_compile():
    py_compile.compile('source/db/image_db.py')


def test_imagedb_start_exit(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    assert db.conn is not None
    assert db.read_conn is not None
    db.exit()


def test_imagedb_upsert_and_load(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    sources = [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')]
    images = [('c:/test/img.jpg', 'src1', 'img.jpg', 1.5)]
    metas = [('c:/test/img.jpg', 'dpi', '72')]
    tags = [('hash1', 'rating', '5')]
    db.upsert_batches(sources, images, metas, tags)
    prev = db.load_previous()
    assert 'src1' in prev
    assert prev['src1'] == (1.0, 100)
    db.exit()


def test_imagedb_delete_sources(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    sources = [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')]
    db.upsert_batches(sources, [], [], [])
    db.delete_sources_by_paths(['src1'])
    prev = db.load_previous()
    assert 'src1' not in prev
    db.exit()


def test_schema_no_change_preserves_data(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)],
        [('c:/a.jpg', 'k', 'v')],
        [('hash1', 'tag', 'val')],
    )
    db.exit()
    db2 = ImageDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    prev = db2.load_previous()
    assert 'src1' in prev
    db2.exit()


def test_schema_change_drops_and_recreates(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)], [], [],
    )
    db.conn.execute('ALTER TABLE sources ADD COLUMN extra_col TEXT')
    db.conn.commit()
    db.exit()
    db2 = ImageDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    prev = db2.load_previous()
    assert len(prev) == 0
    cols = [r[1] for r in db2.conn.execute("PRAGMA table_info('sources')").fetchall()]
    assert 'extra_col' not in cols
    db2.exit()


def test_schema_change_cascades_to_children(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [('src1', 'hash1', 100, 1.0, 1.0, 1.0, 'ok')],
        [('c:/a.jpg', 'src1', 'a.jpg', 1.0)],
        [('c:/a.jpg', 'k', 'v')], [],
    )
    db.conn.execute('ALTER TABLE sources ADD COLUMN extra_col TEXT')
    db.conn.commit()
    db.exit()
    db2 = ImageDB(tmp_path / 'test.db')
    db2.start()
    db2.initialize_database()
    imgs = db2.conn.execute('SELECT COUNT(*) FROM images').fetchone()[0]
    metas = db2.conn.execute('SELECT COUNT(*) FROM meta_info').fetchone()[0]
    assert imgs == 0
    assert metas == 0
    db2.exit()


def test_detect_no_changes_on_fresh_db(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    changed = db._detect_changed_tables()
    assert changed == set()
    db.exit()


def test_table_signature_matches_expected(tmp_path):
    db = ImageDB(tmp_path / 'test.db')
    db.start()
    db.initialize_database()
    for name, _, create_sql in _TABLES:
        actual = _table_signature(db.conn, name)
        expected = _expected_table_signature(name, create_sql)
        assert actual == expected, f'{name}: actual={actual} expected={expected}'
    db.exit()

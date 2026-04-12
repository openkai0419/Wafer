import py_compile
import sqlite3
import threading

from pathlib import Path

from wafer.core.db.file_db import (
    FileDB,
    _table_signature,
    _expected_table_signature,
    _TABLES,
    _SQL_UPSERT_SOURCES,
    _SQL_UPSERT_FILES,
    _SQL_UPSERT_FILES_COALESCE,
    _SQL_UPSERT_META,
    _SQL_UPSERT_TAGS,
    _SQL_UPSERT_COLLECTION_STATUS,
)


def test_compile():
    py_compile.compile("wafer/core/db/file_db.py")


def test_filedb_start_exit(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    assert db.conn is not None
    assert db.read_conn is not None
    db.close()
    assert db.conn is None
    assert db.read_conn is None


def test_filedb_double_close_no_error(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.close()
    db.close()


def test_filedb_upsert_and_load(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    sources = [("src1", "hash1", 100, 1.0)]
    images = [("c:/test/img.jpg", "src1", 1.5)]
    metas = [("c:/test/img.jpg", "dpi", "72", None)]
    tags = [("hash1", "rating", "5", 5.0)]
    db.upsert_batches(sources, images, metas, tags)
    prev = db.load_existing_sources()
    assert "src1" in prev
    assert prev["src1"] == (1.0, 100)
    db.close()


def test_filedb_delete_sources(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    sources = [("src1", "hash1", 100, 1.0)]
    db.upsert_batches(sources, [], [], [])
    db.delete_sources_by_paths(["src1"])
    prev = db.load_existing_sources()
    assert "src1" not in prev
    db.close()


def test_schema_no_change_preserves_data(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", 1.0)],
        [("c:/a.jpg", "k", "v", None)],
        [("hash1", "tag", "val", None)],
    )
    db.close()
    db2 = FileDB(tmp_path / "test.db")
    db2.start()
    db2.initialize_database()
    prev = db2.load_existing_sources()
    assert "src1" in prev
    db2.close()


def test_schema_change_drops_and_recreates(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", 1.0)],
        [],
        [],
    )
    db.conn.execute("ALTER TABLE sources ADD COLUMN extra_col TEXT")
    db.conn.commit()
    db.close()
    db2 = FileDB(tmp_path / "test.db")
    db2.start()
    db2.initialize_database()
    prev = db2.load_existing_sources()
    assert len(prev) == 0
    cols = [r[1] for r in db2.conn.execute("PRAGMA table_info('sources')").fetchall()]
    assert "extra_col" not in cols
    db2.close()


def test_schema_change_cascades_to_children(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", 1.0)],
        [("c:/a.jpg", "k", "v", None)],
        [],
    )
    db.conn.execute("ALTER TABLE sources ADD COLUMN extra_col TEXT")
    db.conn.commit()
    db.close()
    db2 = FileDB(tmp_path / "test.db")
    db2.start()
    db2.initialize_database()
    imgs = db2.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    metas = db2.conn.execute("SELECT COUNT(*) FROM meta_info").fetchone()[0]
    assert imgs == 0
    assert metas == 0
    db2.close()


def test_detect_no_changes_on_fresh_db(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    changed = db._detect_changed_tables()
    assert changed == set()
    db.close()


def test_table_signature_matches_expected(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    for name, _, create_sql in _TABLES:
        actual = _table_signature(db.conn, name)
        expected = _expected_table_signature(name, create_sql)
        assert actual == expected, f"{name}: actual={actual} expected={expected}"
    db.close()


def test_collection_status_table_exists(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    cols = [r[1] for r in db.conn.execute("PRAGMA table_info('collection_status')").fetchall()]
    assert "source" in cols
    assert "collector" in cols
    assert "status" in cols
    assert "collected_at" in cols
    db.close()


def test_upsert_basic_sources(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    sources = [("src1", "hash1", 100, 1.0)]
    images = [("c:/a.jpg", "src1", None)]
    db.upsert_basic_sources(sources, images)
    prev = db.load_existing_sources()
    assert "src1" in prev
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] is None
    db.close()


def test_upsert_basic_sources_preserves_existing_aspect(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", 1.5)],
    )
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 2.0)],
        [("c:/a.jpg", "src1", None)],
    )
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] == 1.5
    db.close()


def test_upsert_collection_results(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", None)],
    )
    db.upsert_collection_results(
        [("c:/a.jpg", "src1", 1.5)],
        [("c:/a.jpg", "width", "1920", 1920.0)],
        [("hash1", "rating", "5", 5.0)],
        [("src1", "exif", "ok", 2.0)],
    )
    row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/a.jpg'").fetchone()
    assert row[0] == 1.5
    cs_row = db.read_conn.execute("SELECT status FROM collection_status WHERE source='src1' AND collector='exif'").fetchone()
    assert cs_row[0] == "ok"
    meta_row = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/a.jpg' AND key='width'").fetchone()
    assert meta_row[0] == "1920"
    db.close()


def test_insert_pending_collection(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0), ("src2", "hash2", 200, 2.0)],
        [("c:/a.jpg", "src1", None), ("c:/b.jpg", "src2", None)],
    )
    db.insert_pending_collection(["src1", "src2"], ["exif"])
    rows = db.get_pending_sources("exif")
    assert len(rows) == 2
    sources = {r[0] for r in rows}
    assert sources == {"src1", "src2"}
    db.close()


def test_get_pending_sources_excludes_completed(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0), ("src2", "hash2", 200, 2.0)],
        [("c:/a.jpg", "src1", None), ("c:/b.jpg", "src2", None)],
    )
    db.insert_pending_collection(["src1", "src2"], ["exif"])
    db.upsert_collection_results([], [], [], [("src1", "exif", "ok", 1.0)])
    rows = db.get_pending_sources("exif")
    assert len(rows) == 1
    assert rows[0][0] == "src2"
    db.close()


def test_collection_status_cascade_delete(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", None)],
    )
    db.insert_pending_collection(["src1"], ["exif"])
    db.delete_sources_by_paths(["src1"])
    rows = db.conn.execute("SELECT COUNT(*) FROM collection_status").fetchone()[0]
    assert rows == 0
    db.close()


def test_rename_paths_single_file(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [("c:/old/img.jpg", "hash1", 100, 1.0)],
        [("c:/old/img.jpg", "c:/old/img.jpg", 1.5)],
        [("c:/old/img.jpg", "width", "1920", 1920.0), ("c:/old/img.jpg", "name", "img.jpg", None), ("c:/old/img.jpg", "path", "c:/old/img.jpg", None)],
        [("hash1", "rating", "5", 5.0)],
    )
    db.insert_pending_collection(["c:/old/img.jpg"], ["exif"])
    db.rename_paths([("c:/old/img.jpg", "c:/new/img.jpg")])
    assert db.read_conn.execute("SELECT COUNT(*) FROM sources WHERE source='c:/old/img.jpg'").fetchone()[0] == 0
    src_row = db.read_conn.execute("SELECT file_hash, size FROM sources WHERE source='c:/new/img.jpg'").fetchone()
    assert src_row == ("hash1", 100)
    file_row = db.read_conn.execute("SELECT aspect_ratio FROM files WHERE path='c:/new/img.jpg'").fetchone()
    assert file_row[0] == 1.5
    meta_row = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/new/img.jpg' AND key='width'").fetchone()
    assert meta_row[0] == "1920"
    assert db.read_conn.execute("SELECT COUNT(*) FROM meta_info WHERE path='c:/old/img.jpg'").fetchone()[0] == 0
    tag_row = db.read_conn.execute("SELECT value FROM tags WHERE file_hash='hash1' AND key='rating'").fetchone()
    assert tag_row[0] == "5"
    cs_row = db.read_conn.execute("SELECT source FROM collection_status WHERE source='c:/new/img.jpg'").fetchone()
    assert cs_row is not None
    assert db.read_conn.execute("SELECT COUNT(*) FROM collection_status WHERE source='c:/old/img.jpg'").fetchone()[0] == 0
    db.close()


def test_rename_paths_batch(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [
            ("c:/dir/a.jpg", "hash_a", 100, 1.0),
            ("c:/dir/b.jpg", "hash_b", 200, 2.0),
        ],
        [
            ("c:/dir/a.jpg", "c:/dir/a.jpg", 1.0),
            ("c:/dir/b.jpg", "c:/dir/b.jpg", 2.0),
        ],
        [("c:/dir/a.jpg", "k", "v1", None), ("c:/dir/b.jpg", "k", "v2", None)],
        [],
    )
    db.rename_paths(
        [
            ("c:/dir/a.jpg", "c:/new/a.jpg"),
            ("c:/dir/b.jpg", "c:/new/b.jpg"),
        ]
    )
    prev = db.load_existing_sources()
    assert "c:/new/a.jpg" in prev
    assert "c:/new/b.jpg" in prev
    assert "c:/dir/a.jpg" not in prev
    assert "c:/dir/b.jpg" not in prev
    meta_a = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/new/a.jpg' AND key='k'").fetchone()
    assert meta_a[0] == "v1"
    db.close()


def test_rename_paths_updates_filename(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_batches(
        [("c:/dir/old_name.jpg", "hash1", 100, 1.0)],
        [("c:/dir/old_name.jpg", "c:/dir/old_name.jpg", 1.0)],
        [("c:/dir/old_name.jpg", "name", "old_name.jpg", None), ("c:/dir/old_name.jpg", "path", "c:/dir/old_name.jpg", None)],
        [],
    )
    db.rename_paths([("c:/dir/old_name.jpg", "c:/dir/new_name.jpg")])
    row = db.read_conn.execute("SELECT value FROM meta_info WHERE path='c:/dir/new_name.jpg' AND key='name'").fetchone()
    assert row[0] == "new_name.jpg"
    db.close()


def test_rename_paths_nonexistent_source(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.rename_paths([("c:/nonexistent.jpg", "c:/new.jpg")])
    assert db.read_conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] == 0
    db.close()


def _setup_db_with_pending(tmp_path, sources_count=3):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    srcs = [(f"src{i}", f"h{i}", 100, 1.0) for i in range(sources_count)]
    imgs = [(f"src{i}", f"src{i}", 1.0) for i in range(sources_count)]
    db.upsert_basic_sources(srcs, imgs)
    db.insert_pending_collection([f"src{i}" for i in range(sources_count)], ["exif"])
    return db


def test_mark_dispatched(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(["src0", "src1"], "exif")
    pending = db.get_pending_sources("exif")
    assert len(pending) == 1
    assert pending[0][0] == "src2"
    dispatched = db.read_conn.execute("SELECT source FROM collection_status WHERE status='dispatched' ORDER BY source").fetchall()
    assert [r[0] for r in dispatched] == ["src0", "src1"]
    db.close()


def test_mark_dispatched_empty(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched([], "exif")
    pending = db.get_pending_sources("exif")
    assert len(pending) == 3
    db.close()


def test_mark_dispatched_only_affects_pending(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.conn.execute("UPDATE collection_status SET status='ok' WHERE source='src0'")
    db.conn.commit()
    db.mark_dispatched(["src0", "src1"], "exif")
    ok = db.read_conn.execute("SELECT status FROM collection_status WHERE source='src0'").fetchone()
    assert ok[0] == "ok"
    db.close()


def test_reset_stale_dispatched(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(["src0", "src1"], "exif")
    changed = db.reset_stale_dispatched(["exif"])
    assert changed == 2
    pending = db.get_pending_sources("exif")
    assert len(pending) == 3
    db.close()


def test_reset_stale_dispatched_no_collectors(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.mark_dispatched(["src0"], "exif")
    changed = db.reset_stale_dispatched()
    assert changed == 1
    pending = db.get_pending_sources("exif")
    assert len(pending) == 3
    db.close()


def test_reset_stale_dispatched_does_not_affect_ok(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    db.conn.execute("UPDATE collection_status SET status='ok' WHERE source='src0'")
    db.conn.commit()
    db.mark_dispatched(["src1"], "exif")
    changed = db.reset_stale_dispatched(["exif"])
    assert changed == 1
    ok = db.read_conn.execute("SELECT status FROM collection_status WHERE source='src0'").fetchone()
    assert ok[0] == "ok"
    db.close()


def test_get_sources_without_collector(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "h1", 100, 1.0), ("src2", "h2", 200, 2.0), ("src3", "h3", 300, 3.0)],
        [("c:/a.jpg", "src1", None), ("c:/b.jpg", "src2", None), ("c:/c.jpg", "src3", None)],
    )
    db.insert_pending_collection(["src1"], ["exif"])
    missing = db.get_sources_without_collector("exif")
    assert set(missing) == {"src2", "src3"}
    db.close()


def test_get_sources_without_collector_empty_when_all_have(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "h1", 100, 1.0)],
        [("c:/a.jpg", "src1", None)],
    )
    db.insert_pending_collection(["src1"], ["exif"])
    missing = db.get_sources_without_collector("exif")
    assert missing == []
    db.close()


def test_get_sources_without_collector_new_collector(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "h1", 100, 1.0)],
        [("c:/a.jpg", "src1", None)],
    )
    db.insert_pending_collection(["src1"], ["exif"])
    missing = db.get_sources_without_collector("ocr")
    assert missing == ["src1"]
    db.close()


def test_concurrent_writes_no_error(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    count = 50
    srcs = [(f"src{i}", f"h{i}", 100, 1.0) for i in range(count)]
    imgs = [(f"src{i}", f"src{i}", 1.0) for i in range(count)]
    db.upsert_basic_sources(srcs, imgs)
    db.insert_pending_collection([f"src{i}" for i in range(count)], ["exif"])
    errors = []
    barrier = threading.Barrier(2)

    def writer_a():
        try:
            barrier.wait()
            db.mark_dispatched([f"src{i}" for i in range(0, count, 2)], "exif")
        except Exception as e:
            errors.append(e)

    def writer_b():
        try:
            barrier.wait()
            db.upsert_basic_sources(
                [(f"src_new{i}", f"hn{i}", 200, 2.0) for i in range(10)],
                [(f"src_new{i}", f"src_new{i}", 1.0) for i in range(10)],
            )
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=writer_a)
    t2 = threading.Thread(target=writer_b)
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    assert errors == [], f"Concurrent writes raised errors: {errors}"
    db.close()


def _setup_db_with_collected(tmp_path, collectors=("exif",)):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    srcs = [("src0", "h0", 100, 1.0), ("src1", "h1", 200, 2.0)]
    imgs = [("c:/a.jpg", "src0", 1.5), ("c:/b.jpg", "src1", 1.0)]
    metas = [
        ("c:/a.jpg", "exif.width", "1920", 1920.0),
        ("c:/a.jpg", "exif.height", "1080", 1080.0),
        ("c:/b.jpg", "exif.width", "800", 800.0),
        ("c:/a.jpg", "basic.name", "a.jpg", None),
    ]
    tags = [
        ("h0", "exif.camera", "Canon", None),
        ("h1", "exif.camera", "Nikon", None),
        ("h0", "ai.style", "portrait", None),
    ]
    db.upsert_batches(srcs, imgs, metas, tags)
    for coll in collectors:
        db.insert_pending_collection(["src0", "src1"], [coll])
        db.mark_dispatched(["src0", "src1"], coll)
        db.conn.execute(
            "UPDATE collection_status SET status='ok', collected_at=1.0 WHERE collector=?",
            (coll,),
        )
        db.conn.commit()
    return db


def test_delete_collector_data_deletes_meta_and_tags(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del, cs_del = db.delete_collector_data("exif")
    assert meta_del == 3
    assert tags_del == 2
    assert cs_del == 2
    remaining_meta = db.read_conn.execute("SELECT key FROM meta_info").fetchall()
    assert [r[0] for r in remaining_meta] == ["basic.name"]
    remaining_tags = db.read_conn.execute("SELECT key FROM tags").fetchall()
    assert [r[0] for r in remaining_tags] == ["ai.style"]
    cs = db.read_conn.execute("SELECT * FROM collection_status WHERE collector='exif'").fetchall()
    assert cs == []
    db.close()


def test_delete_collector_data_re_collect(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del, cs_affected = db.delete_collector_data("exif", re_collect=True)
    assert meta_del == 3
    assert tags_del == 2
    assert cs_affected == 2
    rows = db.read_conn.execute("SELECT status, collected_at FROM collection_status WHERE collector='exif'").fetchall()
    assert len(rows) == 2
    for status, collected_at in rows:
        assert status == "pending"
        assert collected_at is None
    db.close()


def test_delete_collector_data_no_match(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del, cs_del = db.delete_collector_data("nonexistent")
    assert meta_del == 0
    assert tags_del == 0
    assert cs_del == 0
    db.close()


def test_delete_keys_deletes_specific_keys(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del = db.delete_keys(["exif.width"])
    assert meta_del == 2
    assert tags_del == 0
    remaining = db.read_conn.execute("SELECT key FROM meta_info WHERE key = 'exif.width'").fetchall()
    assert remaining == []
    kept = db.read_conn.execute("SELECT key FROM meta_info WHERE key = 'exif.height'").fetchall()
    assert len(kept) == 1
    db.close()


def test_delete_keys_deletes_from_tags(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del = db.delete_keys(["exif.camera"])
    assert meta_del == 0
    assert tags_del == 2
    remaining = db.read_conn.execute("SELECT key FROM tags WHERE key = 'exif.camera'").fetchall()
    assert remaining == []
    db.close()


def test_delete_keys_empty_list(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del = db.delete_keys([])
    assert meta_del == 0
    assert tags_del == 0
    db.close()


def test_delete_keys_no_match(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_del, tags_del = db.delete_keys(["nonexistent.key"])
    assert meta_del == 0
    assert tags_del == 0
    db.close()


def test_reset_collector_status(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    meta_before = db.read_conn.execute("SELECT COUNT(*) FROM meta_info").fetchone()[0]
    tags_before = db.read_conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    affected = db.reset_collector_status("exif")
    assert affected == 2
    rows = db.read_conn.execute("SELECT status, collected_at FROM collection_status WHERE collector='exif'").fetchall()
    assert len(rows) == 2
    for status, collected_at in rows:
        assert status == "pending"
        assert collected_at is None
    meta_after = db.read_conn.execute("SELECT COUNT(*) FROM meta_info").fetchone()[0]
    tags_after = db.read_conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0]
    assert meta_after == meta_before
    assert tags_after == tags_before
    db.close()


def test_reset_collector_status_no_match(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    affected = db.reset_collector_status("nonexistent")
    assert affected == 0
    db.close()


def test_collector_data_counts(tmp_path):
    db = _setup_db_with_collected(tmp_path, collectors=("exif", "ocr"))
    counts = dict(db.collector_data_counts())
    assert counts["exif"] == 2
    assert counts["ocr"] == 2
    db.close()


def test_collector_data_counts_empty(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    counts = db.collector_data_counts()
    assert counts == []
    db.close()


def test_collector_data_counts_excludes_pending(tmp_path):
    db = _setup_db_with_pending(tmp_path)
    counts = db.collector_data_counts()
    assert counts == []
    db.close()


def test_prefix_data_summary(tmp_path):
    db = _setup_db_with_collected(tmp_path)
    rows = db.prefix_data_summary()
    data = {r[0]: (r[1], r[2]) for r in rows}
    assert data["exif"] == (3, 2)
    assert data["basic"] == (1, 0)
    assert data["ai"] == (0, 1)
    db.close()


def test_prefix_data_summary_empty(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    assert db.prefix_data_summary() == []
    db.close()


def test_prefix_data_summary_unprefixed(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    srcs = [("src0", "h0", 100, 1.0)]
    imgs = [("src0", "src0", 1.0)]
    metas = [("src0", "raw_key", "val", None)]
    db.upsert_batches(srcs, imgs, metas, [])
    rows = db.prefix_data_summary()
    data = {r[0]: (r[1], r[2]) for r in rows}
    assert data[""] == (1, 0)
    db.close()


def test_sql_constants_are_valid():
    conn = sqlite3.connect(":memory:")
    for _, _, sql in _TABLES:
        conn.execute(sql)
    conn.commit()
    for const in [_SQL_UPSERT_SOURCES, _SQL_UPSERT_FILES, _SQL_UPSERT_FILES_COALESCE, _SQL_UPSERT_META, _SQL_UPSERT_TAGS, _SQL_UPSERT_COLLECTION_STATUS]:
        assert "INSERT" in const
        assert "ON CONFLICT" in const
    conn.close()


def test_ensure_hash_indexes_deduplicates(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    cur = db.get_writer_cursor()
    db._ensure_hash_indexes(
        cur,
        [("src1", "hash1", 100, 1.0), ("src2", "hash2", 200, 2.0)],
        [("hash1", "tag", "val", None)],
    )
    db.conn.commit()
    rows = db.conn.execute("SELECT COUNT(*) FROM hash_index").fetchone()[0]
    assert rows == 2
    cur.close()
    db.close()


def test_backup_and_recreate_corrupt_db(tmp_path):
    db_path = tmp_path / "corrupt.db"
    conn = sqlite3.connect(str(db_path))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE dummy (id INTEGER, data TEXT)")
    conn.executemany(
        "INSERT INTO dummy VALUES (?, ?)",
        [(i, "x" * 200) for i in range(500)],
    )
    conn.commit()
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    with open(str(db_path), "r+b") as f:
        f.seek(4096 * 2)
        f.write(b"\x00" * 4096)
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    assert db.conn is not None
    assert db.backup_path.exists()
    db.close()


def test_insert_pending_collection_skips_missing_sources(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0)],
        [("c:/a.jpg", "src1", None)],
    )
    db.insert_pending_collection(["src1", "nonexistent_src"], ["exif"])
    rows = db.read_conn.execute("SELECT source FROM collection_status WHERE collector='exif'").fetchall()
    sources = {r[0] for r in rows}
    assert sources == {"src1"}
    assert "nonexistent_src" not in sources
    db.close()


def _setup_db_for_detacher(tmp_path):
    db = FileDB(tmp_path / "test.db")
    db.start()
    db.initialize_database()
    db.upsert_basic_sources(
        [("src1", "hash1", 100, 1.0), ("src2", "hash2", 200, 2.0)],
        [("src1", "src1", 1.0), ("src2", "src2", 1.5)],
        [("src1", "exif.parameters", "steps:20", None), ("src1", "exif.other", "val", None), ("src2", "exif.parameters", "steps:30", None)],
    )
    db.upsert_collection_results([], [], [("hash1", "wd14.general", "cat", None)], [])
    return db


def test_delete_meta_and_tags_by_keys(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    db.delete_meta_and_tags_by_keys(
        [
            ("src1", "hash1", ["exif.parameters", "wd14.general"]),
        ]
    )
    cur = db.get_reader_cursor()
    cur.execute("SELECT key FROM meta_info WHERE path='src1'")
    meta_keys = {r[0] for r in cur.fetchall()}
    assert "exif.parameters" not in meta_keys
    assert "exif.other" in meta_keys
    cur.execute("SELECT key FROM tags WHERE file_hash='hash1'")
    tag_keys = {r[0] for r in cur.fetchall()}
    assert "wd14.general" not in tag_keys
    cur.close()
    db.close()


def test_delete_meta_and_tags_by_keys_no_hash(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    db.delete_meta_and_tags_by_keys(
        [
            ("src1", None, ["exif.parameters"]),
        ]
    )
    cur = db.get_reader_cursor()
    cur.execute("SELECT key FROM meta_info WHERE path='src1'")
    meta_keys = {r[0] for r in cur.fetchall()}
    assert "exif.parameters" not in meta_keys
    cur.execute("SELECT key FROM tags WHERE file_hash='hash1'")
    tag_keys = {r[0] for r in cur.fetchall()}
    assert "wd14.general" in tag_keys
    cur.close()
    db.close()


def test_delete_meta_and_tags_by_keys_empty(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    db.delete_meta_and_tags_by_keys([])
    cur = db.get_reader_cursor()
    cur.execute("SELECT COUNT(*) FROM meta_info WHERE path='src1'")
    assert cur.fetchone()[0] == 2
    cur.close()
    db.close()


def test_find_sources_with_trigger_keys(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    sources = db.find_sources_with_trigger_keys(("exif.parameters",), "sd_meta")
    assert set(sources) == {"src1", "src2"}
    db.close()


def test_find_sources_with_trigger_keys_excludes_processed(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    db.insert_pending_collection(["src1"], ["sd_meta"])
    db.upsert_collection_results([], [], [], [("src1", "sd_meta", "ok", 1.0)])
    sources = db.find_sources_with_trigger_keys(("exif.parameters",), "sd_meta")
    assert "src1" not in sources
    assert "src2" in sources
    db.close()


def test_find_sources_with_trigger_keys_from_tags(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    sources = db.find_sources_with_trigger_keys(("wd14.general",), "tag_proc")
    assert "src1" in sources
    db.close()


def test_get_trigger_metadata(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    meta = db.get_trigger_metadata(["src1", "src2"], ("exif.parameters",))
    assert meta["src1"] == {"exif.parameters": "steps:20"}
    assert meta["src2"] == {"exif.parameters": "steps:30"}
    db.close()


def test_get_trigger_metadata_includes_tags(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    meta = db.get_trigger_metadata(["src1"], ("wd14.general",))
    assert meta["src1"] == {"wd14.general": "cat"}
    db.close()


def test_get_trigger_metadata_empty(tmp_path):
    db = _setup_db_for_detacher(tmp_path)
    meta = db.get_trigger_metadata([], ("exif.parameters",))
    assert meta == {}
    meta = db.get_trigger_metadata(["src1"], ())
    assert meta == {}
    db.close()

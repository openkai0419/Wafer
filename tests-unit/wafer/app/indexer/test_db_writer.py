import os
import py_compile
import tempfile

import pytest

from wafer.app.indexer.db_writer import DatabaseWriter


def test_compile():
    py_compile.compile("wafer/app/indexer/db_writer.py")


@pytest.fixture
def writer(tmp_path):
    db_path = tmp_path / "test.db"
    w = DatabaseWriter(db_path)
    w.start()
    w.initialize()
    yield w
    w.close()


def test_start_and_close(tmp_path):
    db_path = tmp_path / "test.db"
    w = DatabaseWriter(db_path)
    w.start()
    assert w.db.conn is not None
    w.close()
    assert w.db.conn is None


def test_initialize_creates_tables(writer):
    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
    tables = {row[0] for row in cur.fetchall()}
    cur.close()
    assert "sources" in tables
    assert "files" in tables
    assert "collection_status" in tables


def test_upsert_and_delete_sources(writer):
    source_entries = [("/a.png", "hash1", 100, 1.0)]
    image_entries = [("/a.png", "/a.png", 1.5)]
    writer.upsert_sources(source_entries, image_entries)

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT source FROM sources")
    rows = cur.fetchall()
    cur.close()
    assert len(rows) == 1
    assert rows[0][0] == "/a.png"

    writer.delete_sources(["/a.png"])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT source FROM sources")
    rows = cur.fetchall()
    cur.close()
    assert len(rows) == 0


def test_rename_paths(writer):
    source_entries = [("/old.png", "hash1", 100, 1.0)]
    image_entries = [("/old.png", "/old.png", 1.0)]
    writer.upsert_sources(source_entries, image_entries)

    writer.rename_paths([("/old.png", "/new.png")])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT source FROM sources")
    rows = cur.fetchall()
    cur.close()
    assert rows[0][0] == "/new.png"


def test_insert_pending_and_mark_dispatched(writer):
    source_entries = [("/a.png", "hash1", 100, 1.0)]
    image_entries = [("/a.png", "/a.png", 1.0)]
    writer.upsert_sources(source_entries, image_entries)

    writer.insert_pending(["/a.png"], ["exif"])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png' AND collector='exif'")
    assert cur.fetchone()[0] == "pending"
    cur.close()

    writer.mark_dispatched(["/a.png"], "exif")

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png' AND collector='exif'")
    assert cur.fetchone()[0] == "dispatched"
    cur.close()


def test_reset_stale(writer):
    source_entries = [("/a.png", "hash1", 100, 1.0)]
    image_entries = [("/a.png", "/a.png", 1.0)]
    writer.upsert_sources(source_entries, image_entries)
    writer.insert_pending(["/a.png"], ["exif"])
    writer.mark_dispatched(["/a.png"], "exif")

    writer.reset_stale(["exif"])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT status FROM collection_status WHERE source='/a.png'")
    assert cur.fetchone()[0] == "pending"
    cur.close()


def test_upsert_collection_results(writer):
    source_entries = [("/a.png", "hash1", 100, 1.0)]
    image_entries = [("/a.png", "/a.png", 1.0)]
    writer.upsert_sources(source_entries, image_entries)
    writer.insert_pending(["/a.png"], ["exif"])

    writer.upsert_results(
        [],
        [("/a.png", "width", "1920", 1920.0)],
        [("hash1", "rating", "5", 5.0)],
        [("/a.png", "exif", "ok", 2.0)],
    )

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT value FROM meta_info WHERE path='/a.png' AND key='width'")
    assert cur.fetchone()[0] == "1920"
    cur.execute("SELECT value FROM tags WHERE file_hash='hash1' AND key='rating'")
    assert cur.fetchone()[0] == "5"
    cur.close()


def test_delete_orphans(writer):
    writer.delete_orphans()


def test_checkpoint(writer):
    writer.checkpoint("PASSIVE")

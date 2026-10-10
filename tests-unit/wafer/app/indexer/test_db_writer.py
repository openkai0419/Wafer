import pytest

from wafer.app.indexer.db_writer import DatabaseWriter
from wafer.core.db.db_utils import build_basic_entries
from wafer.core.common.paths import normalize_path
from wafer.core.common.virtual_paths import build_virtual_path


@pytest.fixture
def writer(tmp_path):
    db_path = tmp_path / "test.db"
    w = DatabaseWriter(db_path)
    w.start()
    w.initialize()
    yield w
    w.close()


def test_infer_moved_sources_matches_delete_create_by_signature(writer, tmp_path):
    old_path = tmp_path / "old.jpg"
    new_dir = tmp_path / "sub"
    new_dir.mkdir()
    new_path = new_dir / "old.jpg"
    old_path.write_bytes(b"same-content" * 128)
    old_norm = normalize_path(str(old_path))
    info = {old_norm: (old_path.stat().st_mtime, old_path.stat().st_size, old_path.stat().st_ctime)}
    source_entries, file_entries = build_basic_entries([old_norm], info, {old_norm: 1.0}, 1.0)
    writer.upsert_sources(source_entries, file_entries)
    old_path.rename(new_path)

    pairs = writer.infer_moved_sources([str(old_path)], [str(new_path)])

    assert pairs == [(old_norm, normalize_path(str(new_path)))]


def test_infer_moved_sources_skips_ambiguous_duplicates(writer, tmp_path):
    old_a = tmp_path / "a.jpg"
    old_b = tmp_path / "b.jpg"
    new_a = tmp_path / "new_a.jpg"
    new_b = tmp_path / "new_b.jpg"
    for path in (old_a, old_b):
        path.write_bytes(b"same-content" * 128)
    old_norms = [normalize_path(str(old_a)), normalize_path(str(old_b))]
    info = {normalize_path(str(path)): (path.stat().st_mtime, path.stat().st_size, path.stat().st_ctime) for path in (old_a, old_b)}
    source_entries, file_entries = build_basic_entries(old_norms, info, {path: 1.0 for path in old_norms}, 1.0)
    writer.upsert_sources(source_entries, file_entries)
    old_a.rename(new_a)
    old_b.rename(new_b)

    pairs = writer.infer_moved_sources([str(old_a), str(old_b)], [str(new_a), str(new_b)])

    assert pairs == []


def test_zip_collection_deletes_stale_child_rows(writer):
    source = "/a.zip"
    old_child = build_virtual_path(source, "old.png")
    keep_child = build_virtual_path(source, "keep.png")
    writer.upsert_sources([(source, "hash_zip", 100, 1.0)], [(source, source, 1.0)])
    writer.upsert_results(
        [(old_child, source, "old.png", 1.0, "zip"), (keep_child, source, "keep.png", 1.0, "zip")],
        [],
        [],
        [(source, "zip", "ok", 2.0)],
    )
    writer.upsert_results(
        [(keep_child, source, "keep.png", 2.0, "zip")],
        [],
        [],
        [(source, "zip", "ok", 3.0)],
    )

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT path FROM files WHERE source = ? ORDER BY path", (source,))
    paths = [row[0] for row in cur.fetchall()]
    cur.close()
    assert paths == [source, keep_child]


def test_zip_collection_empty_result_deletes_child_rows(writer):
    source = "/a.zip"
    child = build_virtual_path(source, "old.png")
    writer.upsert_sources([(source, "hash_zip", 100, 1.0)], [(source, source, 1.0)])
    writer.upsert_results(
        [(child, source, "old.png", 1.0, "zip")],
        [],
        [],
        [(source, "zip", "ok", 2.0)],
    )
    writer.upsert_results([], [], [], [(source, "zip", "ok", 3.0)])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT path FROM files WHERE source = ? ORDER BY path", (source,))
    paths = [row[0] for row in cur.fetchall()]
    cur.close()
    assert paths == [source]


def test_zip_collection_fail_does_not_delete_child_rows(writer):
    source = "/a.zip"
    child = build_virtual_path(source, "old.png")
    writer.upsert_sources([(source, "hash_zip", 100, 1.0)], [(source, source, 1.0)])
    writer.upsert_results(
        [(child, source, "old.png", 1.0, "zip")],
        [],
        [],
        [(source, "zip", "ok", 2.0)],
    )
    writer.upsert_results([], [], [], [(source, "zip", "fail", 3.0)])

    cur = writer.db.get_reader_cursor()
    cur.execute("SELECT path FROM files WHERE source = ? ORDER BY path", (source,))
    paths = [row[0] for row in cur.fetchall()]
    cur.close()
    assert paths == [source, child]


def test_delete_sources_retriggers_sources_sharing_the_hash(writer, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "wafer.app.indexer.receivers.parser_receiver.trigger_parser_pending",
        lambda source_keys, w, *a, **kw: triggered.update(source_keys),
    )
    writer.db.upsert_basic_sources(
        [("src1", "shared", 10, 1.0), ("src2", "shared", 10, 1.0)],
        [("src1", "src1", 1.0), ("src2", "src2", 1.0)],
    )

    writer.delete_sources(["src2"])

    assert triggered == {"src1": {"file_hash"}}


def test_delete_sources_does_not_retrigger_unique_hashes(writer, monkeypatch):
    triggered = {}
    monkeypatch.setattr(
        "wafer.app.indexer.receivers.parser_receiver.trigger_parser_pending",
        lambda source_keys, w, *a, **kw: triggered.update(source_keys),
    )
    writer.db.upsert_basic_sources(
        [("src1", "one", 10, 1.0), ("src2", "two", 10, 1.0)],
        [("src1", "src1", 1.0), ("src2", "src2", 1.0)],
    )

    writer.delete_sources(["src2"])

    assert triggered == {}

import pytest

from wafer.core.db.file_db import SOURCE_TRIGGER_KEYS, FileDB, _split_trigger_keys


@pytest.fixture
def db(tmp_path):
    database = FileDB(tmp_path / "test.db")
    database.start()
    database.initialize_database()
    yield database
    database.close()


def _seed(database, source="src1", file_hash="fast1", path=None):
    path = path or source
    database.upsert_batches(
        [(source, file_hash, 100, 1.0)],
        [(path, source, 1.0)],
        [],
        [(file_hash, "wd14.general", "cat", None)],
    )


def test_split_trigger_keys():
    source_columns, meta_keys = _split_trigger_keys(("file_hash", "exiftool.Comment", "size"))
    assert source_columns == ["file_hash", "size"]
    assert meta_keys == ["exiftool.Comment"]


def test_update_source_hashes_replaces_hash_and_keeps_tags(db):
    _seed(db)
    impacted = db.update_source_hashes([("src1", "full1")])
    assert impacted == ["src1"]

    cur = db.get_reader_cursor()
    assert cur.execute("SELECT file_hash FROM sources WHERE source = 'src1'").fetchone()[0] == "full1"
    assert cur.execute("SELECT value FROM tags WHERE file_hash = 'full1' AND key = 'wd14.general'").fetchone()[0] == "cat"
    cur.close()


def test_update_source_hashes_returns_siblings_sharing_old_hash(db):
    _seed(db, source="src1", file_hash="shared", path="src1")
    _seed(db, source="src2", file_hash="shared", path="src2")
    impacted = db.update_source_hashes([("src1", "full1")])
    assert sorted(impacted) == ["src1", "src2"]


def test_update_source_hashes_ignores_unchanged_and_unknown(db):
    _seed(db)
    assert db.update_source_hashes([("src1", "fast1")]) == []
    assert db.update_source_hashes([("missing", "full1")]) == []
    assert db.update_source_hashes([]) == []
    assert db.update_source_hashes([("src1", "")]) == []


def test_update_source_hashes_does_not_overwrite_existing_tag_of_target_hash(db):
    _seed(db)
    db.upsert_batches([], [], [], [("full1", "wd14.general", "dog", None)])
    db.update_source_hashes([("src1", "full1")])

    cur = db.get_reader_cursor()
    assert cur.execute("SELECT value FROM tags WHERE file_hash = 'full1' AND key = 'wd14.general'").fetchone()[0] == "dog"
    cur.close()


def test_get_trigger_metadata_returns_source_columns(db):
    _seed(db)
    metadata = db.get_trigger_metadata(["src1"], ("file_hash", "size"))
    assert metadata["src1"]["file_hash"] == "fast1"
    assert metadata["src1"]["size"] == "100"


def test_get_trigger_metadata_mixes_source_columns_and_meta_keys(db):
    _seed(db)
    db.upsert_batches([], [], [("src1", "exiftool.Comment", "hello", None)], [])
    metadata = db.get_trigger_metadata(["src1"], ("file_hash", "exiftool.Comment"))
    assert metadata["src1"] == {"file_hash": "fast1", "exiftool.Comment": "hello"}


def test_find_sources_with_trigger_keys_uses_source_columns(db):
    _seed(db)
    _seed(db, source="src2", file_hash="fast2")
    assert sorted(db.find_sources_with_trigger_keys(("file_hash",), "full_hash")) == ["src1", "src2"]

    db.insert_pending_collection(["src1"], ["full_hash"])
    assert db.find_sources_with_trigger_keys(("file_hash",), "full_hash") == ["src2"]


def test_source_trigger_keys_match_sources_columns(db):
    cur = db.get_reader_cursor()
    columns = {row[1] for row in cur.execute("PRAGMA table_info(sources)").fetchall()}
    cur.close()
    assert set(SOURCE_TRIGGER_KEYS) <= columns


def test_delete_sources_returns_remaining_sources_sharing_hash(db):
    _seed(db, source="src1", file_hash="shared")
    _seed(db, source="src2", file_hash="shared")
    _seed(db, source="src3", file_hash="shared")

    impacted = db.delete_sources_by_paths(["src2", "src3"])

    assert impacted == ["src1"]


def test_delete_sources_returns_nothing_for_unique_hash(db):
    _seed(db, source="src1", file_hash="unique1")
    _seed(db, source="src2", file_hash="unique2")

    assert db.delete_sources_by_paths(["src1"]) == []


def test_delete_source_trees_returns_remaining_sources_sharing_hash(db):
    _seed(db, source="root/a.png", file_hash="shared")
    _seed(db, source="keep/b.png", file_hash="shared")

    impacted = db.delete_sources_by_path_prefixes(["root"])

    assert impacted == ["keep/b.png"]


def test_delete_meta_and_tags_by_keys_separates_scopes(db):
    _seed(db, source="src1", file_hash="hash1")
    db.upsert_batches([], [], [("src1", "exiftool.Comment", "hello", None)], [])

    db.delete_meta_and_tags_by_keys([("src1", "hash1", ["exiftool.Comment"], [])])

    cur = db.get_reader_cursor()
    assert cur.execute("SELECT COUNT(*) FROM meta_info WHERE key = 'exiftool.Comment'").fetchone()[0] == 0
    assert cur.execute("SELECT COUNT(*) FROM tags WHERE key = 'wd14.general'").fetchone()[0] == 1
    cur.close()


def test_delete_meta_and_tags_by_keys_deletes_tag_scope_only(db):
    _seed(db, source="src1", file_hash="hash1")
    db.upsert_batches([], [], [("src1", "wd14.general", "hello", None)], [])

    db.delete_meta_and_tags_by_keys([("src1", "hash1", [], ["wd14.general"])])

    cur = db.get_reader_cursor()
    assert cur.execute("SELECT COUNT(*) FROM tags WHERE key = 'wd14.general'").fetchone()[0] == 0
    assert cur.execute("SELECT COUNT(*) FROM meta_info WHERE key = 'wd14.general'").fetchone()[0] == 1
    cur.close()

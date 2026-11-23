import pytest

from extensions.duplicate.duplicate import TAG, DuplicateParser
from wafer.core.db.file_db import FileDB

TAG_KEY = f"{DuplicateParser.NAME}.{TAG}"


@pytest.fixture
def parser(tmp_path, monkeypatch):
    import wafer.core.common.paths as paths

    db_path = tmp_path / "dup.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))

    plugin = DuplicateParser()
    plugin.db_name = "dup"
    plugin.db = db
    yield plugin
    plugin.shutdown()
    db.close()


def _add_source(db, source, file_hash):
    db.upsert_basic_sources([(source, file_hash, 100, 1.0)], [(source, source, 1.0)])


def test_flags_when_another_source_shares_the_hash(parser):
    _add_source(parser.db, "/a.png", "h1")
    _add_source(parser.db, "/b.png", "h1")
    result = parser.process("/a.png", (1.0, 100, "h1"), {})
    assert result.status is True
    assert result.tags == {TAG: "1"}


def test_no_tag_for_unique_hash(parser):
    _add_source(parser.db, "/a.png", "h1")
    result = parser.process("/a.png", (1.0, 100, "h1"), {})
    assert result.tags is None
    assert result.delete_tag_keys is None


def test_does_not_rewrite_existing_flag(parser):
    _add_source(parser.db, "/a.png", "h1")
    _add_source(parser.db, "/b.png", "h1")
    parser.db.upsert_collection_results([], [], [("/a.png", TAG_KEY, "1", 1.0)], [])
    result = parser.process("/a.png", (1.0, 100, "h1"), {})
    assert result.tags is None
    assert result.delete_tag_keys is None


def test_removes_flag_when_hash_is_no_longer_shared(parser):
    _add_source(parser.db, "/a.png", "h1")
    parser.db.upsert_collection_results([], [], [("/a.png", TAG_KEY, "1", 1.0)], [])
    result = parser.process("/a.png", (1.0, 100, "h1"), {})
    assert result.delete_tag_keys == [TAG_KEY]
    assert result.tags is None


def test_fails_without_file_hash(parser):
    result = parser.process("/a.png", (1.0, 100), {})
    assert result.status is False


def test_fails_on_failed_hash_sentinel(parser):
    from wafer.core.common.hashes import HASH_FAILED

    _add_source(parser.db, "/a.png", HASH_FAILED)
    _add_source(parser.db, "/b.png", HASH_FAILED)
    result = parser.process("/a.png", (1.0, 100, HASH_FAILED), {})
    assert result.status is False
    assert result.tags is None


def test_batch_matches_one_by_one(parser):
    _add_source(parser.db, "/a.png", "h1")
    _add_source(parser.db, "/b.png", "h1")
    _add_source(parser.db, "/c.png", "h2")
    _add_source(parser.db, "/d.png", "h3")
    _add_source(parser.db, "/e.png", "h3")
    parser.db.upsert_collection_results([], [], [("/c.png", TAG_KEY, "1", 1.0), ("/d.png", TAG_KEY, "1", 1.0)], [])
    from wafer.core.common.hashes import HASH_FAILED

    info = {"/a.png": (1.0, 100, "h1"), "/b.png": (1.0, 100, "h1"), "/c.png": (1.0, 100, "h2"), "/d.png": (1.0, 100, "h3"), "/x.png": (1.0, 100), "/f.png": (1.0, 100, HASH_FAILED)}
    paths = list(info)
    expected = [parser.process(p, info[p], {}) for p in paths]
    assert parser.process_batch(paths, info, {p: {} for p in paths}) == expected
    assert [(r.status, r.tags, r.delete_tag_keys) for r in expected] == [
        (True, {TAG: "1"}, None), (True, {TAG: "1"}, None), (True, None, [TAG_KEY]), (True, None, None), (False, None, None), (False, None, None)]


def test_batch_reads_the_database_once(parser, monkeypatch):
    for i in range(5):
        _add_source(parser.db, f"/{i}.png", f"h{i % 2}")
    calls = []
    original = parser.read_db
    monkeypatch.setattr(parser, "read_db", lambda read, default=None: calls.append(1) or original(read, default))
    paths = [f"/{i}.png" for i in range(5)]
    parser.process_batch(paths, {p: (1.0, 100, f"h{i % 2}") for i, p in enumerate(paths)}, {p: {} for p in paths})
    assert len(calls) == 1

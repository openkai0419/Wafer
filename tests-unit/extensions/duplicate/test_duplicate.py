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
    db.upsert_batches([(source, file_hash, 100, 1.0)], [(source, source, 1.0)], [], [])


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
    parser.db.upsert_batches([], [], [], [("h1", TAG_KEY, "1", 1.0)])
    result = parser.process("/a.png", (1.0, 100, "h1"), {})
    assert result.tags is None
    assert result.delete_tag_keys is None


def test_removes_flag_when_hash_is_no_longer_shared(parser):
    _add_source(parser.db, "/a.png", "h1")
    parser.db.upsert_batches([], [], [], [("h1", TAG_KEY, "1", 1.0)])
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


def test_triggers_on_source_file_hash_without_collector():
    from wafer.core.db.file_db import SOURCE_TRIGGER_KEYS
    from wafer.plugin.parser.base import required_collectors

    assert DuplicateParser.TRIGGER_KEYS == ("file_hash",)
    assert "file_hash" in SOURCE_TRIGGER_KEYS
    assert required_collectors(DuplicateParser.TRIGGER_KEYS) == {}
    assert DuplicateParser.DEFAULT_ENABLED is False
    assert DuplicateParser.NAME == "duplicate"


def test_registered_as_known_extension():
    from wafer.plugin.badges import resolve_badge, KNOWN_EXTENSIONS

    assert "duplicate" in KNOWN_EXTENSIONS
    assert resolve_badge("duplicate") is None

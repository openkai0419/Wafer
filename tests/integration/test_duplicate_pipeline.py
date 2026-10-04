import time

import pytest

from extensions.duplicate.duplicate import TAG, DuplicateParser
from extensions.duplicate.full_hash import FULL_HASH_LENGTH, FullHashParser
from wafer.app.indexer.receivers.collector_receiver import _parse_batch as parse_collector_batch
from wafer.app.indexer.receivers.parser_receiver import _parse_batch
from wafer.core.db.db_utils import build_basic_entries
from wafer.core.db.file_db import FileDB
from wafer.core.common.paths import normalize_path

TAG_KEY = f"{DuplicateParser.NAME}.{TAG}"


@pytest.fixture
def db(tmp_path, monkeypatch):
    import wafer.core.common.paths as paths

    db_path = tmp_path / "duplicate.db"
    database = FileDB(db_path)
    database.start()
    database.initialize_database()
    monkeypatch.setattr(paths, "data_db_path", lambda name: str(db_path))
    yield database
    database.close()


def _register(database, paths):
    file_info = {}
    for path in paths:
        stat_result = path.stat()
        file_info[normalize_path(str(path))] = (stat_result.st_mtime, stat_result.st_size, stat_result.st_ctime)
    source_entries, file_entries = build_basic_entries(list(file_info), file_info, {}, time.time())
    database.upsert_basic_sources(source_entries, file_entries)
    return [source for source, *_ in source_entries]


def _file_info(database, source):
    cur = database.get_reader_cursor()
    try:
        return cur.execute("SELECT modified, size, file_hash FROM sources WHERE source = ?", (source,)).fetchone()
    finally:
        cur.close()


def _run_parser(database, plugin, sources):
    results = []
    for source in sources:
        info = _file_info(database, source)
        result = plugin.process(source, info, {})
        if result is None:
            continue
        entry = result.to_dict()
        entry["parser"] = plugin.NAME
        results.append(entry)
    data = _parse_batch(results)
    impacted = database.update_source_hashes(data["hash_updates"])
    database.upsert_collection_results(
        [],
        data["meta_info_entries"],
        data["tag_entries"],
        data["collector_status"],
        cleanup=False,
    )
    if data["delete_entries"]:
        database.delete_meta_and_tags_by_keys(data["delete_entries"])
    return impacted


def _tagged_sources(database):
    cur = database.get_reader_cursor()
    try:
        rows = cur.execute(
            "SELECT s.source FROM tags t JOIN sources s ON s.file_hash = t.file_hash WHERE t.key = ?",
            (TAG_KEY,),
        ).fetchall()
    finally:
        cur.close()
    return sorted(row[0] for row in rows)


def _hash_of(database, source):
    return _file_info(database, source)[2]


def test_duplicates_are_flagged_before_and_after_full_hashing(db, tmp_path):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    unique = tmp_path / "unique.bin"
    first.write_bytes(b"same payload" * 500)
    second.write_bytes(b"same payload" * 500)
    unique.write_bytes(b"other payload" * 500)
    sources = _register(db, [first, second, unique])

    flagger = DuplicateParser()
    flagger.db_name = "duplicate"
    hasher = FullHashParser()
    try:
        _run_parser(db, flagger, sources)
        assert _tagged_sources(db) == sorted(sources[:2])

        impacted = _run_parser(db, hasher, sources)
        assert all(len(_hash_of(db, source)) == FULL_HASH_LENGTH for source in sources)
        assert _hash_of(db, sources[0]) == _hash_of(db, sources[1])
        assert _tagged_sources(db) == sorted(sources[:2]), "tags must follow the file to its new hash"

        _run_parser(db, flagger, impacted)
        assert _tagged_sources(db) == sorted(sources[:2])
    finally:
        flagger.shutdown()


def test_flag_is_removed_when_full_hashing_splits_a_collision(db, tmp_path):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"payload one" * 500)
    second.write_bytes(b"payload two" * 500)
    sources = _register(db, [first, second])
    db.update_source_hashes([(sources[0], "collided")])
    db.update_source_hashes([(sources[1], "collided")])

    flagger = DuplicateParser()
    flagger.db_name = "duplicate"
    hasher = FullHashParser()
    try:
        _run_parser(db, flagger, sources)
        assert _tagged_sources(db) == sorted(sources)

        impacted = _run_parser(db, hasher, [sources[0]])
        assert _hash_of(db, sources[0]) != _hash_of(db, sources[1])
        assert sorted(impacted) == sorted(sources), "the untouched sibling must be re-triggered too"

        _run_parser(db, flagger, impacted)
        assert _tagged_sources(db) == []
    finally:
        flagger.shutdown()


def test_flag_is_removed_after_the_duplicate_sibling_is_deleted(db, tmp_path):
    first = tmp_path / "first.bin"
    second = tmp_path / "second.bin"
    first.write_bytes(b"same payload" * 500)
    second.write_bytes(b"same payload" * 500)
    sources = _register(db, [first, second])

    flagger = DuplicateParser()
    flagger.db_name = "duplicate"
    try:
        _run_parser(db, flagger, sources)
        assert _tagged_sources(db) == sorted(sources)

        impacted = db.delete_sources_by_paths([sources[1]])
        assert impacted == [sources[0]], "the surviving file must be re-evaluated"

        _run_parser(db, flagger, impacted)
        assert _tagged_sources(db) == []
    finally:
        flagger.shutdown()


def test_collector_tags_survive_full_hash_replacing_hash_in_flight(db, tmp_path):
    image = tmp_path / "image.bin"
    image.write_bytes(b"image payload" * 500)
    [source] = _register(db, [image])
    dispatched_hash = _file_info(db, source)[2]

    _run_parser(db, FullHashParser(), [source])
    assert _file_info(db, source)[2] != dispatched_hash

    data = parse_collector_batch([{"source": source, "status": True, "tags": {"tags": "1girl"}, "collector": "wd14"}])
    db.upsert_collection_results([], [], data["tag_entries"], data["collector_status"])

    cur = db.get_reader_cursor()
    try:
        row = cur.execute(
            "SELECT t.value FROM tags t JOIN sources s ON s.file_hash = t.file_hash WHERE s.source = ? AND t.key = 'wd14.tags'",
            (source,),
        ).fetchone()
        assert row == ("1girl",)
        assert cur.execute("SELECT COUNT(*) FROM tags WHERE file_hash = ?", (dispatched_hash,)).fetchone()[0] == 0
    finally:
        cur.close()

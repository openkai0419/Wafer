import sqlite3
import threading
import time

import pytest

from wafer.core.db.query import FileSearchEngine, _kv_sort_join, key_value_path_query, parse_keywords, standard_key_path_query
from wafer.core.db.file_db import FileDB
from wafer.core.common.paths import normalize_path
from wafer.core.common.virtual_paths import build_virtual_path


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "test.db")


@pytest.fixture
def populated_db(db_path):
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    sources, images, metas, tags = [], [], [], []
    for i in range(200):
        d = "C:/photos/vacation" if i < 100 else "C:/photos/work"
        path = f"{d}/img_{i:04d}.jpg"
        source = path
        fhash = f"hash_{i:04d}"
        mtime = float(1700000000 + i)
        fsize = 1000 + i
        sources.append((source, fhash, fsize, mtime))
        images.append((path, source, 1.5))
        metas.append((path, "dpi", f"{72 + (i % 4) * 24}", None))
        metas.append((path, "Comment", f"photo number {i}", None))
        if i % 3 == 0:
            metas.append((path, "Artist", f"photographer_{i % 5}", None))
        tags.append((source, "rating", f"{(i % 5) + 1}", float((i % 5) + 1)))
        if i % 2 == 0:
            tags.append((source, "category", "landscape" if i < 100 else "office", None))
    db.upsert_basic_sources(sources, images, metas)
    db.upsert_collection_results([], [], tags, [])
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


def np(p):
    return normalize_path(p)


SAMPLE_PATH = "C:/photos/vacation/img_0000.jpg"


class TestFileSearchEngineThreadLocal:
    def test_concurrent_threads_use_separate_connections(self, populated_db):
        engine = FileSearchEngine(populated_db)
        conns = []
        sources = []
        lock = threading.Lock()

        def worker():
            record = engine.get_file_record(SAMPLE_PATH)
            with lock:
                conns.append(id(engine.conn))
                sources.append(record["source"])

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert sources == [np(SAMPLE_PATH)] * 4
        assert len(set(conns)) == 4
        assert len(engine._connections) == 4
        engine.close()
        assert engine._connections == []

    def test_close_from_other_thread(self, populated_db):
        engine = FileSearchEngine(populated_db)
        t = threading.Thread(target=lambda: engine.get_file_record(SAMPLE_PATH))
        t.start()
        t.join()
        assert len(engine._connections) == 1
        engine.close()
        assert engine.conn is None


class TestEngineLookupMethods:
    def test_get_file_record(self, populated_db):
        engine = FileSearchEngine(populated_db)
        rec = engine.get_file_record(SAMPLE_PATH)
        assert rec.get("path") is not None
        assert rec.get("source") is not None

    def test_get_file_record_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        rec = engine.get_file_record("C:/nonexistent/file.jpg")
        assert rec == {}

    def test_get_all_metadata(self, populated_db):
        engine = FileSearchEngine(populated_db)
        source_rec, file_rec, file_hash, tags_with_lock, meta = engine.get_all_metadata_with_locks(SAMPLE_PATH)
        assert file_rec.get("path") is not None
        assert source_rec.get("file_hash") == file_hash
        assert file_hash is not None
        assert "rating" in tags_with_lock
        assert isinstance(tags_with_lock["rating"], tuple) and len(tags_with_lock["rating"]) == 2
        assert "dpi" in meta

    def test_child_metadata_resolves_source_hash_and_tags(self, db_path):
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        source = "C:/data/archive.zip"
        child = build_virtual_path(source, "folder/image.png")
        db.upsert_basic_sources(
            [(source, "hash_zip", 100, 1.0)],
            [(source, source, 1.0), (child, source, 1.5)],
            [(child, "name", "image.png", None)],
        )
        db.upsert_collection_results([], [], [(source, "rating", "5", 5.0)], [])
        db.close()
        engine = FileSearchEngine(db_path)
        source_rec, file_rec, file_hash, tags_with_lock, meta = engine.get_all_metadata_with_locks(child)
        assert file_rec["source"] == source
        assert file_hash == "hash_zip"
        assert source_rec["file_hash"] == "hash_zip"
        assert tags_with_lock["rating"] == ("5", False)
        assert meta["name"] == ("image.png", False)

    def test_get_all_metadata_empty(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        db.close()
        engine = FileSearchEngine(db_path)
        source_rec, file_rec, file_hash, tags_with_lock, meta = engine.get_all_metadata_with_locks("C:/any/file.jpg")
        assert source_rec == {}
        assert file_rec == {}
        assert file_hash is None
        assert tags_with_lock == {}
        assert meta == {}

    def test_get_collection_status_ok(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        db.insert_pending_collection([SAMPLE_PATH], ["exif"])
        db.upsert_collection_results([], [], [], [(SAMPLE_PATH, "exif", "ok", time.time())])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(SAMPLE_PATH)
        assert len(result) == 1
        assert result[0] == ("exif", "ok")

    def test_get_collection_status_fail(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        db.insert_pending_collection([SAMPLE_PATH], ["exif"])
        db.upsert_collection_results([], [], [], [(SAMPLE_PATH, "exif", "fail", time.time())])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(SAMPLE_PATH)
        assert len(result) == 1
        assert result[0] == ("exif", "fail")

    def test_get_collection_status_pending_hidden(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        db.insert_pending_collection([SAMPLE_PATH], ["exif"])
        db.close()
        engine = FileSearchEngine(populated_db)
        assert engine.get_collection_status(SAMPLE_PATH) == []

    def test_get_collection_status_stale_ok_hidden(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        db.insert_pending_collection([SAMPLE_PATH], ["exif"])
        db.upsert_collection_results([], [], [], [(SAMPLE_PATH, "exif", "ok", 1000.0)])
        db.close()
        engine = FileSearchEngine(populated_db)
        assert engine.get_collection_status(SAMPLE_PATH) == []

    def test_get_collection_status_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine.get_collection_status("C:/nonexistent/file.jpg") == []

    def test_nonexistent_db_path(self, tmp_path):
        engine = FileSearchEngine(str(tmp_path / "does_not_exist.db"))
        assert engine.get_file_record("a.jpg") == {}
        assert engine.conn is None

    def test_empty_db_missing_tables(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.close()
        engine = FileSearchEngine(db_path)
        assert engine.get_file_record("a.jpg") == {}
        assert engine.conn is None


class TestGetKvKeysByPrefix:
    @pytest.fixture
    def mark_db(self, tmp_path):
        db_path = str(tmp_path / "marks.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources, images, metas, tags = [], [], [], []
        for i in range(5):
            path = f"C:/m/img_{i}.jpg"
            fhash = f"h{i}"
            sources.append((path, fhash, 100, 1.0))
            images.append((path, path, 1.0))
            metas.append((path, "name", f"img_{i}.jpg", None))
        tags.append(("C:/m/img_0.jpg", "mark.red", "1", None))
        tags.append(("C:/m/img_0.jpg", "mark.blue", "1", None))
        tags.append(("C:/m/img_2.jpg", "mark.green", "1", None))
        tags.append(("C:/m/img_3.jpg", "rating", "5", 5.0))
        metas.append(("C:/m/img_1.jpg", "mark.red", "1", None))
        metas.append(("C:/m/img_4.jpg", "mark.blue", "1", None))
        db.upsert_basic_sources(sources, images, metas)
        db.upsert_collection_results([], [], tags, [])
        db.close()
        return db_path

    def test_all_marks_when_paths_none(self, mark_db):
        engine = FileSearchEngine(mark_db)
        result = engine.get_kv_keys_by_prefix("tag", "mark.")
        assert set(result.keys()) == {np("C:/m/img_0.jpg"), np("C:/m/img_2.jpg")}
        assert sorted(result[np("C:/m/img_0.jpg")]) == ["blue", "red"]
        assert result[np("C:/m/img_2.jpg")] == ["green"]

    def test_filtered_paths(self, mark_db):
        engine = FileSearchEngine(mark_db)
        result = engine.get_kv_keys_by_prefix("tag", "mark.", paths=["C:/m/img_2.jpg", "C:/m/img_3.jpg"])
        assert set(result.keys()) == {np("C:/m/img_2.jpg")}

    def test_no_matches(self, mark_db):
        engine = FileSearchEngine(mark_db)
        assert engine.get_kv_keys_by_prefix("tag", "nonexistent.") == {}

    def test_empty_prefix(self, mark_db):
        engine = FileSearchEngine(mark_db)
        assert engine.get_kv_keys_by_prefix("tag", "") == {}

    def test_meta_scope_marks(self, mark_db):
        engine = FileSearchEngine(mark_db)
        result = engine.get_kv_keys_by_prefix("meta_info", "mark.")
        assert set(result.keys()) == {np("C:/m/img_1.jpg"), np("C:/m/img_4.jpg")}
        assert result[np("C:/m/img_1.jpg")] == ["red"]

    def test_all_scope_marks_dedupes_path_suffix(self, mark_db):
        engine = FileSearchEngine(mark_db)
        result = engine.get_kv_keys_by_prefix("*", "mark.")
        assert set(result.keys()) == {
            np("C:/m/img_0.jpg"),
            np("C:/m/img_1.jpg"),
            np("C:/m/img_2.jpg"),
            np("C:/m/img_4.jpg"),
        }
        assert sorted(result[np("C:/m/img_0.jpg")]) == ["blue", "red"]
        assert result[np("C:/m/img_1.jpg")] == ["red"]


def test_fetch_runs_sql_with_params(populated_db):
    engine = FileSearchEngine(populated_db)
    assert engine._connect_if_needed()
    assert len(engine.fetch("SELECT path FROM files WHERE path LIKE ?", ["%vacation%"])) == 100
    assert engine.fetch("SELECT path FROM files WHERE path = ?", ["nonexistent"]) == []


class TestParseKeywords:
    def test_trim_by_default(self):
        assert parse_keywords(" a , b , -c ", ",") == (["a", "b"], ["c"])

    def test_drops_empty_and_dash_only_words(self):
        assert parse_keywords("a,,b,-,-c", ",") == (["a", "b"], ["c"])

    def test_exclude_only(self):
        assert parse_keywords("-a,-b", ",") == ([], ["a", "b"])

    def test_none_is_empty(self):
        assert parse_keywords(None, ",") == ([], [])

    def test_keep_spaces(self):
        assert parse_keywords(" hair, long hair ", ",", trim=False) == ([" hair", " long hair "], [])

    def test_keep_spaces_drops_blank_words(self):
        assert parse_keywords("a, ,  ", ",", trim=False) == (["a"], [])

    def test_keep_spaces_drops_dash_blank(self):
        assert parse_keywords("a,- ,-  ", ",", trim=False) == (["a"], [])

    def test_keep_spaces_dash_only_at_head(self):
        assert parse_keywords("a, -b,-c ", ",", trim=False) == (["a", " -b"], ["c "])

    def test_trim_without_separator(self):
        assert parse_keywords("  cat dog ") == (["cat dog"], [])

    def test_sequence_used_as_is(self):
        assert parse_keywords((" a", " ", "-b"), ",") == ([" a"], ["b"])


class TestKvSortJoinValidation:
    @pytest.mark.parametrize("bad_key", ["x; --", ""])
    def test_rejects_invalid_identifier(self, bad_key):
        with pytest.raises(ValueError, match="Invalid META_KEY"):
            _kv_sort_join(bad_key)

    def test_no_conn_returns_full_join(self):
        join, select, order, params = _kv_sort_join("name")
        assert "_tg" in join
        assert "_mi" in join
        assert "COALESCE" in select
        assert params == ["name", "name"]

    def test_conn_key_absent_in_tags_skips_tags_join(self, populated_db):
        conn = sqlite3.connect(f"file:{populated_db}?mode=ro", uri=True)
        try:
            join, select, order, params = _kv_sort_join("modified", conn)
            assert "_tg" not in join
            assert "_mi" in join
            assert "COALESCE" not in select
            assert params == ["modified"]
        finally:
            conn.close()

    def test_conn_key_present_in_tags_uses_full_join(self, populated_db):
        conn = sqlite3.connect(f"file:{populated_db}?mode=ro", uri=True)
        try:
            join, select, order, params = _kv_sort_join("rating", conn)
            assert "_tg" in join
            assert "_mi" in join
            assert "COALESCE" in select
            assert params == ["rating", "rating"]
        finally:
            conn.close()


def _value_equals(value):
    return lambda column: ([f"{column} = ?"], [value])


def _paths(engine, sql, params):
    assert engine._connect_if_needed()
    return sorted(row[0] for row in engine.fetch(sql, params))


class TestKeyValuePathQuery:
    def test_keys_exclude_keys_and_value_conditions_are_anded(self):
        sql, params = key_value_path_query("meta_info", _value_equals("v"), keys=["a", "b"], exclude_keys=["c"])
        assert sql == 'SELECT mi.path AS path FROM meta_info AS mi WHERE mi."key" IN (?,?) AND mi."key" NOT IN (?) AND mi."value" = ?'
        assert params == ["a", "b", "c", "v"]

    def test_no_conditions_has_no_where(self):
        assert key_value_path_query("meta_info", lambda column: ([], [])) == ("SELECT mi.path AS path FROM meta_info AS mi", [])

    def test_tags_are_matched_through_sources(self, populated_db):
        sql, params = key_value_path_query("tags", _value_equals("landscape"), keys=["category"])
        paths = _paths(FileSearchEngine(populated_db), sql, params)
        assert len(paths) == 50
        assert all("/vacation/" in p for p in paths)


class TestStandardKeyPathQuery:
    def test_unknown_key_has_no_query(self):
        assert standard_key_path_query("Comment", _value_equals("x")) == (None, [])

    @pytest.mark.parametrize(("key", "value", "expected"), [("path", SAMPLE_PATH, [SAMPLE_PATH]), ("size", "1100", ["C:/photos/work/img_0100.jpg"])])
    def test_files_and_sources_columns(self, populated_db, key, value, expected):
        sql, params = standard_key_path_query(key, _value_equals(value))
        assert _paths(FileSearchEngine(populated_db), sql, params) == expected

import sqlite3

from wafer.core.db.query import SearchQuery, FileSearchEngine
from wafer.core.db.file_db import FileDB, _TABLES, _VIEWS, _INDEXES_SQL
from wafer.core.db.db_utils import apply_write_pragmas


def _setup_db(tmp_path, files=None, meta=None, tags=None):
    db_path = tmp_path / "test.db"
    db = FileDB(db_path)
    db.start()
    db.initialize_database()

    cur = db.conn.cursor()
    for path, source, fhash, size, modified, aspect in files or []:
        cur.execute("INSERT OR IGNORE INTO hash_index (file_hash) VALUES (?)", (fhash,))
        cur.execute(
            "INSERT OR REPLACE INTO sources (source, file_hash, size, modified) VALUES (?,?,?,?)",
            (source, fhash, size, modified),
        )
        cur.execute(
            "INSERT OR REPLACE INTO files (path, source, aspect_ratio) VALUES (?,?,?)",
            (path, source, aspect),
        )
    for path, key, value in meta or []:
        cur.execute(
            "INSERT OR REPLACE INTO meta_info (path, key, value, value_num) VALUES (?,?,?,NULL)",
            (path, key, value),
        )
    for fhash, key, value in tags or []:
        cur.execute(
            "INSERT OR REPLACE INTO tags (file_hash, key, value, value_num) VALUES (?,?,?,NULL)",
            (fhash, key, value),
        )
    db.conn.commit()
    db.close()
    return str(db_path)


class TestSearchQueryNormalize:
    def test_string_keys_to_list(self):
        q = SearchQuery(keys="path")
        keys, inc, exc = q.normalize_inputs()
        assert keys == ["path"]

    def test_tuple_keys(self):
        q = SearchQuery(keys=("path", "name"))
        keys, inc, exc = q.normalize_inputs()
        assert keys == ["path", "name"]

    def test_exclude_keywords(self):
        q = SearchQuery(keywords=("sunset", "-blur"))
        _, inc, exc = q.normalize_inputs()
        assert "sunset" in inc
        assert "blur" in exc

    def test_keyword_separator(self):
        q = SearchQuery(keywords="a,b,c", keyword_separator=",")
        _, inc, exc = q.normalize_inputs()
        assert inc == ["a", "b", "c"]

    def test_empty_query(self):
        q = SearchQuery()
        keys, inc, exc = q.normalize_inputs()
        assert keys == []
        assert inc == []
        assert exc == []


class TestFileSearchEngineSmoke:
    def test_search_by_path_keyword(self, tmp_path):
        db_path = _setup_db(
            tmp_path,
            files=[
                ("photos/alpha.jpg", "photos/alpha.jpg", "h1", 1000, 1.0, 1.5),
                ("photos/beta.png", "photos/beta.png", "h2", 2000, 2.0, 1.0),
            ],
            meta=[
                ("photos/alpha.jpg", "path", "photos/alpha.jpg"),
                ("photos/beta.png", "path", "photos/beta.png"),
            ],
        )
        engine = FileSearchEngine(db_path)
        paths, sources, aspects = engine.search(SearchQuery(keys="path", keywords="alpha"))
        assert len(paths) == 1
        assert "alpha" in paths[0]

    def test_search_all_no_keys(self, tmp_path):
        db_path = _setup_db(
            tmp_path,
            files=[
                ("a.jpg", "a.jpg", "h1", 100, 1.0, 1.0),
                ("b.jpg", "b.jpg", "h2", 200, 2.0, 2.0),
            ],
            meta=[
                ("a.jpg", "path", "a.jpg"),
                ("b.jpg", "path", "b.jpg"),
            ],
        )
        engine = FileSearchEngine(db_path)
        paths, _, _ = engine.search(SearchQuery(keys="path"))
        assert len(paths) == 2

    def test_search_returns_aspect_ratios(self, tmp_path):
        db_path = _setup_db(
            tmp_path,
            files=[("x.jpg", "x.jpg", "hx", 500, 1.0, 2.5)],
            meta=[("x.jpg", "path", "x.jpg")],
        )
        engine = FileSearchEngine(db_path)
        paths, _, aspects = engine.search(SearchQuery(keys="path"))
        assert len(aspects) == 1
        assert aspects[0] == 2.5

    def test_search_empty_db(self, tmp_path):
        db_path = _setup_db(tmp_path)
        engine = FileSearchEngine(db_path)
        paths, sources, aspects = engine.search(SearchQuery(keys="path", keywords="anything"))
        assert paths == []

    def test_search_with_exclude(self, tmp_path):
        db_path = _setup_db(
            tmp_path,
            files=[
                ("photos/cat.jpg", "photos/cat.jpg", "h1", 100, 1.0, 1.0),
                ("photos/dog.jpg", "photos/dog.jpg", "h2", 200, 2.0, 1.0),
            ],
            meta=[
                ("photos/cat.jpg", "exif.Comment", "cute cat"),
                ("photos/dog.jpg", "exif.Comment", "big dog"),
            ],
        )
        engine = FileSearchEngine(db_path)
        paths, _, _ = engine.search(SearchQuery(keys="exif.Comment", keywords=("cute", "-dog")))
        assert len(paths) == 1
        assert "cat" in paths[0]

    def test_search_nonexistent_db(self, tmp_path):
        engine = FileSearchEngine(str(tmp_path / "nonexistent.db"))
        paths, sources, aspects = engine.search(SearchQuery(keys="path", keywords="x"))
        assert paths == []

    def test_glob_query_mode(self, tmp_path):
        db_path = _setup_db(
            tmp_path,
            files=[
                ("photos/sunset.jpg", "photos/sunset.jpg", "h1", 100, 1.0, 1.0),
                ("photos/sunrise.jpg", "photos/sunrise.jpg", "h2", 200, 2.0, 1.0),
            ],
            meta=[
                ("photos/sunset.jpg", "path", "photos/sunset.jpg"),
                ("photos/sunrise.jpg", "path", "photos/sunrise.jpg"),
            ],
        )
        engine = FileSearchEngine(db_path)
        paths, _, _ = engine.search(SearchQuery(keys="path", keywords="sun*", query_mode="GLOB"))
        assert len(paths) == 2

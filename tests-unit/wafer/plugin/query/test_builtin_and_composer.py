import pytest
import sqlite3
from pathlib import Path

from wafer.core.db.file_db import FileDB
from wafer.core.db.query import FileSearchEngine
from wafer.plugin.query.composer import SearchComposer
from wafer.plugin.query.base import BaseFilterPlugin
from wafer.builtins.filters import TextFilter, DirectoryFilter, ContainedFilesFilter, SourceChildrenFilter
from wafer.builtins.sorts import (
    NaturalPathSort,
    NaturalNameSort,
    ModifiedSort,
    CreatedSort,
    SizeSort,
    CollectedSort,
    RandomSort,
)
from wafer.utils.paths import normalize_path
from wafer.utils.virtual_paths import build_virtual_path


def np(p):
    return normalize_path(p)


@pytest.fixture
def populated_db(tmp_path):
    db_path = str(tmp_path / "test.db")
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    sources, images, metas, tags = [], [], [], []
    for i in range(200):
        d = "C:/photos/vacation" if i < 100 else "C:/photos/work"
        path = f"{d}/img_{i:04d}.jpg"
        source = path
        fhash = f"hash_{i:04d}"
        sources.append((source, fhash, 1000 + i, float(1700000000 + i)))
        images.append((path, source, 1.5))
        metas.append((path, "dpi", f"{72 + (i % 4) * 24}", None))
        metas.append((path, "Comment", f"photo number {i}", None))
        if i % 3 == 0:
            metas.append((path, "Artist", f"photographer_{i % 5}", None))
        tags.append((fhash, "rating", f"{(i % 5) + 1}", float((i % 5) + 1)))
        if i % 2 == 0:
            tags.append((fhash, "category", "landscape" if i < 100 else "office", None))
    db.upsert_batches(sources, images, metas, tags)
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


@pytest.fixture
def special_db(tmp_path):
    db_path = str(tmp_path / "special.db")
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    sources, images, metas, tags = [], [], [], []
    special_names = [
        ("C:/data/100%_done.jpg", "100%_done.jpg", "h1", "val with %percent"),
        ("C:/data/under_score.jpg", "under_score.jpg", "h2", "has_underscore"),
        ("C:/data/back\\slash.jpg", "back\\slash.jpg", "h3", "back\\slash"),
        ("C:/data/star*glob.jpg", "star*glob.jpg", "h4", "star*val"),
        ("C:/data/question?.jpg", "question?.jpg", "h5", "question?val"),
        ("C:/data/normal.jpg", "normal.jpg", "h6", "normal value"),
        ("C:/data/UPPER.JPG", "UPPER.JPG", "h7", "UPPER VALUE"),
        ("C:/data/sub_dir/nested.jpg", "nested.jpg", "h8", "nested"),
    ]
    for path, name, fhash, comment in special_names:
        sources.append((path, fhash, 100, 1.0))
        images.append((path, path, 1.5))
        metas.append((path, "Comment", comment, None))
        tags.append((fhash, "rating", "3", 3.0))
    db.upsert_batches(sources, images, metas, tags)
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


@pytest.fixture
def contained_db(tmp_path):
    db_path = str(tmp_path / "contained.db")
    db = FileDB(db_path)
    db.start()
    db.initialize_database()
    archive = "C:/archives/temp.zip"
    child_a = build_virtual_path(archive, "a.png")
    child_b = build_virtual_path(archive, "nested/b.png")
    plain = "C:/photos/plain.png"
    db.upsert_batches(
        [
            (archive, "hash_zip", 1000, 1.0),
            (plain, "hash_plain", 2000, 2.0),
        ],
        [
            (archive, archive, "temp.zip", 1.0, None),
            (child_a, archive, "a.png", 1.0, "zip"),
            (child_b, archive, "b.png", 1.0, "zip"),
            (plain, plain, "plain.png", 1.0, None),
        ],
        [],
        [],
    )
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path, archive, child_a, child_b, plain


@pytest.fixture
def engine(populated_db):
    return FileSearchEngine(populated_db)


@pytest.fixture
def special_engine(special_db):
    return FileSearchEngine(special_db)


@pytest.fixture
def composer():
    return SearchComposer()


class TestTextFilterBuildPathQuery:
    def test_filepath_key(self, engine):
        params = {"keys": ["path"], "keywords": "img_0001"}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "files" in sql

    def test_meta_key(self, engine):
        params = {"keys": ["dpi"], "keywords": "72"}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "meta_info" in sql

    def test_no_keys_require_true_returns_empty_for_none_keys(self):
        params = {"keys": None, "require_keys": True}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "WHERE 0" in sql

    def test_no_keys_require_true_returns_empty_for_empty_list(self):
        params = {"keys": [], "require_keys": True}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "WHERE 0" in sql

    def test_no_keys_require_false(self, engine):
        params = {"keys": [], "require_keys": False, "keywords": "photo"}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "files" in sql
        assert "meta_info" in sql
        assert "tags" in sql

    def test_exclude_keywords(self, engine):
        params = {"keys": ["Comment"], "keywords": "photo,-number 5", "keyword_separator": ","}
        sql, bind = TextFilter.build_path_query(params, np)
        assert sql is not None
        assert "NOT IN" in sql

    def test_glob_mode(self, engine):
        params = {"keys": ["path"], "keywords": "vacation", "query_mode": "GLOB"}
        sql, bind = TextFilter.build_path_query(params, np)
        assert "GLOB" in sql

    def test_and_keyword_mode(self, engine):
        params = {"keys": ["Comment"], "keywords": "photo,number", "keyword_separator": ",", "keyword_mode": "AND"}
        sql, bind = TextFilter.build_path_query(params, np)
        assert " AND " in sql


class TestTextFilterExecution:
    def test_search_filepath(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "vacation"}, None)]
        paths, sources, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100
        assert all("vacation" in p for p in paths)

    def test_search_meta(self, engine, composer):
        entries = [(TextFilter, {"keys": ["dpi"], "keywords": "72"}, None)]
        paths, sources, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) > 0
        assert len(paths) == 50

    def test_search_tags(self, engine, composer):
        entries = [(TextFilter, {"keys": ["rating"], "keywords": "1"}, None)]
        paths, sources, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 40

    def test_search_file_hash_uses_sources(self, engine, composer):
        entries = [(TextFilter, {"keys": ["file_hash"], "keywords": "hash_0001"}, None)]
        paths, sources, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert paths == ["C:/photos/vacation/img_0001.jpg"]

    def test_search_with_exclude(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "img,-work", "keyword_separator": ","}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert all("work" not in p for p in paths)
        assert len(paths) == 100

    def test_empty_keywords_returns_all(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "", "keyword_separator": ","}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 200

    def test_no_match(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "nonexistent_xyz"}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 0


class TestDirectoryFilterBuildPathQuery:
    def test_no_directories(self):
        params = {}
        sql, bind = DirectoryFilter.build_path_query(params, np)
        assert sql is None

    def test_single_directory(self):
        params = {"directories": ["C:/photos/vacation"]}
        sql, bind = DirectoryFilter.build_path_query(params, np)
        assert sql is not None
        assert "LIKE" in sql
        assert len(bind) == 1

    def test_multiple_directories(self):
        params = {"directories": ["C:/photos/vacation", "C:/photos/work"]}
        sql, bind = DirectoryFilter.build_path_query(params, np)
        assert sql is not None
        assert " OR " in sql
        assert len(bind) == 2

    def test_no_subfolders(self):
        params = {"directories": ["C:/data"], "include_subfolders": False}
        sql, bind = DirectoryFilter.build_path_query(params, np)
        assert sql is not None
        assert "NOT LIKE" in sql
        assert len(bind) == 2


class TestContainedFilesFilterBuildPathQuery:
    def test_include_true_noops(self):
        sql, bind = ContainedFilesFilter.build_path_query({"include": True}, np)
        assert sql is None
        assert bind == []

    def test_include_false_uses_source_extension_index(self):
        sql, bind = ContainedFilesFilter.build_path_query({"include": False}, np)
        assert sql == "SELECT path FROM files WHERE source_extension IS NULL"
        assert bind == []


class TestSourceChildrenFilterBuildPathQuery:
    def test_source_children_query_uses_source_and_prefix(self):
        sql, bind = SourceChildrenFilter.build_path_query({"source": "C:/archives/temp.zip"}, np)
        assert "source = ?" in sql
        assert "path LIKE ?" in sql
        assert bind == ["C:/archives/temp.zip", "C:/archives/temp.zip::%"]

    def test_source_children_empty_source_noops(self):
        sql, bind = SourceChildrenFilter.build_path_query({"source": ""}, np)
        assert sql is None
        assert bind == []


class TestFileSearchEngineSourceChildren:
    def test_has_source_children_detects_virtual_members(self, contained_db):
        db_path, archive, _child_a, _child_b, plain = contained_db
        engine = FileSearchEngine(db_path)
        try:
            assert engine.has_source_children(archive) is True
            assert engine.has_source_children(plain) is False
        finally:
            engine.close()

    def test_has_source_children_uses_virtual_path_prefix(self, tmp_path):
        db_path = str(tmp_path / "prefix_children.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        archive = "C:/archives/legacy.zip"
        child = build_virtual_path(archive, "legacy.png")
        db.upsert_batches(
            [(archive, "hash_zip", 1000, 1.0)],
            [
                (archive, archive, "legacy.zip", 1.0, None),
                (child, archive, "legacy.png", 1.0, None),
            ],
            [],
            [],
        )
        db.close()

        engine = FileSearchEngine(db_path)
        try:
            assert engine.has_source_children(archive) is True
        finally:
            engine.close()


class TestDirectoryFilterExecution:
    def test_filter_vacation(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"]}, None),
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100
        assert all("vacation" in p for p in paths)

    def test_filter_work(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"]}, None),
            (DirectoryFilter, {"directories": ["C:/photos/work"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100
        assert all("work" in p for p in paths)

    def test_filter_both(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"]}, None),
            (DirectoryFilter, {"directories": ["C:/photos/vacation", "C:/photos/work"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 200

    def test_no_subfolders(self, special_engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "require_keys": True}, None),
            (DirectoryFilter, {"directories": ["C:/data"], "include_subfolders": False}, None),
        ]
        paths, _, _ = composer.execute(special_engine, entries, NaturalNameSort, True)
        assert all("sub_dir" not in p for p in paths)
        assert len(paths) == 7

    def test_directory_only(self, engine, composer):
        entries = [
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100


class TestContainedFilesFilterExecution:
    def test_contained_files_can_be_excluded(self, contained_db, composer):
        db_path, archive, child_a, child_b, plain = contained_db
        engine = FileSearchEngine(db_path)
        paths, _, _ = composer.execute(engine, [(ContainedFilesFilter, {"include": False}, None)], NaturalPathSort, True)
        assert set(paths) == {archive, plain}
        assert child_a not in paths
        assert child_b not in paths

    def test_source_children_lists_archive_members_only(self, contained_db, composer):
        db_path, archive, child_a, child_b, plain = contained_db
        engine = FileSearchEngine(db_path)
        paths, sources, _ = composer.execute(engine, [(SourceChildrenFilter, {"source": archive}, None)], NaturalPathSort, True)
        assert paths == [child_a, child_b]
        assert sources == [archive, archive]
        assert plain not in paths


class TestComposerCombineLogic:
    def test_single_filter(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "img_0001"}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 1

    def test_and_combine(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["Comment"], "keywords": "photo number 0"}, "AND"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) > 0
        assert all("vacation" in p for p in paths)

    def test_or_combine(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_0002"}, "OR"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 2

    def test_and_or_precedence(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["rating"], "keywords": "1"}, "AND"),
            (TextFilter, {"keys": ["path"], "keywords": "img_0101"}, "OR"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        vacation_rating1 = [p for p in paths if "vacation" in p]
        work_specific = [p for p in paths if "img_0101" in p]
        assert len(vacation_rating1) > 0 or len(work_specific) > 0

    def test_not_subtracts_filter(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, "NOT"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 9
        assert all("img_000" in p for p in paths)
        assert all("img_0001" not in p for p in paths)

    def test_not_binds_weaker_than_or(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, "NOT"),
            (TextFilter, {"keys": ["path"], "keywords": "img_0100"}, "OR"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 9
        assert all("img_0100" not in p for p in paths)

    def test_not_is_right_associative(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, "NOT"),
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, "NOT"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 91
        assert any("img_0001" in p for p in paths)
        assert all("img_0000" not in p for p in paths)

    def test_no_filters(self, engine, composer):
        entries = []
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 200

    def test_empty_keys_returns_nothing(self, engine, composer):
        entries = [(TextFilter, {"keys": []}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 0

    def test_none_keys_returns_nothing(self, engine, composer):
        entries = [(TextFilter, {"keys": None}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 0

    def test_filter_returns_none_skipped(self, engine, composer):
        entries = [
            (DirectoryFilter, {}, None),
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100


class TestComposerSorting:
    def test_natural_name_sort_asc(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        names = [p.rsplit("/", 1)[-1] for p in paths]
        assert names == sorted(names, key=lambda s: [int(c) if c.isdigit() else c.casefold() for c in __import__("re").compile(r"(\d+)").split(s)])

    def test_natural_name_sort_desc(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, False)
        names = [p.rsplit("/", 1)[-1] for p in paths]
        assert names == sorted(names, key=lambda s: [int(c) if c.isdigit() else c.casefold() for c in __import__("re").compile(r"(\d+)").split(s)], reverse=True)

    def test_natural_path_sort(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalPathSort, True)
        assert len(paths) == 200
        assert paths[0] < paths[-1]

    def test_modified_sort_sql(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, ModifiedSort, True)
        assert len(paths) == 200

    def test_created_sort_sql(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, CreatedSort, False)
        assert len(paths) == 200

    def test_size_sort(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, SizeSort, True)
        assert len(paths) == 200

    def test_collected_sort(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, CollectedSort, True)
        assert len(paths) == 200

    def test_random_sort(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths1, _, _ = composer.execute(engine, entries, RandomSort, True)
        paths2, _, _ = composer.execute(engine, entries, RandomSort, True)
        assert len(paths1) == 200
        assert set(paths1) == set(paths2)


class TestComposerReturnFormat:
    def test_returns_three_lists(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        result = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(result) == 3
        paths, sources, aspects = result
        assert len(paths) == len(sources) == len(aspects) == 200

    def test_aspects_default_to_1(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        _, _, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert all(isinstance(a, float) for a in aspects)

    def test_db_not_found(self, composer):
        engine = FileSearchEngine("/nonexistent/path.db")
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, sources, aspects = composer.execute(engine, entries, NaturalNameSort, True)
        assert paths == []
        assert sources == []
        assert aspects == []


class TestSpecialCharacterSearch:
    def test_percent_in_path(self, special_engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "100%", "query_mode": "LIKE"}, None)]
        paths, _, _ = composer.execute(special_engine, entries, NaturalNameSort, True)
        assert len(paths) == 1
        assert "100%" in paths[0]

    def test_underscore_in_path(self, special_engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "under_score", "query_mode": "LIKE"}, None)]
        paths, _, _ = composer.execute(special_engine, entries, NaturalNameSort, True)
        assert len(paths) == 1

    def test_glob_star(self, special_engine, composer):
        entries = [(TextFilter, {"keys": ["path"], "keywords": "normal", "query_mode": "GLOB"}, None)]
        paths, _, _ = composer.execute(special_engine, entries, NaturalNameSort, True)
        assert len(paths) == 1


class TestPostFilter:
    def test_custom_post_filter(self, engine, composer):
        class EvenIndexFilter(BaseFilterPlugin):
            NAME = "even_idx"

            @classmethod
            def build_path_query(cls, params, normalize_path):
                return None, []

            @classmethod
            def post_filter(cls, params, rows):
                return [r for i, r in enumerate(rows) if i % 2 == 0]

        entries = [
            (TextFilter, {"keys": ["path"]}, None),
            (EvenIndexFilter, {}, "AND"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 100

    def test_post_filter_not_called_for_base(self, engine, composer):
        entries = [(TextFilter, {"keys": ["path"]}, None)]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 200


class TestComposerCombineStatic:
    def test_empty_produces_all_files(self):
        sql, params = SearchComposer._combine([])
        assert sql == "SELECT path FROM files"
        assert params == []

    def test_single_entry(self):
        sql, params = SearchComposer._combine([("SELECT path FROM files WHERE path LIKE ?", ["%test%"], None)])
        assert "LIKE" in sql
        assert params == ["%test%"]

    def test_two_and(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a", [], None),
                ("SELECT path FROM b", [], "AND"),
            ]
        )
        assert "INTERSECT" in sql

    def test_two_or(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a", [], None),
                ("SELECT path FROM b", [], "OR"),
            ]
        )
        assert "UNION" in sql
        assert "INTERSECT" not in sql

    def test_and_or_groups(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a", ["p1"], None),
                ("SELECT path FROM b", ["p2"], "AND"),
                ("SELECT path FROM c", ["p3"], "OR"),
            ]
        )
        assert "INTERSECT" in sql
        assert "UNION" in sql
        assert params == ["p1", "p2", "p3"]

    def test_three_and(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a", [], None),
                ("SELECT path FROM b", [], "AND"),
                ("SELECT path FROM c", [], "AND"),
            ]
        )
        assert sql.count("INTERSECT") == 2
        assert "UNION" not in sql

    def test_not_uses_except(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a WHERE x = ?", ["p1"], None),
                ("SELECT path FROM b WHERE y = ?", ["p2"], "NOT"),
            ]
        )
        assert "EXCEPT" in sql
        assert params == ["p1", "p2"]

    def test_not_or_group_is_right_operand(self):
        sql, params = SearchComposer._combine(
            [
                ("SELECT path FROM a WHERE x = ?", ["p1"], None),
                ("SELECT path FROM b WHERE y = ?", ["p2"], "NOT"),
                ("SELECT path FROM c WHERE z = ?", ["p3"], "OR"),
            ]
        )
        assert "EXCEPT" in sql
        assert "UNION" in sql
        assert params == ["p1", "p2", "p3"]


class TestComposerListAllKeys:
    def test_all_keys_returned(self, engine, composer):
        entries = []
        keys = composer.list_all_keys(engine, entries)
        key_names = [k for k, _ in keys]
        assert "Comment" in key_names
        assert "dpi" in key_names
        assert "rating" in key_names

    def test_filepath_included(self, engine, composer):
        keys = composer.list_all_keys(engine, [])
        key_names = [k for k, _ in keys]
        assert "path" in key_names

    def test_filepath_count_equals_file_count(self, engine, composer):
        keys = composer.list_all_keys(engine, [], sort_by_freq=True)
        fp_count = next(f for k, f in keys if k == "path")
        assert fp_count == 200

    def test_file_hash_count_equals_file_count(self, engine, composer):
        keys = composer.list_all_keys(engine, [], sort_by_freq=True)
        file_hash_count = next(f for k, f in keys if k == "file_hash")
        assert file_hash_count == 200

    def test_filepath_count_filtered_by_directory(self, engine, composer):
        entries = [
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        keys = composer.list_all_keys(engine, entries, sort_by_freq=True)
        fp_count = next(f for k, f in keys if k == "path")
        assert fp_count == 100

    def test_sort_by_freq(self, engine, composer):
        entries = []
        keys = composer.list_all_keys(engine, entries, sort_by_freq=True)
        freqs = [f for _, f in keys]
        assert freqs == sorted(freqs, reverse=True)

    def test_sort_by_name(self, engine, composer):
        entries = []
        keys = composer.list_all_keys(engine, entries, sort_by_freq=False)
        key_names = [k for k, _ in keys]
        assert key_names == sorted(key_names)

    def test_filtered_by_directory(self, engine, composer):
        entries = [
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        keys = composer.list_all_keys(engine, entries)
        key_names = [k for k, _ in keys]
        assert "Comment" in key_names
        assert "rating" in key_names

    def test_filtered_directory_counts(self, engine, composer):
        all_keys = composer.list_all_keys(engine, [], sort_by_freq=True)
        vac_keys = composer.list_all_keys(
            engine,
            [(DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None)],
            sort_by_freq=True,
        )
        all_comment = next(f for k, f in all_keys if k == "Comment")
        vac_comment = next(f for k, f in vac_keys if k == "Comment")
        assert vac_comment < all_comment

    def test_not_filter_restricts_key_counts(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, "NOT"),
        ]
        keys = composer.list_all_keys(engine, entries, sort_by_freq=True)
        fp_count = next(f for k, f in keys if k == "path")
        assert fp_count == 90

    def test_db_not_found(self, composer):
        engine = FileSearchEngine("/nonexistent/path.db")
        keys = composer.list_all_keys(engine, [])
        assert keys == []

    def test_artist_key_present(self, engine, composer):
        keys = composer.list_all_keys(engine, [])
        key_names = [k for k, _ in keys]
        assert "Artist" in key_names

    def test_category_key_from_tags(self, engine, composer):
        keys = composer.list_all_keys(engine, [])
        key_names = [k for k, _ in keys]
        assert "category" in key_names


class TestDirectoryFilterGlobalScope:
    def test_directory_scope_is_global(self):
        assert DirectoryFilter.QUERY_SCOPE == "global"

    def test_text_scope_is_row(self):
        assert TextFilter.QUERY_SCOPE == "row"

    def test_base_scope_default(self):
        assert BaseFilterPlugin.QUERY_SCOPE == "row"

    def test_and_works_without_directory(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["Comment"], "keywords": "photo number 0"}, "AND"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) > 0
        assert all("vacation" in p for p in paths)

    def test_or_works_without_directory(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_0101"}, "OR"),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert len(paths) == 2
        assert any("img_0001" in p for p in paths)
        assert any("img_0101" in p for p in paths)

    def test_and_consistent_with_and_without_directory(self, engine, composer):
        entries_no_dir = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["rating"], "keywords": "1"}, "AND"),
        ]
        entries_with_all_dir = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (TextFilter, {"keys": ["rating"], "keywords": "1"}, "AND"),
            (DirectoryFilter, {"directories": ["C:/photos/vacation", "C:/photos/work"]}, None),
        ]
        paths_no_dir, _, _ = composer.execute(engine, entries_no_dir, NaturalNameSort, True)
        paths_all_dir, _, _ = composer.execute(engine, entries_with_all_dir, NaturalNameSort, True)
        assert set(paths_no_dir) == set(paths_all_dir)

    def test_directory_always_intersects_with_or_groups(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_0001"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_0101"}, "OR"),
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert all("vacation" in p for p in paths)
        assert len(paths) == 1
        assert "img_0001" in paths[0]

    def test_directory_intersects_entire_union(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_010"}, "OR"),
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        paths, _, _ = composer.execute(engine, entries, NaturalNameSort, True)
        assert all("vacation" in p for p in paths)
        expected = {p for p in paths if "img_000" in p or "img_010" in p}
        assert set(paths) == expected

    def test_apply_global_static(self):
        combined = "SELECT path FROM a UNION SELECT path FROM b"
        gsql = "SELECT path FROM c"
        result_sql, result_params = SearchComposer._apply_global(combined, [], [(gsql, [])])
        assert "INTERSECT" in result_sql
        assert "SELECT path FROM (" in result_sql
        assert "_rw" in result_sql

    def test_apply_global_preserves_params(self):
        combined = "SELECT path FROM a WHERE x = ?"
        gsql = "SELECT path FROM c WHERE y = ?"
        result_sql, result_params = SearchComposer._apply_global(combined, ["p1"], [(gsql, ["p2"])])
        assert result_params == ["p1", "p2"]

    def test_apply_global_empty_returns_unchanged(self):
        combined = "SELECT path FROM a"
        result_sql, result_params = SearchComposer._apply_global(combined, ["p1"], [])
        assert result_sql == combined
        assert result_params == ["p1"]

    def test_list_all_keys_global_scope(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "vacation"}, None),
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        keys = composer.list_all_keys(engine, entries, sort_by_freq=True)
        fp_count = next(f for k, f in keys if k == "path")
        assert fp_count == 100

    def test_list_all_keys_directory_restricts_or_groups(self, engine, composer):
        entries = [
            (TextFilter, {"keys": ["path"], "keywords": "img_000"}, None),
            (TextFilter, {"keys": ["path"], "keywords": "img_010"}, "OR"),
            (DirectoryFilter, {"directories": ["C:/photos/vacation"]}, None),
        ]
        keys = composer.list_all_keys(engine, entries, sort_by_freq=True)
        fp_count = next(f for k, f in keys if k == "path")
        assert fp_count <= 100

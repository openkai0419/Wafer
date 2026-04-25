import os
import sqlite3
import time
import pytest
from pathlib import Path
from wafer.core.db.query import SearchQuery, FileSearchEngine, _kv_sort_join
from wafer.utils.formatting import natural_key
from wafer.core.db.file_db import FileDB
from wafer.utils.paths import normalize_path


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
        metas.append((path, "path", path, None))
        metas.append((path, "name", f"img_{i:04d}.jpg", None))
        metas.append((path, "dpi", f"{72 + (i % 4) * 24}", None))
        metas.append((path, "Comment", f"photo number {i}", None))
        metas.append((path, "size", str(fsize), float(fsize)))
        metas.append((path, "modified", str(mtime), mtime))
        metas.append((path, "created", str(mtime), mtime))
        metas.append((path, "collected", str(mtime), mtime))
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
def special_char_db(tmp_path):
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
        metas.append((path, "path", path, None))
        metas.append((path, "name", name, None))
        metas.append((path, "Comment", comment, None))
        tags.append((fhash, "rating", "3", 3.0))
    db.upsert_batches(sources, images, metas, tags)
    db.conn.execute("ANALYZE")
    db.conn.commit()
    db.close()
    return db_path


def np(p):
    return normalize_path(p)


class TestSearchQuerySubquery:
    def test_keys_meta_info(self, populated_db):
        q = SearchQuery(keys=["dpi"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "meta_info" in sql

    def test_keys_filepath(self, populated_db):
        q = SearchQuery(keys=["path"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "meta_info" in sql

    def test_no_keys_require_keys_true(self):
        q = SearchQuery(keys=None, require_keys=True)
        sql, params = q._make_subquery(np)
        assert sql is None

    def test_no_keys_require_keys_false(self, populated_db):
        q = SearchQuery(keys=None, require_keys=False)
        sql, params = q._make_subquery(np, require_keys_override=False)
        assert sql is not None
        assert "files" in sql
        assert "meta_info" in sql
        assert "tags" in sql

    def test_keyword_include(self, populated_db):
        q = SearchQuery(keys=["Comment"], keywords="photo", query_mode="LIKE")
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "LIKE" in sql

    def test_keyword_exclude(self, populated_db):
        q = SearchQuery(keys=["Comment"], keywords="-badword", keyword_separator=",")
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "NOT IN" in sql

    def test_directory_filter(self, populated_db):
        q = SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"])
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "LIKE" in sql

    def test_directory_no_subfolders(self, populated_db):
        q = SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"], include_subfolders=False)
        sql, params = q._make_subquery(np)
        assert sql is not None
        assert "NOT LIKE" in sql

    def test_empty_keyword_filtered(self):
        q = SearchQuery(keys=["path"], keywords="", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == []

    def test_dash_only_keyword_filtered(self):
        q = SearchQuery(keys=["path"], keywords="-", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == []

    def test_mixed_empty_keywords(self):
        q = SearchQuery(keys=["path"], keywords="a,,b,-,-c", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["a", "b"]
        assert exclude == ["c"]

    def test_tuple_keywords_bypass_separator(self):
        q = SearchQuery(keys=["path"], keywords=("a,b", "c"), keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["a,b", "c"]

    def test_keywords_whitespace_strip(self):
        q = SearchQuery(keys=["path"], keywords=" a , b , -c ", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["a", "b"]
        assert exclude == ["c"]

    def test_exclude_only(self):
        q = SearchQuery(keys=["path"], keywords="-a,-b", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == ["a", "b"]

    def test_single_string_key_normalized(self):
        q = SearchQuery(keys="single")
        keys, include, exclude = q.normalize_inputs()
        assert keys == ["single"]


class TestSearchQueryDataclass:
    def test_frozen_immutable(self):
        q = SearchQuery(keys=["dpi"])
        import pytest

        with pytest.raises(AttributeError):
            q.keys = ("other",)

    def test_list_args_converted_to_tuple(self):
        q = SearchQuery(keys=["a", "b"], keywords=["c"], directories=["D:/x"])
        assert isinstance(q.keys, tuple)
        assert isinstance(q.keywords, tuple)
        assert isinstance(q.directories, tuple)
        assert q.keys == ("a", "b")

    def test_none_args_stay_none(self):
        q = SearchQuery()
        assert q.keys is None
        assert q.keywords is None
        assert q.directories is None

    def test_string_args_stay_string(self):
        q = SearchQuery(keys="single_key", keywords="word")
        assert isinstance(q.keys, str)
        assert isinstance(q.keywords, str)

    def test_equality(self):
        q1 = SearchQuery(keys=["dpi"], keywords="test")
        q2 = SearchQuery(keys=["dpi"], keywords="test")
        assert q1 == q2

    def test_inequality(self):
        q1 = SearchQuery(keys=["dpi"])
        q2 = SearchQuery(keys=["Artist"])
        assert q1 != q2

    def test_hashable(self):
        q1 = SearchQuery(keys=["dpi"], keywords="test")
        q2 = SearchQuery(keys=["dpi"], keywords="test")
        assert hash(q1) == hash(q2)
        s = {q1, q2}
        assert len(s) == 1

    def test_hash_differs(self):
        q1 = SearchQuery(keys=["dpi"])
        q2 = SearchQuery(keys=["Artist"])
        assert hash(q1) != hash(q2)


class TestFileSearchEngineGet:
    def test_get_by_meta_key(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["dpi"]))
        assert len(paths) == 200

    def test_get_by_filepath_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["path"], keywords="vacation"))
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100

    def test_get_by_meta_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["Comment"], keywords="photo number 5", query_mode="LIKE"))
        assert len(paths) > 0

    def test_get_with_directory(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["dpi"], directories=["C:/photos/vacation"]))
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100

    def test_get_with_directory_no_subfolders(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["dpi"], directories=["C:/photos"], include_subfolders=False))
        assert len(paths) == 0

    def test_get_with_exclude(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["Comment"]))
        excluded_paths, _, _ = engine.search(SearchQuery(keys=["Comment"], keywords="-number 0,", keyword_separator=","))
        assert len(excluded_paths) < len(all_paths)

    def test_get_sort_by_name(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="name", ascending=True))
        names = [os.path.basename(p) for p in paths]
        assert names == sorted(names)

    def test_get_sort_by_name_desc(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="name", ascending=False))
        names = [os.path.basename(p) for p in paths]
        assert names == sorted(names, reverse=True)

    def test_get_random(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="random"))
        assert len(paths) == 200

    def test_get_no_results(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["nonexistent_key"]))
        assert paths == []

    def test_get_glob_mode(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["path"], keywords="*vacation*", query_mode="GLOB"))
        assert len(paths) == 100


class TestFileSearchEngineListKeys:
    def test_list_all_keys(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery(directories=["C:/photos/vacation"])
        keys = engine.list_all_keys(q, sort_by_freq=True)
        key_names = [k[0] for k in keys]
        assert "path" in key_names
        assert "dpi" in key_names
        assert "Comment" in key_names

    def test_list_all_keys_no_filter(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery()
        keys = engine.list_all_keys(q)
        key_names = [k[0] for k in keys]
        assert "rating" in key_names
        assert "dpi" in key_names

    def test_list_all_keys_dedup(self, db_path):
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [("src1", "hash1", 100, 1.0)]
        images = [("c:/test/img.jpg", "src1", 1.5)]
        metas = [("c:/test/img.jpg", "shared_key", "meta_val", None)]
        tags = [("hash1", "shared_key", "tag_val", None)]
        db.upsert_batches(sources, images, metas, tags)
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        q = SearchQuery()
        keys = engine.list_all_keys(q, sort_by_freq=True)
        shared = [k for k in keys if k[0] == "shared_key"]
        assert len(shared) == 1
        assert shared[0][1] == 1


class TestFileSearchEngineSampleValues:
    def test_sample_values(self, populated_db):
        engine = FileSearchEngine(populated_db)
        values = engine.sample_values("dpi")
        assert len(values) > 0
        assert all(isinstance(v, str) for v in values)

    def test_sample_values_limit(self, populated_db):
        engine = FileSearchEngine(populated_db)
        values = engine.sample_values("dpi", limit=2)
        assert len(values) <= 2

    def test_sample_values_nonexistent_key(self, populated_db):
        engine = FileSearchEngine(populated_db)
        values = engine.sample_values("nonexistent_key_xyz")
        assert values == []

    def test_sample_values_distinct(self, db_path):
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [("s1", "h1", 100, 1.0), ("s2", "h2", 200, 2.0)]
        images = [("c:/a.jpg", "s1", 1.0), ("c:/b.jpg", "s2", 1.0)]
        metas = [
            ("c:/a.jpg", "test.key", "same_value", None),
            ("c:/b.jpg", "test.key", "same_value", None),
        ]
        db.upsert_batches(sources, images, metas, [])
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        values = engine.sample_values("test.key")
        assert values == ["same_value"]


class TestFileSearchEngineCombined:
    def test_get_combined_union(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["path"], keywords="vacation", append_mode="OR")
        q2 = SearchQuery(keys=["path"], keywords="work", append_mode="OR")
        paths, aspects = engine.search_multi([q1, q2])
        assert len(paths) == 200

    def test_get_combined_intersect(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["dpi"], append_mode="OR")
        q2 = SearchQuery(keys=["path"], keywords="vacation", append_mode="AND")
        paths, aspects = engine.search_multi([q1, q2])
        assert all("vacation" in p for p in paths)

    def test_skipped_middle_query_preserves_intersect(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["dpi"], append_mode="OR")
        q2 = SearchQuery(keys=["nonexistent_key_xyz"], keywords="nope", append_mode="OR")
        q3 = SearchQuery(keys=["path"], keywords="vacation", append_mode="AND")
        paths, aspects = engine.search_multi([q1, q2, q3])
        assert all("vacation" in p for p in paths)
        assert len(paths) == 100


class TestNaturalKey:
    def test_basic_order(self):
        names = ["IMG_1.jpg", "IMG_10.jpg", "IMG_2.jpg", "IMG_100.jpg"]
        assert sorted(names, key=natural_key) == [
            "IMG_1.jpg",
            "IMG_2.jpg",
            "IMG_10.jpg",
            "IMG_100.jpg",
        ]

    def test_pure_alpha(self):
        names = ["banana", "apple", "cherry"]
        assert sorted(names, key=natural_key) == ["apple", "banana", "cherry"]

    def test_pure_numeric_prefix(self):
        names = ["3_file", "1_file", "20_file", "10_file"]
        assert sorted(names, key=natural_key) == [
            "1_file",
            "3_file",
            "10_file",
            "20_file",
        ]

    def test_case_insensitive(self):
        names = ["B.jpg", "a.jpg", "C.jpg"]
        assert sorted(names, key=natural_key) == ["a.jpg", "B.jpg", "C.jpg"]

    def test_empty_string(self):
        assert natural_key("") == [""]

    def test_leading_zeros_equal(self):
        assert natural_key("file_001.jpg") == natural_key("file_01.jpg")
        assert natural_key("file_01.jpg") == natural_key("file_1.jpg")

    def test_unicode_digits(self):
        assert natural_key("file①.jpg") == ["file①.jpg"]
        assert natural_key("②③") == ["②③"]
        names = ["b①", "a②", "c"]
        assert sorted(names, key=natural_key) == ["a②", "b①", "c"]


class TestMatchClause:
    def test_like_escapes_percent(self):
        q = SearchQuery(keys=["Comment"], keywords="100%", query_mode="LIKE")
        clause, values = q._match_clause("v", ["100%"], "OR")
        assert "LIKE" in clause
        assert "ESCAPE" in clause
        assert values == ["%100\\%%"]

    def test_like_escapes_underscore(self):
        q = SearchQuery(keys=["Comment"], keywords="a_b", query_mode="LIKE")
        clause, values = q._match_clause("v", ["a_b"], "OR")
        assert values == ["%a\\_b%"]

    def test_like_escapes_backslash(self):
        q = SearchQuery(keys=["Comment"], keywords="a\\b", query_mode="LIKE")
        clause, values = q._match_clause("v", ["a\\b"], "OR")
        assert values == ["%a\\\\b%"]

    def test_glob_wraps_wildcard(self):
        q = SearchQuery(keys=["path"], query_mode="GLOB")
        clause, values = q._match_clause("v", ["test"], "OR")
        assert "GLOB" in clause
        assert values == ["*test*"]

    def test_empty_returns_nothing(self):
        q = SearchQuery(query_mode="LIKE")
        clause, values = q._match_clause("v", [], "OR")
        assert clause == ""
        assert values == []

    def test_multiple_keywords_joined_with_op(self):
        q = SearchQuery(query_mode="LIKE")
        clause, _ = q._match_clause("v", ["a", "b"], "AND")
        assert " AND " in clause

        clause, _ = q._match_clause("v", ["a", "b"], "OR")
        assert " OR " in clause


class TestDirClause:
    def test_empty_directories(self):
        q = SearchQuery(directories=[])
        clause, params = q._dir_clause("p", np)
        assert clause == ""
        assert params == []

    def test_none_in_directories(self):
        q = SearchQuery(directories=[None, ""])
        clause, params = q._dir_clause("p", np)
        assert clause == ""
        assert params == []

    def test_multiple_directories(self):
        q = SearchQuery(directories=["C:/a", "C:/b"])
        clause, params = q._dir_clause("p", np)
        assert " OR " in clause
        assert len(params) == 2


class TestSpecialCharSearch:
    def test_like_percent_in_filepath(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="100%",
                query_mode="LIKE",
            )
        )
        assert len(paths) == 1
        assert "100%_done" in paths[0]

    def test_like_underscore_in_filepath(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="under_score",
                query_mode="LIKE",
            )
        )
        assert len(paths) == 1

    def test_like_underscore_not_wildcard(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["path"]))
        paths_dot, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="under.score",
                query_mode="LIKE",
            )
        )
        assert len(paths_dot) == 0

    def test_like_percent_in_meta_value(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="%percent",
                query_mode="LIKE",
            )
        )
        assert len(paths) == 1

    def test_glob_star_literal(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="star",
                query_mode="GLOB",
            )
        )
        assert any("star*glob" in p for p in paths)

    def test_case_insensitive_like(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="upper",
                query_mode="LIKE",
            )
        )
        assert len(paths) == 1


class TestKeywordModeAnd:
    def test_keyword_and_narrows_results(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths_or, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="photo,number",
                keyword_separator=",",
                keyword_mode="OR",
            )
        )
        paths_and, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="photo,number",
                keyword_separator=",",
                keyword_mode="AND",
            )
        )
        assert len(paths_and) <= len(paths_or)
        assert len(paths_and) > 0

    def test_keyword_and_no_overlap(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="photo,zzz_nonexistent",
                keyword_separator=",",
                keyword_mode="AND",
            )
        )
        assert len(paths) == 0


class TestExcludeVariants:
    def test_exclude_only_no_include(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["path"]))
        excluded, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="-vacation",
                keyword_separator=",",
            )
        )
        assert len(excluded) < len(all_paths)
        assert all("vacation" not in p for p in excluded)

    def test_exclude_meta_value(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["Comment"]))
        excluded, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="-number 0,",
                keyword_separator=",",
            )
        )
        assert len(excluded) < len(all_paths)

    def test_exclude_tag_value(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["rating"]))
        excluded, _, _ = engine.search(
            SearchQuery(
                keys=["rating"],
                keywords="-1",
                keyword_separator=",",
            )
        )
        assert len(excluded) < len(all_paths)

    def test_exclude_all_keys(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q_all = SearchQuery(require_keys=False)
        all_paths, _ = engine.search_multi([q_all])
        q_exc = SearchQuery(require_keys=False, keywords="-vacation", keyword_separator=",")
        exc_paths, _ = engine.search_multi([q_exc])
        assert len(exc_paths) < len(all_paths)


class TestSearchMultiEdgeCases:
    def test_single_query(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery(keys=["path"], keywords="vacation")
        paths_single, _, _ = engine.search(q)
        paths_multi, _ = engine.search_multi([q])
        assert set(paths_single) == set(paths_multi)

    def test_all_and_with_no_match_returns_empty(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["path"], append_mode="OR")
        q2 = SearchQuery(keys=["nonexistent"], keywords="nope", append_mode="AND")
        paths, _ = engine.search_multi([q1, q2])
        assert paths == []

    def test_sort_uses_last_query(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=["path"], sort_by="name", ascending=True, append_mode="OR")
        q2 = SearchQuery(keys=["path"], sort_by="name", ascending=False, append_mode="OR")
        paths, _ = engine.search_multi([q1, q2])
        names = [os.path.basename(p) for p in paths]
        assert names == sorted(names, key=natural_key, reverse=True)


class TestSortVariants:
    def test_sort_by_modified(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="modified", ascending=True))
        assert len(paths) == 200

    def test_sort_by_created(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="created", ascending=True))
        assert len(paths) == 200

    def test_sort_by_size(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="size", ascending=True))
        assert len(paths) == 200

    def test_sort_by_path(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="path", ascending=True))
        assert len(paths) == 200

    def test_unknown_sort_returns_unordered(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="invalid_col"))
        assert len(paths) == 200


class TestMultipleDirectories:
    def test_search_two_directories(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                directories=["C:/photos/vacation", "C:/photos/work"],
            )
        )
        assert len(paths) == 200

    def test_search_one_directory_subset(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                directories=["C:/photos/vacation"],
            )
        )
        assert len(paths) == 100
        assert all("vacation" in p for p in paths)


class TestEngineLookupMethods:
    def test_get_meta_info_by_path(self, populated_db):
        engine = FileSearchEngine(populated_db)
        meta = engine.get_meta_info_by_path("C:/photos/vacation/img_0000.jpg")
        assert "dpi" in meta
        assert "Comment" in meta

    def test_get_meta_info_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        meta = engine.get_meta_info_by_path("C:/nonexistent/file.jpg")
        assert meta == {}

    def test_get_tags_by_path(self, populated_db):
        engine = FileSearchEngine(populated_db)
        _, _, tags, _ = engine.get_all_metadata("C:/photos/vacation/img_0000.jpg")
        assert "rating" in tags

    def test_get_tags_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        _, _, tags, _ = engine.get_all_metadata("C:/nonexistent/file.jpg")
        assert tags == {}

    def test_get_file_record(self, populated_db):
        engine = FileSearchEngine(populated_db)
        rec = engine.get_file_record("C:/photos/vacation/img_0000.jpg")
        assert rec.get("path") is not None
        assert rec.get("source") is not None

    def test_get_file_record_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        rec = engine.get_file_record("C:/nonexistent/file.jpg")
        assert rec == {}

    def test_get_source_by_path(self, populated_db):
        engine = FileSearchEngine(populated_db)
        src = engine.get_source_by_path("C:/photos/vacation/img_0000.jpg")
        assert src.get("file_hash") == "hash_0000"

    def test_get_source_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        src = engine.get_source_by_path("C:/nonexistent/file.jpg")
        assert src == {}

    def test_get_all_metadata(self, populated_db):
        engine = FileSearchEngine(populated_db)
        file_rec, file_hash, tags_with_lock, meta = engine.get_all_metadata("C:/photos/vacation/img_0000.jpg")
        assert file_rec.get("path") is not None
        assert file_hash is not None
        assert "rating" in tags_with_lock
        assert isinstance(tags_with_lock["rating"], tuple) and len(tags_with_lock["rating"]) == 2
        assert "dpi" in meta

    def test_get_collection_status_ok(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        path = "C:/photos/vacation/img_0000.jpg"
        db.insert_pending_collection([path], ["exif"])
        db.upsert_collection_results([], [], [], [(path, "exif", "ok", time.time())])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(path)
        assert len(result) == 1
        assert result[0] == ("exif", "ok")

    def test_get_collection_status_fail(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        path = "C:/photos/vacation/img_0000.jpg"
        db.insert_pending_collection([path], ["exif"])
        db.upsert_collection_results([], [], [], [(path, "exif", "fail", time.time())])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(path)
        assert len(result) == 1
        assert result[0] == ("exif", "fail")

    def test_get_collection_status_pending_hidden(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        path = "C:/photos/vacation/img_0000.jpg"
        db.insert_pending_collection([path], ["exif"])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(path)
        assert result == []

    def test_get_collection_status_stale_ok_hidden(self, populated_db):
        db = FileDB(populated_db)
        db.start()
        path = "C:/photos/vacation/img_0000.jpg"
        old_time = 1000.0
        db.insert_pending_collection([path], ["exif"])
        db.upsert_collection_results([], [], [], [(path, "exif", "ok", old_time)])
        db.close()
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status(path)
        assert result == []

    def test_get_collection_status_nonexistent(self, populated_db):
        engine = FileSearchEngine(populated_db)
        result = engine.get_collection_status("C:/nonexistent/file.jpg")
        assert result == []

    def test_nonexistent_db_path(self, tmp_path):
        engine = FileSearchEngine(str(tmp_path / "does_not_exist.db"))
        paths, sources, aspects = engine.search(SearchQuery(keys=["path"]))
        assert paths == []
        assert sources == []
        assert aspects == []

    def test_empty_db_missing_tables(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE dummy (id INTEGER)")
        conn.close()
        engine = FileSearchEngine(db_path)
        paths, sources, aspects = engine.search(SearchQuery(keys=["path"]))
        assert paths == []

    def test_reconnect_after_valid(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths1, _, _ = engine.search(SearchQuery(keys=["path"]))
        paths2, _, _ = engine.search(SearchQuery(keys=["path"]))
        assert paths1 == paths2


class TestExplainQueryPlan:
    def _plan_text(self, conn, sql, params=()):
        rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        return "\n".join(r["detail"] for r in rows)

    def test_filepath_uses_files_directly(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["path"], keywords="vacation")
        subq, params = q._make_subquery(np)
        sql = f"SELECT DISTINCT path FROM ({subq}) s0"
        plan = self._plan_text(engine.conn, sql, params)
        assert "files" in plan.lower()

    def test_meta_key_uses_index(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["dpi"])
        subq, params = q._make_subquery(np)
        sql = f"SELECT DISTINCT path FROM ({subq}) s0"
        plan = self._plan_text(engine.conn, sql, params)
        assert "idx_meta_info_key_fid" in plan or "meta_info" in plan.lower()

    def test_full_get_plan(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q = SearchQuery(keys=["dpi"])
        subq, params = q._make_subquery(np)
        distinct_paths = f"SELECT DISTINCT path FROM ({subq}) s0"
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN ({distinct_paths}) AS s USING(path)
            ORDER BY m.path ASC
        """
        plan = self._plan_text(engine.conn, sql, params)


class TestTagKeySearch:
    def test_search_by_tag_key_rating(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["rating"]))
        assert len(paths) == 200

    def test_search_by_tag_key_with_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["rating"], keywords="5"))
        assert len(paths) > 0
        assert len(paths) < 200

    def test_search_by_tag_only_key_category(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["category"]))
        assert len(paths) > 0

    def test_search_by_tag_keyword_landscape(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["category"], keywords="landscape"))
        assert len(paths) > 0
        assert all("vacation" in p for p in paths)

    def test_search_by_tag_keyword_office(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["category"], keywords="office"))
        assert len(paths) > 0
        assert all("work" in p for p in paths)


class TestMixedKeys:
    def test_filepath_and_meta_key(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["path", "dpi"]))
        assert len(paths) == 200

    def test_filepath_and_meta_key_with_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path", "dpi"],
                keywords="vacation",
            )
        )
        assert len(paths) > 0

    def test_filepath_and_tag_key(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["path", "rating"]))
        assert len(paths) == 200

    def test_meta_and_tag_keys(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi", "rating"]))
        assert len(paths) == 200

    def test_meta_and_tag_keys_with_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["dpi", "rating"],
                keywords="5",
            )
        )
        assert len(paths) > 0


class TestEmptyDB:
    @pytest.fixture
    def empty_db(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        db.close()
        return db_path

    def test_search_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        paths, sources, aspects = engine.search(SearchQuery(keys=["path"]))
        assert paths == []
        assert sources == []
        assert aspects == []

    def test_search_multi_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        q = SearchQuery(keys=["path"])
        paths, aspects = engine.search_multi([q])
        assert paths == []
        assert aspects == []

    def test_list_all_keys_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        keys = engine.list_all_keys(SearchQuery(), sort_by_freq=True)
        assert keys == []

    def test_get_meta_info_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        assert engine.get_meta_info_by_path("C:/any/file.jpg") == {}

    def test_get_tags_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        _, _, tags, _ = engine.get_all_metadata("C:/any/file.jpg")
        assert tags == {}

    def test_get_file_record_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        assert engine.get_file_record("C:/any/file.jpg") == {}

    def test_get_source_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        assert engine.get_source_by_path("C:/any/file.jpg") == {}

    def test_get_all_metadata_empty(self, empty_db):
        engine = FileSearchEngine(empty_db)
        file_rec, file_hash, tags_with_lock, meta = engine.get_all_metadata("C:/any/file.jpg")
        assert file_rec == {}
        assert file_hash is None
        assert tags_with_lock == {}
        assert meta == {}


class TestAspectRatioFallback:
    def test_null_aspect_ratio_defaults_to_1(self, tmp_path):
        db_path = str(tmp_path / "aspect.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [("C:/test/img.jpg", "hash1", 100, 1.0)]
        images = [("C:/test/img.jpg", "C:/test/img.jpg", None)]
        metas = [("C:/test/img.jpg", "path", "C:/test/img.jpg", None)]
        db.upsert_batches(sources, images, metas, [])
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        paths, sources_out, aspects = engine.search(SearchQuery(keys=["path"]))
        assert len(paths) == 1
        assert aspects[0] == 1.0

    def test_valid_aspect_ratio_preserved(self, tmp_path):
        db_path = str(tmp_path / "aspect2.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [("C:/test/img.jpg", "hash1", 100, 1.0)]
        images = [("C:/test/img.jpg", "C:/test/img.jpg", 1.777)]
        metas = [("C:/test/img.jpg", "path", "C:/test/img.jpg", None)]
        db.upsert_batches(sources, images, metas, [])
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        paths, _, aspects = engine.search(SearchQuery(keys=["path"]))
        assert aspects[0] == pytest.approx(1.777)


class TestIncludeExcludeCombined:
    def test_include_and_exclude(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="vacation,-img_0000",
                keyword_separator=",",
            )
        )
        assert len(paths) > 0
        assert all("vacation" in p for p in paths)
        assert all("img_0000" not in p for p in paths)

    def test_include_and_exclude_meta(self, populated_db):
        engine = FileSearchEngine(populated_db)
        all_paths, _, _ = engine.search(SearchQuery(keys=["Comment"], keywords="photo"))
        filtered, _, _ = engine.search(
            SearchQuery(
                keys=["Comment"],
                keywords="photo,-number 0",
                keyword_separator=",",
            )
        )
        assert len(filtered) < len(all_paths)
        assert len(filtered) > 0

    def test_exclude_everything_returns_empty(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="vacation,-vacation",
                keyword_separator=",",
            )
        )
        assert len(paths) == 0


class TestDirectoryFilterEdgeCases:
    def test_no_match_directory(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                directories=["C:/nonexistent_directory"],
            )
        )
        assert paths == []

    def test_include_subfolders_true_nested(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                directories=["C:/data"],
                include_subfolders=True,
            )
        )
        nested = [p for p in paths if "sub_dir" in p]
        assert len(nested) > 0

    def test_include_subfolders_false_excludes_nested(self, special_char_db):
        engine = FileSearchEngine(special_char_db)
        paths, _, _ = engine.search(
            SearchQuery(
                keys=["path"],
                directories=["C:/data"],
                include_subfolders=False,
            )
        )
        nested = [p for p in paths if "sub_dir" in p]
        assert len(nested) == 0
        assert len(paths) > 0


class TestFetchMethod:
    def test_fetch_raw_sql(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        rows = engine.fetch("SELECT COUNT(*) AS cnt FROM files", [])
        assert rows[0]["cnt"] == 200

    def test_fetch_with_params(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        rows = engine.fetch(
            "SELECT path FROM files WHERE path LIKE ?",
            ["%vacation%"],
        )
        assert len(rows) == 100

    def test_fetch_no_results(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        rows = engine.fetch(
            "SELECT path FROM files WHERE path = ?",
            ["nonexistent"],
        )
        assert rows == []


class TestListAllKeysWithKeywords:
    def test_list_keys_filtered_by_keyword(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery(keywords="vacation", keyword_separator=",")
        keys = engine.list_all_keys(q)
        key_names = [k[0] for k in keys]
        assert "path" in key_names

    def test_list_keys_filtered_by_directory(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery(directories=["C:/photos/vacation"])
        keys = engine.list_all_keys(q)
        key_names = [k[0] for k in keys]
        assert "path" in key_names
        assert "dpi" in key_names

    def test_list_keys_sorted_alphabetically(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery()
        keys = engine.list_all_keys(q, sort_by_freq=False)
        key_names = [k[0] for k in keys]
        assert key_names == sorted(key_names)

    def test_list_keys_sorted_by_freq(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q = SearchQuery()
        keys = engine.list_all_keys(q, sort_by_freq=True)
        freqs = [k[1] for k in keys]
        assert freqs == sorted(freqs, reverse=True)


class TestSearchMultiMoreCases:
    def test_empty_queries_list(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, aspects = engine.search_multi([])
        assert paths == []
        assert aspects == []

    def test_all_queries_produce_none_and(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=None, require_keys=True, append_mode="AND")
        q2 = SearchQuery(keys=None, require_keys=True, append_mode="AND")
        paths, aspects = engine.search_multi([q1, q2])
        assert paths == []

    def test_all_queries_produce_none_or(self, populated_db):
        engine = FileSearchEngine(populated_db)
        q1 = SearchQuery(keys=None, require_keys=True, append_mode="OR")
        q2 = SearchQuery(keys=None, require_keys=True, append_mode="OR")
        paths, aspects = engine.search_multi([q1, q2])
        assert paths == []


class TestSortByCollected:
    def test_sort_by_collected_asc(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="collected", ascending=True))
        assert len(paths) == 200

    def test_sort_by_collected_desc(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, _, _ = engine.search(SearchQuery(keys=["dpi"], sort_by="collected", ascending=False))
        assert len(paths) == 200


class TestSearchSourceValues:
    def test_search_returns_correct_sources(self, populated_db):
        engine = FileSearchEngine(populated_db)
        paths, sources, _ = engine.search(
            SearchQuery(
                keys=["path"],
                keywords="img_0000",
            )
        )
        assert len(paths) > 0
        for path, source in zip(paths, sources):
            assert source is not None
            src_rec = engine.get_source_by_path(path)
            assert src_rec.get("source") == source

    def test_search_source_and_path_match(self, tmp_path):
        db_path = str(tmp_path / "src_test.db")
        db = FileDB(db_path)
        db.start()
        db.initialize_database()
        sources = [
            ("src_a.png", "h1", 100, 1.0),
            ("src_b.png", "h2", 200, 2.0),
        ]
        images = [
            ("C:/dir/a.jpg", "src_a.png", 1.5),
            ("C:/dir/b.jpg", "src_b.png", 2.0),
        ]
        metas = [
            ("C:/dir/a.jpg", "path", "C:/dir/a.jpg", None),
            ("C:/dir/b.jpg", "path", "C:/dir/b.jpg", None),
        ]
        db.upsert_batches(sources, images, metas, [])
        db.conn.commit()
        db.close()
        engine = FileSearchEngine(db_path)
        paths, srcs, _ = engine.search(SearchQuery(keys=["path"]))
        result_map = dict(zip(paths, srcs))
        assert result_map[np("C:/dir/a.jpg")] == "src_a.png"
        assert result_map[np("C:/dir/b.jpg")] == "src_b.png"


class TestNaturalKeyEdgeCases:
    def test_special_characters(self):
        names = ["a-1.jpg", "a-10.jpg", "a-2.jpg"]
        assert sorted(names, key=natural_key) == ["a-1.jpg", "a-2.jpg", "a-10.jpg"]

    def test_mixed_alpha_numeric(self):
        names = ["file10b", "file2a", "file10a", "file2b"]
        assert sorted(names, key=natural_key) == ["file2a", "file2b", "file10a", "file10b"]

    def test_unicode_characters(self):
        keys = [natural_key(n) for n in ["画僁E.jpg", "画僁E0.jpg", "画僁E.jpg"]]
        names = ["画僁E.jpg", "画僁E0.jpg", "画僁E.jpg"]
        assert sorted(names, key=natural_key) == ["画僁E0.jpg", "画僁E.jpg", "画僁E.jpg"]

    def test_only_digits(self):
        names = ["100", "20", "3", "1"]
        assert sorted(names, key=natural_key) == ["1", "3", "20", "100"]

    def test_long_number_sequences(self):
        names = ["file_999999.jpg", "file_1000000.jpg", "file_100.jpg"]
        assert sorted(names, key=natural_key) == [
            "file_100.jpg",
            "file_999999.jpg",
            "file_1000000.jpg",
        ]


class TestBuildPathQueryEdgeCases:
    def test_and_query_with_null_subquery_returns_none(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q_null = SearchQuery(keys=None, require_keys=True, append_mode="AND")
        result, params = engine._build_path_query([q_null])
        assert result is None
        assert params == []

    def test_or_query_with_null_subquery_skipped(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        q_null = SearchQuery(keys=None, require_keys=True, append_mode="OR")
        q_valid = SearchQuery(keys=["path"], append_mode="OR")
        result, params = engine._build_path_query([q_null, q_valid])
        assert result is not None

    def test_empty_list_returns_none(self, populated_db):
        engine = FileSearchEngine(populated_db)
        assert engine._connect_if_needed()
        result, params = engine._build_path_query([])
        assert result is None


class TestSearchQueryNormalizeInputs:
    def test_none_keywords(self):
        q = SearchQuery(keys=["path"], keywords=None)
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == []

    def test_single_keyword_no_separator(self):
        q = SearchQuery(keys=["path"], keywords="hello world")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["hello world"]
        assert exclude == []

    def test_keyword_separator_splits(self):
        q = SearchQuery(keys=["path"], keywords="a|b|c", keyword_separator="|")
        keys, include, exclude = q.normalize_inputs()
        assert include == ["a", "b", "c"]

    def test_exclude_with_no_include(self):
        q = SearchQuery(keys=["path"], keywords="-only_exclude", keyword_separator=",")
        keys, include, exclude = q.normalize_inputs()
        assert include == []
        assert exclude == ["only_exclude"]

    def test_keys_none_returns_empty(self):
        q = SearchQuery(keys=None)
        keys, include, exclude = q.normalize_inputs()
        assert keys == []


class TestKvSortJoinValidation:
    def test_valid_identifier(self):
        join, select, order, params = _kv_sort_join("name")
        assert "name" in select
        assert params == ["name", "name"]

    def test_valid_identifier_with_underscore(self):
        join, select, order, params = _kv_sort_join("my_key_2")
        assert "my_key_2" in select

    @pytest.mark.parametrize(
        "bad_key",
        [
            "DROP TABLE",
            "x; --",
            "1invalid",
            "",
            "a b",
            'key"name',
            "key'name",
        ],
    )
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


class TestExplainQueryPlanRealDB:
    REAL_DB = os.environ.get("TEST_REAL_DB", "")

    @pytest.fixture
    def real_engine(self):
        if not self.REAL_DB or not os.path.exists(self.REAL_DB):
            pytest.skip("Set TEST_REAL_DB env var to a real .db path")
        return FileSearchEngine(self.REAL_DB)

    def _plan_and_time(self, engine, label, sql, params=()):
        assert engine._connect_if_needed()
        conn = engine.conn
        plan_rows = conn.execute(f"EXPLAIN QUERY PLAN {sql}", params).fetchall()
        plan = "\n".join(f"  [{r['id']}] {r['detail']}" for r in plan_rows)
        times = []
        for _ in range(3):
            t0 = time.perf_counter()
            rows = conn.execute(sql, params).fetchall()
            times.append(time.perf_counter() - t0)
        avg_ms = sum(times) / len(times) * 1000
        best_ms = min(times) * 1000
        print(f"\n{'=' * 60}")
        print(f"[{label}]")
        print(plan)
        print(f"  ROWS: {len(rows)}  AVG: {avg_ms:.1f}ms  BEST: {best_ms:.1f}ms")
        return plan, rows, avg_ms

    def test_meta_key_query(self, real_engine):
        assert real_engine._connect_if_needed()
        cur = real_engine.conn.cursor()
        top_key = cur.execute("SELECT key FROM meta_info GROUP BY key ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
        if not top_key:
            pytest.skip("No meta_info data")
        key = top_key[0]
        q = SearchQuery(keys=[key])
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.path ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"meta key='{key}'", sql, params)

    def test_filepath_query(self, real_engine):
        q = SearchQuery(keys=["path"], keywords="img")
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.path ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, "path keyword='img'", sql, params)

    def test_directory_query(self, real_engine):
        assert real_engine._connect_if_needed()
        sample = real_engine.conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No image data")
        parts = sample[0].replace("\\", "/").split("/")
        sample_dir = "/".join(parts[:4])
        q = SearchQuery(keys=["path"], directories=[sample_dir])
        subq, params = q._make_subquery(np)
        sql = f"""
            SELECT m.path, m.source, m.aspect_ratio
            FROM files_full AS m
            JOIN (SELECT DISTINCT path FROM ({subq}) s0) AS s USING(path)
            ORDER BY m.path ASC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"directory='{sample_dir}'", sql, params)

    def test_list_all_keys_query(self, real_engine):
        assert real_engine._connect_if_needed()
        sample = real_engine.conn.execute("SELECT path FROM files LIMIT 1").fetchone()
        if not sample:
            pytest.skip("No image data")
        parts = sample[0].replace("\\", "/").split("/")
        sample_dir = "/".join(parts[:4])
        q = SearchQuery(directories=[sample_dir])
        subq, params = q._make_subquery(np, require_keys_override=False)
        sql = f"""
            SELECT key, COUNT(*) AS freq
            FROM ({subq}) AS items
            GROUP BY key
            ORDER BY freq DESC
        """
        plan, rows, avg_ms = self._plan_and_time(real_engine, f"list_all_keys dir='{sample_dir}'", sql, params)

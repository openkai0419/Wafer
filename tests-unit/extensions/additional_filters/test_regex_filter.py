from __future__ import annotations

import hashlib
import os
import re
import sqlite3

import pytest

from wafer.core.db.db_utils import apply_read_pragmas, apply_write_pragmas

from extensions.additional_filters.regex_filter import (
    RegexFilter,
    _extract_literal_hints,
    _escape_like,
)


def _setup_db(tmp_path, files=None, meta=None, tags=None):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    apply_write_pragmas(conn)
    conn.execute("CREATE TABLE hash_index (file_hash TEXT PRIMARY KEY)")
    conn.execute("""CREATE TABLE sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))""")
    conn.execute("""CREATE TABLE files (
        path TEXT PRIMARY KEY, source TEXT NOT NULL, aspect_ratio REAL,
        FOREIGN KEY(source) REFERENCES sources(source))""")
    conn.execute("""CREATE TABLE meta_info (
        path TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        PRIMARY KEY(path, key),
        FOREIGN KEY(path) REFERENCES files(path))""")
    conn.execute("""CREATE TABLE tags (
        file_hash TEXT NOT NULL, key TEXT NOT NULL, value TEXT, value_num REAL,
        PRIMARY KEY(file_hash, key),
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))""")
    conn.execute("""CREATE VIEW files_full AS
        SELECT i.path, i.source, i.aspect_ratio,
               s.file_hash, s.size, s.modified
        FROM files i JOIN sources s ON s.source = i.source""")
    conn.executescript("""
        CREATE INDEX idx_meta_key ON meta_info(key, path);
        CREATE INDEX idx_tags_key ON tags(key, file_hash);
    """)

    for path in files or []:
        fhash = hashlib.md5(path.encode()).hexdigest()
        source = path
        name = os.path.basename(path)
        conn.execute("INSERT OR IGNORE INTO hash_index VALUES (?)", (fhash,))
        conn.execute("INSERT INTO sources VALUES (?,?,?,?)", (source, fhash, 100, 1.0))
        conn.execute("INSERT INTO files VALUES (?,?,?)", (path, source, 1.0))
        conn.execute("INSERT OR REPLACE INTO meta_info VALUES (?,?,?,?)", (path, "path", path, None))
        conn.execute("INSERT OR REPLACE INTO meta_info VALUES (?,?,?,?)", (path, "name", name, None))

    for path, key, value in meta or []:
        conn.execute("INSERT OR REPLACE INTO meta_info VALUES (?,?,?,?)", (path, key, value, None))

    for path, key, value in tags or []:
        fhash = hashlib.md5(path.encode()).hexdigest()
        conn.execute("INSERT OR REPLACE INTO tags VALUES (?,?,?,?)", (fhash, key, value, None))

    conn.commit()
    conn.close()
    return db_path


def _query(db_path, params):
    sql, bind = RegexFilter.build_path_query(params, lambda p: p)
    if sql is None:
        return set()
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    apply_read_pragmas(conn)
    rows = conn.execute(sql, bind).fetchall()
    conn.close()

    result_rows = [dict(r) for r in rows]
    result_rows = RegexFilter.post_filter(params, result_rows)
    return {r["path"] for r in result_rows}


class TestExtractLiteralHints:
    def test_simple_literal(self):
        assert _extract_literal_hints("hello") == ["hello"]

    def test_digit_class(self):
        assert _extract_literal_hints(r"\d+") == []

    def test_mixed_literal_and_class(self):
        hints = _extract_literal_hints(r"\d{4}_sunset")
        assert "_sunset" in hints

    def test_alternation_in_group(self):
        hints = _extract_literal_hints(r"(cat|dog)_photo")
        assert "_photo" in hints
        assert "cat" not in hints
        assert "dog" not in hints

    def test_top_level_alternation(self):
        assert _extract_literal_hints("cat|dog") == []

    def test_escaped_dot(self):
        hints = _extract_literal_hints(r"test\.jpg")
        assert any(".jpg" in h for h in hints) or "test.jpg" in hints

    def test_escaped_backslash(self):
        hints = _extract_literal_hints(r"path\\to\\file")
        combined = "".join(hints)
        assert "path" in combined
        assert "to" in combined
        assert "file" in combined

    def test_character_class(self):
        hints = _extract_literal_hints(r"[abc]_test")
        assert "_test" in hints

    def test_quantifier_star(self):
        hints = _extract_literal_hints("ab*c")
        assert "ab" not in hints
        assert any("a" in h for h in hints)
        assert any("c" in h for h in hints)

    def test_quantifier_plus(self):
        hints = _extract_literal_hints("ab+c")
        assert "ab" in hints

    def test_quantifier_question(self):
        hints = _extract_literal_hints("ab?c")
        assert "ab" not in hints
        assert any("a" in h for h in hints)

    def test_quantifier_brace_zero_min(self):
        hints = _extract_literal_hints("ab{0,3}c")
        assert "ab" not in hints

    def test_quantifier_brace_nonzero_min(self):
        hints = _extract_literal_hints("ab{2,5}c")
        assert "ab" in hints

    def test_dot_breaks_literal(self):
        hints = _extract_literal_hints("hello.world")
        assert "hello" in hints
        assert "world" in hints
        assert "hello.world" not in hints

    def test_anchors_break_literal(self):
        hints = _extract_literal_hints("^hello$")
        assert "hello" in hints

    def test_nested_group_with_alternation(self):
        hints = _extract_literal_hints(r"prefix_(a|b(c|d)e)_suffix")
        assert "prefix_" in hints
        assert "_suffix" in hints

    def test_empty_pattern(self):
        assert _extract_literal_hints("") == []

    def test_invalid_pattern(self):
        assert _extract_literal_hints("[invalid") == []

    def test_complex_real_world(self):
        hints = _extract_literal_hints(r"IMG_\d{4}\.jpg$")
        assert "IMG_" in hints
        assert ".jpg" in hints

    def test_no_literal_content(self):
        assert _extract_literal_hints(r".*") == []
        assert _extract_literal_hints(r"\w+") == []
        assert _extract_literal_hints(r"[a-z]+") == []

    def test_non_capturing_group(self):
        hints = _extract_literal_hints(r"(?:abc)_test")
        assert "abc" in hints
        assert "_test" in hints

    def test_lookahead(self):
        hints = _extract_literal_hints(r"abc(?=def)")
        assert "abc" in hints

    def test_lazy_quantifier(self):
        hints = _extract_literal_hints(r"ab+?c")
        assert "ab" in hints


class TestInheritableParams:
    def test_exports_keys_and_ignore_case(self):
        params = {
            "keys": ["path", "prompt"],
            "pattern": r"photo.*2024",
            "ignore_case": True,
        }
        result = RegexFilter.inheritable_params(params)
        assert result == {"keys": ["path", "prompt"], "ignore_case": True}
        assert "pattern" not in result

    def test_empty_params(self):
        assert RegexFilter.inheritable_params({}) == {}

    def test_partial_params(self):
        result = RegexFilter.inheritable_params({"ignore_case": False})
        assert result == {"ignore_case": False}


class TestBuildPathQuery:
    def test_empty_pattern_returns_none(self, tmp_path):
        sql, bind = RegexFilter.build_path_query({"pattern": "", "keys": ["path"]}, lambda p: p)
        assert sql is None

    def test_invalid_regex_returns_none(self, tmp_path):
        sql, bind = RegexFilter.build_path_query({"pattern": "[invalid", "keys": ["path"]}, lambda p: p)
        assert sql is None

    def test_no_keys_with_require_keys(self, tmp_path):
        sql, bind = RegexFilter.build_path_query({"pattern": "test", "keys": [], "require_keys": True}, lambda p: p)
        assert "WHERE 0" in sql

    def test_filepath_key_produces_sql(self, tmp_path):
        sql, bind = RegexFilter.build_path_query({"pattern": "test", "keys": ["path"]}, lambda p: p)
        assert sql is not None
        assert "files" in sql

    def test_meta_key_produces_sql(self, tmp_path):
        sql, bind = RegexFilter.build_path_query({"pattern": "test", "keys": ["description"]}, lambda p: p)
        assert sql is not None
        assert "meta_info" in sql
        assert "tags" in sql


class TestPathFiltering:
    def test_simple_regex_on_path(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/IMG_0001.jpg",
                "c:/photos/IMG_0002.jpg",
                "c:/photos/vacation.png",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"IMG_\d+\.jpg",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/IMG_0001.jpg", "c:/photos/IMG_0002.jpg"}

    def test_no_match(self, tmp_path):
        db = _setup_db(tmp_path, files=["c:/a.jpg", "c:/b.png"])
        result = _query(
            db,
            {
                "pattern": r"zzz_nonexistent",
                "keys": ["path"],
            },
        )
        assert result == set()

    def test_all_match(self, tmp_path):
        db = _setup_db(tmp_path, files=["c:/a.jpg", "c:/b.jpg"])
        result = _query(
            db,
            {
                "pattern": r"\.jpg$",
                "keys": ["path"],
            },
        )
        assert result == {"c:/a.jpg", "c:/b.jpg"}

    def test_case_sensitive_by_default(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/Test.jpg",
                "c:/photos/test.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"Test",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/Test.jpg"}

    def test_case_insensitive(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/Test.jpg",
                "c:/photos/test.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"test",
                "keys": ["path"],
                "ignore_case": True,
            },
        )
        assert result == {"c:/photos/Test.jpg", "c:/photos/test.jpg"}

    def test_complex_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/2024-01-15_sunset.jpg",
                "c:/photos/2024-12-25_christmas.jpg",
                "c:/photos/vacation_2024.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"\d{4}-\d{2}-\d{2}_",
                "keys": ["path"],
            },
        )
        assert result == {
            "c:/photos/2024-01-15_sunset.jpg",
            "c:/photos/2024-12-25_christmas.jpg",
        }

    def test_alternation_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/cat_photo.jpg",
                "c:/dog_photo.jpg",
                "c:/bird_photo.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"(cat|dog)_photo",
                "keys": ["path"],
            },
        )
        assert result == {"c:/cat_photo.jpg", "c:/dog_photo.jpg"}

    def test_dot_literal_escaped(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/file.txt",
                "c:/fileTtxt",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"file\.txt",
                "keys": ["path"],
            },
        )
        assert result == {"c:/file.txt"}

    def test_pattern_with_no_literal_hints(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/123.jpg",
                "c:/abc.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"^\w:/\d+\.jpg$",
                "keys": ["path"],
            },
        )
        assert result == {"c:/123.jpg"}

    def test_special_sql_chars_in_path(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/100%_done.jpg",
                "c:/photos/normal.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"100%_done",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/100%_done.jpg"}

    def test_unicode_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/日本_旅行.jpg",
                "c:/photos/america_trip.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": "日本",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/日本_旅行.jpg"}


class TestMetaFiltering:
    def test_meta_value_like_match(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg"],
            meta=[
                ("c:/a.jpg", "desc", "sunset_beach_2024"),
                ("c:/b.jpg", "desc", "mountain_hike"),
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"sunset",
                "keys": ["desc"],
            },
        )
        assert "c:/a.jpg" in result

    def test_tag_value_like_match(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg"],
            tags=[
                ("c:/a.jpg", "category", "photo_sunset_2024"),
                ("c:/b.jpg", "category", "photo_mountain"),
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"sunset",
                "keys": ["category"],
            },
        )
        assert "c:/a.jpg" in result

    def test_query_all_keys(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/sunset.jpg", "c:/mountain.jpg"],
            meta=[("c:/mountain.jpg", "desc", "sunset_view")],
        )
        result = _query(
            db,
            {
                "pattern": r"sunset",
                "keys": [],
                "require_keys": False,
            },
        )
        assert "c:/sunset.jpg" in result
        assert "c:/mountain.jpg" in result


class TestPostFilter:
    def test_filepath_only_exact_verification(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/IMG_0001.jpg",
                "c:/photos/IMG_test.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"IMG_\d{4}",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/IMG_0001.jpg"}

    def test_mixed_keys_no_path_stripping(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/IMG_test.jpg"],
            meta=[("c:/IMG_test.jpg", "desc", "IMG_0001_sunset")],
        )
        result = _query(
            db,
            {
                "pattern": r"IMG_\d{4}",
                "keys": ["path", "desc"],
            },
        )
        assert "c:/IMG_test.jpg" in result


class TestEdgeCases:
    def test_empty_db(self, tmp_path):
        db = _setup_db(tmp_path)
        result = _query(
            db,
            {
                "pattern": r"test",
                "keys": ["path"],
            },
        )
        assert result == set()

    def test_pattern_matching_nothing(self, tmp_path):
        db = _setup_db(tmp_path, files=["c:/a.jpg"])
        result = _query(
            db,
            {
                "pattern": r"^$",
                "keys": ["path"],
            },
        )
        assert result == set()

    def test_like_false_positive_filtered_by_post(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/photos/test_1234_photo.jpg",
                "c:/photos/test_abcd_photo.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"test_\d{4}_photo",
                "keys": ["path"],
            },
        )
        assert result == {"c:/photos/test_1234_photo.jpg"}

    def test_backslash_in_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/path\\to\\file.jpg",
                "c:/path/to/file.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"path\\to\\file",
                "keys": ["path"],
            },
        )
        assert "c:/path\\to\\file.jpg" in result

    def test_only_quantifiers_pattern(self, tmp_path):
        db = _setup_db(tmp_path, files=["c:/a.jpg"])
        result = _query(
            db,
            {
                "pattern": r".+",
                "keys": ["path"],
            },
        )
        assert result == {"c:/a.jpg"}

    def test_deeply_nested_groups(self, tmp_path):
        hints = _extract_literal_hints(r"a((b|c)(d|e))f")
        assert "a" in hints
        assert "f" in hints
        assert "b" not in hints
        assert "c" not in hints

    def test_quantifier_on_group(self, tmp_path):
        hints = _extract_literal_hints(r"(abc)+_end")
        assert "_end" in hints

    def test_percent_in_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/100%_complete.jpg",
                "c:/100_complete.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"100%_complete",
                "keys": ["path"],
            },
        )
        assert result == {"c:/100%_complete.jpg"}

    def test_underscore_in_literal(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=[
                "c:/a_b.jpg",
                "c:/axb.jpg",
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"a_b",
                "keys": ["path"],
            },
        )
        assert result == {"c:/a_b.jpg"}

    def test_no_false_negatives_for_path(self, tmp_path):
        files = [f"c:/photo_{i:04d}.jpg" for i in range(100)]
        db = _setup_db(tmp_path, files=files)

        pattern = r"photo_00[0-4]\d"
        expected = {f for f in files if re.search(pattern, f)}

        result = _query(
            db,
            {
                "pattern": pattern,
                "keys": ["path"],
            },
        )
        assert expected == result

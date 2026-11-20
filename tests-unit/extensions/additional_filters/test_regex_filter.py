from __future__ import annotations

import hashlib
import os
import re
import sqlite3


from wafer.core.db.db_utils import apply_write_pragmas
from wafer.core.db.query import FileSearchEngine

from extensions.additional_filters.regex_filter import (
    RegexFilter,
    _extract_literal_hints,
)


def _setup_db(tmp_path, files=None, meta=None, tags=None, source_num=None):
    db_path = tmp_path / "test.db"
    conn = sqlite3.connect(str(db_path))
    apply_write_pragmas(conn)
    conn.execute("CREATE TABLE hash_index (file_hash TEXT PRIMARY KEY)")
    conn.execute("""CREATE TABLE sources (
        source TEXT PRIMARY KEY, file_hash TEXT NOT NULL,
        size INTEGER, modified REAL, created REAL, collected REAL,
        FOREIGN KEY(file_hash) REFERENCES hash_index(file_hash))""")
    conn.execute("""CREATE TABLE files (
        path TEXT PRIMARY KEY, source TEXT NOT NULL, name TEXT, aspect_ratio REAL,
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
         SELECT i.path, i.name, i.source, i.aspect_ratio,
             s.file_hash, s.size, s.modified, s.created, s.collected
        FROM files i JOIN sources s ON s.source = i.source""")
    conn.executescript("""
        CREATE INDEX idx_meta_key ON meta_info(key, path);
        CREATE INDEX idx_tags_key ON tags(key, file_hash);
    """)

    source_overrides = {p: (size, modified, created, collected) for p, size, modified, created, collected in (source_num or [])}
    for path in files or []:
        fhash = hashlib.md5(path.encode()).hexdigest()
        source = path
        name = os.path.basename(path)
        size, modified, created, collected = source_overrides.get(path, (100, 1.0, None, None))
        conn.execute("INSERT OR IGNORE INTO hash_index VALUES (?)", (fhash,))
        conn.execute("INSERT INTO sources VALUES (?,?,?,?,?,?)", (source, fhash, size, modified, created, collected))
        conn.execute("INSERT INTO files VALUES (?,?,?,?)", (path, source, name, 1.0))

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
    engine = FileSearchEngine(str(db_path))
    try:
        assert engine._connect_if_needed()
        return {r["path"] for r in engine.conn.execute(sql, bind)}
    finally:
        engine.close()


class TestExtractLiteralHints:
    def test_simple_literal(self):
        assert _extract_literal_hints("hello") == ["hello"]

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

    def test_quantifier_zero_min(self):
        for pattern in ("ab*c", "ab?c", "ab{0,3}c"):
            hints = _extract_literal_hints(pattern)
            assert "ab" not in hints
            assert any("a" in h for h in hints)
            assert any("c" in h for h in hints)

    def test_quantifier_nonzero_min(self):
        for pattern in ("ab+c", "ab{2,5}c"):
            assert "ab" in _extract_literal_hints(pattern)

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
        assert _extract_literal_hints(r"(?:abc)_test") == ["abc_test"]

    def test_lookahead(self):
        hints = _extract_literal_hints(r"abc(?=def)")
        assert "abc" in hints

    def test_lookaround_text_is_never_a_hint(self):
        assert _extract_literal_hints(r"abc(?=def)") == ["abc"]
        assert _extract_literal_hints(r"foo(?!bar)") == ["foo"]
        assert _extract_literal_hints(r"(?<=x)abc") == ["abc"]
        assert _extract_literal_hints(r"(?<!x)abc") == ["abc"]
        assert _extract_literal_hints(r"(?<=pre)mid(?!post)end") == ["mid", "end"]

    def test_groups_nested_in_lookaround_are_never_hints(self):
        assert _extract_literal_hints(r"foo(?!(?:bar)baz)") == ["foo"]
        assert _extract_literal_hints(r"foo(?!b(ar)(?=z)q)") == ["foo"]
        assert _extract_literal_hints(r"(?:foo(?<!xfoo))end") == ["foo", "end"]

    def test_lazy_quantifier(self):
        hints = _extract_literal_hints(r"ab+?c")
        assert "ab" in hints

    def test_optional_groups_are_never_hints(self):
        for pattern in (r"(abc)?def", r"(abc)*def", r"(abc){0,2}def", r"(?:abc)??def"):
            assert _extract_literal_hints(pattern) == ["def"], pattern

    def test_escapes_are_hinted_as_the_character_they_match(self):
        assert _extract_literal_hints(r"foo\nbar") == ["foo\nbar"]
        assert _extract_literal_hints(r"a\tb") == ["a\tb"]
        assert _extract_literal_hints(r"\x41BC") == ["ABC"]
        assert _extract_literal_hints(r"あx") == ["あx"]

    def test_verbose_patterns_and_comments_are_hinted_as_matched(self):
        assert _extract_literal_hints(r"(?x)a b  # note") == ["ab"]
        assert _extract_literal_hints(r"x(?#comment)y") == ["xy"]

    def test_conditional_groups_are_never_hints(self):
        assert _extract_literal_hints(r"(a)?(?(1)b|c)") == []

    def test_text_under_local_ignore_case_keeps_only_ascii(self):
        assert _extract_literal_hints("x(?i:abあ)y") == ["xab", "y"]


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
    def test_standard_name_match(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/photos/sunset_001.jpg", "c:/photos/mountain.jpg"],
        )
        result = _query(
            db,
            {
                "pattern": r"sunset_\d+",
                "keys": ["name"],
            },
        )
        assert result == {"c:/photos/sunset_001.jpg"}

    def test_standard_size_match(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg"],
            source_num=[
                ("c:/a.jpg", 12345, 10.0, None, None),
                ("c:/b.jpg", 999, 20.0, None, None),
            ],
        )
        result = _query(
            db,
            {
                "pattern": r"12345",
                "keys": ["size"],
            },
        )
        assert result == {"c:/a.jpg"}

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

    def test_lookaround_text_does_not_exclude_matches(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg", "c:/c.jpg"],
            meta=[
                ("c:/a.jpg", "desc", "foobaz"),
                ("c:/b.jpg", "desc", "foobar"),
                ("c:/c.jpg", "desc", "yabc"),
            ],
        )
        assert _query(db, {"pattern": r"foo(?!bar)", "keys": ["desc"]}) == {"c:/a.jpg"}
        assert _query(db, {"pattern": r"foo(?=baz)", "keys": ["desc"]}) == {"c:/a.jpg"}
        assert _query(db, {"pattern": r"(?<!x)abc", "keys": ["desc"]}) == {"c:/c.jpg"}
        assert _query(db, {"pattern": r"(?<=y)abc", "keys": ["desc"]}) == {"c:/c.jpg"}

    def test_patterns_whose_text_is_optional_or_escaped_keep_every_match(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg", "c:/c.jpg"],
            meta=[
                ("c:/a.jpg", "desc", "def only"),
                ("c:/b.jpg", "desc", "line1\nline2"),
                ("c:/c.jpg", "desc", "ABC"),
            ],
        )
        assert _query(db, {"pattern": r"(abc)?def", "keys": ["desc"]}) == {"c:/a.jpg"}
        assert _query(db, {"pattern": r"line1\nline2", "keys": ["desc"]}) == {"c:/b.jpg"}
        assert _query(db, {"pattern": r"(?x) def \s only", "keys": ["desc"]}) == {"c:/a.jpg"}
        assert _query(db, {"pattern": r"\x41BC", "keys": ["desc"]}) == {"c:/c.jpg"}

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

    def test_file_hash_key_matches_source_hash(self, tmp_path):
        db = _setup_db(tmp_path, files=["c:/a.jpg", "c:/b.jpg"])
        target = hashlib.md5(b"c:/b.jpg").hexdigest()
        assert _query(db, {"pattern": target[:12], "keys": ["file_hash"]}) == {"c:/b.jpg"}


class TestMixedKeys:
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

    def test_like_false_positive_filtered_by_regex(self, tmp_path):
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

    def test_quantifier_on_group(self, tmp_path):
        hints = _extract_literal_hints(r"(abc)+_end")
        assert "_end" in hints

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


class TestValueRegex:
    def test_meta_value_must_match_pattern(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg", "c:/c.jpg"],
            meta=[
                ("c:/a.jpg", "desc", "seed 1234"),
                ("c:/b.jpg", "desc", "seed abcd"),
            ],
        )
        assert _query(db, {"pattern": r"seed \d+", "keys": ["desc"]}) == {"c:/a.jpg"}

    def test_meta_value_without_hints_is_evaluated(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg"],
            meta=[("c:/a.jpg", "steps", "28"), ("c:/b.jpg", "steps", "x")],
        )
        assert _query(db, {"pattern": r"^\d+$", "keys": ["steps"]}) == {"c:/a.jpg"}

    def test_ignore_case_on_meta_value(self, tmp_path):
        db = _setup_db(
            tmp_path,
            files=["c:/a.jpg", "c:/b.jpg"],
            meta=[("c:/a.jpg", "desc", "SUNSET"), ("c:/b.jpg", "desc", "sunrise")],
        )
        assert _query(db, {"pattern": "sunset", "keys": ["desc"]}) == set()
        assert _query(db, {"pattern": "sunset", "keys": ["desc"], "ignore_case": True}) == {"c:/a.jpg"}

    def test_inline_flags_are_not_hints(self):
        assert _extract_literal_hints("(?i)abc") == ["abc"]
        assert _extract_literal_hints("(?s:ab)cd") == ["abcd"]

    def test_path_regex_keeps_or_combined_results(self, tmp_path):
        from wafer.builtins.sorts import NoSort
        from wafer.plugin.query.composer import SearchComposer

        db = _setup_db(
            tmp_path,
            files=["c:/x/match.jpg", "c:/y/other.jpg", "c:/z/none.jpg"],
            meta=[("c:/y/other.jpg", "desc", "sunset")],
        )
        engine = FileSearchEngine(str(db))
        try:
            entries = [
                (RegexFilter, {"pattern": "match", "keys": ["path"]}, None),
                (RegexFilter, {"pattern": "sun", "keys": ["desc"]}, "OR"),
            ]
            paths, _sources, _aspects = SearchComposer().execute(engine, entries, NoSort, True)
        finally:
            engine.close()
        assert set(paths) == {"c:/x/match.jpg", "c:/y/other.jpg"}

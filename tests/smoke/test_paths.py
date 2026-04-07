import os
from pathlib import Path

from wafer.utils.paths import (
    normalize_path,
    safe_exists,
    safe_is_file,
    safe_is_dir,
    safe_getsize,
    natural_sort,
    stem,
    list_files,
)


class TestNormalizePath:
    def test_backslash_converted_to_forward(self, tmp_path):
        result = normalize_path(str(tmp_path) + "\\sub\\file.txt")
        assert "\\" not in result

    def test_absolute_path(self, tmp_path):
        p = tmp_path / "a.txt"
        p.write_text("x")
        result = normalize_path(str(p))
        assert os.path.isabs(result)

    def test_relative_path_becomes_absolute(self):
        result = normalize_path("relative/path.txt")
        assert os.path.isabs(result)

    def test_trailing_dot_resolved(self, tmp_path):
        result = normalize_path(str(tmp_path / "sub" / ".." / "file.txt"))
        assert ".." not in result

    def test_same_file_same_result(self, tmp_path):
        p = tmp_path / "f.txt"
        p.write_text("hi")
        a = normalize_path(str(p))
        b = normalize_path(str(p))
        assert a == b


class TestSafeFileChecks:
    def test_safe_exists_true(self, tmp_path):
        p = tmp_path / "exists.txt"
        p.write_text("ok")
        assert safe_exists(str(p)) is True

    def test_safe_exists_false(self, tmp_path):
        assert safe_exists(str(tmp_path / "nope.txt")) is False

    def test_safe_is_file(self, tmp_path):
        p = tmp_path / "file.txt"
        p.write_text("ok")
        assert safe_is_file(str(p)) is True
        assert safe_is_file(str(tmp_path)) is False

    def test_safe_is_dir(self, tmp_path):
        assert safe_is_dir(str(tmp_path)) is True
        assert safe_is_dir(str(tmp_path / "nope")) is False

    def test_safe_getsize(self, tmp_path):
        p = tmp_path / "sized.bin"
        p.write_bytes(b"12345")
        assert safe_getsize(str(p)) == 5

    def test_safe_getsize_missing(self, tmp_path):
        assert safe_getsize(str(tmp_path / "nope")) is None


class TestStem:
    def test_simple_filename(self):
        assert stem("/path/to/file.txt") == "file"

    def test_no_extension(self):
        assert stem("name") == "name"

    def test_multiple_dots(self):
        assert stem("/a/b.c.d.txt") == "b.c.d"

    def test_hidden_file(self):
        assert stem("/dir/.hidden") == ".hidden"


class TestNaturalSort:
    def test_numeric_order(self):
        result = natural_sort(["file10.txt", "file2.txt", "file1.txt"])
        assert result == ["file1.txt", "file2.txt", "file10.txt"]

    def test_empty_list(self):
        assert natural_sort([]) == []

    def test_single_item(self):
        assert natural_sort(["a"]) == ["a"]


class TestListFiles:
    def test_lists_matching_extension(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        (tmp_path / "b.txt").write_text("y")
        (tmp_path / "c.jpg").write_bytes(b"\xff")
        result = list_files(str(tmp_path), ".txt")
        assert len(result) == 2
        assert all(r.endswith(".txt") for r in result)

    def test_extension_without_dot(self, tmp_path):
        (tmp_path / "f.log").write_text("data")
        result = list_files(str(tmp_path), "log")
        assert len(result) == 1

    def test_no_match(self, tmp_path):
        (tmp_path / "a.txt").write_text("x")
        result = list_files(str(tmp_path), ".py")
        assert result == []

    def test_case_insensitive_extension(self, tmp_path):
        (tmp_path / "upper.TXT").write_text("x")
        result = list_files(str(tmp_path), ".txt")
        assert len(result) == 1

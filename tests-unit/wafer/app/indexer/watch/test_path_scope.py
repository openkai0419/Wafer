import py_compile

from wafer.app.indexer.watch.path_scope import compile_ignore_patterns, contains_path_prefix, normalize_prefixes
from wafer.core.common.paths import normalize_path


def test_compile():
    py_compile.compile("wafer/app/indexer/watch/path_scope.py")


def test_contains_path_prefix_boundary():
    prefixes = normalize_prefixes(["/a/b"])
    assert contains_path_prefix(prefixes, "/a/b")
    assert contains_path_prefix(prefixes, "/a/b/file.jpg")
    assert not contains_path_prefix(prefixes, "/a/bc/file.jpg")
    assert not contains_path_prefix(prefixes, "/a")


def test_contains_path_prefix_normalizes_paths(tmp_path):
    root = tmp_path / "root"
    child = root / "child" / "file.jpg"
    prefixes = normalize_prefixes([str(root)])
    assert contains_path_prefix(prefixes, str(child))


def test_contains_path_prefix_empty():
    assert not contains_path_prefix([], "/a/b")


def _matches(path, patterns):
    pattern_re = compile_ignore_patterns(patterns)
    return pattern_re is not None and pattern_re.match(normalize_path(path)) is not None


def test_compile_ignore_patterns_empty_returns_none():
    assert compile_ignore_patterns([]) is None


def test_matches_ignore_pattern_wildcard_substring():
    assert _matches("/a/b/my_cache_dir/file.jpg", ["*cache*"])
    assert not _matches("/a/b/data/file.jpg", ["*cache*"])


def test_matches_ignore_pattern_wildcard_spans_separators():
    assert _matches("/a/b/test/_cache.txt", ["*cache.txt"])
    assert not _matches("/a/b/test/cache.txt.bak", ["*cache.txt"])


def test_matches_ignore_pattern_literal_requires_full_match():
    full = normalize_path("/a/b/cache")
    assert _matches(full, [full])
    assert not _matches(full + "/child.jpg", [full])


def test_matches_ignore_pattern_is_case_sensitive():
    assert _matches("/a/b/CACHE/file.jpg", ["*CACHE*"])
    assert not _matches("/a/b/CACHE/file.jpg", ["*cache*"])
    assert not _matches("/a/b/cache/file.jpg", ["*CACHE*"])


def test_matches_ignore_pattern_empty():
    assert not _matches("/a/b", [])


def test_matches_ignore_pattern_multiple_patterns_combined():
    assert _matches("/a/b/thumbs.db", ["*cache*", "*thumbs.db"])
    assert _matches("/a/b/my_cache/x.jpg", ["*cache*", "*thumbs.db"])
    assert not _matches("/a/b/keep.jpg", ["*cache*", "*thumbs.db"])


import py_compile

from wafer.app.indexer.path_scope import contains_path_prefix, normalize_prefixes


def test_compile():
    py_compile.compile("wafer/app/indexer/path_scope.py")


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

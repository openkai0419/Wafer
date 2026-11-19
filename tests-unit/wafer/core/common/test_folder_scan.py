from wafer.core.common.folder_scan import has_subfolders, scan_child_paths, scan_children, scan_roots, visible_roots
from wafer.core.common.paths import normalize_path
from wafer.core.db.path_scope import compile_ignore_patterns


def make_dirs(base, *names):
    for name in names:
        (base / name).mkdir(parents=True, exist_ok=True)
    return normalize_path(str(base))


def test_scan_children_lists_folders_only_and_reports_subfolders(tmp_path):
    base = make_dirs(tmp_path, "A/A1", "B")
    (tmp_path / "file.txt").write_text("")
    assert scan_children(base, set()) == [(f"{base}/A", True), (f"{base}/B", False)]


def test_scan_children_skips_excluded_folders(tmp_path):
    base = make_dirs(tmp_path, "A", "B")
    assert scan_child_paths(base, {f"{base}/A"}) == (f"{base}/B",)


def test_scan_child_paths_skips_ignore_patterns(tmp_path):
    base = make_dirs(tmp_path, "keep", "cache_old")
    assert scan_child_paths(base, set(), compile_ignore_patterns(["*cache*"])) == (f"{base}/keep",)


def test_scan_child_paths_sorts_naturally(tmp_path):
    base = make_dirs(tmp_path, "img10", "img2", "Img1")
    assert scan_child_paths(base, set()) == (f"{base}/Img1", f"{base}/img2", f"{base}/img10")


def test_scan_children_of_a_missing_folder_is_empty():
    assert scan_children("/nonexistent/path/that/does/not/exist", set()) == []


def test_has_subfolders_ignores_hidden_children(tmp_path):
    base = make_dirs(tmp_path, "cache", "only/x")
    assert has_subfolders(base, {f"{base}/only"}, compile_ignore_patterns(["*cache*"])) is False
    assert has_subfolders(f"{base}/only", set()) is True
    assert has_subfolders(f"{base}/only/x", set()) is False
    assert has_subfolders("/nonexistent/path", set()) is False


def test_visible_roots_dedupes_hides_and_sorts_naturally(tmp_path):
    base = make_dirs(tmp_path, "r10", "r2/sub", "skip", "cache")
    roots = [f"{base}/r10", f"{base}/r2", f"{base}/r10", f"{base}/skip", f"{base}/cache"]
    pattern = compile_ignore_patterns(["*cache*"])
    assert visible_roots(roots, {f"{base}/skip"}, pattern) == (f"{base}/r2", f"{base}/r10")
    assert scan_roots(roots, {f"{base}/skip"}, pattern) == [(f"{base}/r2", True), (f"{base}/r10", False)]

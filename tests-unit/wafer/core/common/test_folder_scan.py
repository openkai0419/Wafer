import os
import sys

import pytest

from wafer.core.common import folder_scan
from wafer.core.common.folder_scan import JunctionFilter, has_subfolders, scan_child_paths, scan_children, scan_roots, visible_roots
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


windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows junctions")


def make_junction(link, target):
    import _winapi

    _winapi.CreateJunction(str(target), str(link))


def junction_entry(folder, name):
    return next(entry for entry in os.scandir(folder) if entry.name == name)


@windows_only
def test_a_junction_to_a_folder_outside_the_roots_is_listed_like_a_folder(tmp_path):
    base = make_dirs(tmp_path, "root", "outside/inner")
    make_junction(tmp_path / "root" / "linked", tmp_path / "outside")
    roots = [f"{base}/root"]
    assert scan_children(f"{base}/root", set(), roots=roots) == [(f"{base}/root/linked", True)]
    assert has_subfolders(f"{base}/root", set(), roots=roots) is True
    assert scan_roots(roots, set()) == [(f"{base}/root", True)]


@windows_only
def test_a_junction_to_its_own_folder_or_an_ancestor_is_skipped(tmp_path):
    base = make_dirs(tmp_path, "root/sub")
    make_junction(tmp_path / "root" / "self", tmp_path / "root")
    make_junction(tmp_path / "root" / "sub" / "up", tmp_path)
    assert scan_child_paths(f"{base}/root", set()) == (f"{base}/root/sub",)
    assert has_subfolders(f"{base}/root/sub", set()) is False


@windows_only
def test_a_junction_into_a_root_is_skipped_because_the_root_shows_it(tmp_path):
    base = make_dirs(tmp_path, "first", "second/inner")
    make_junction(tmp_path / "first" / "to_second", tmp_path / "second" / "inner")
    roots = [f"{base}/first", f"{base}/second"]
    assert scan_child_paths(f"{base}/first", set(), roots=roots) == ()
    assert scan_roots(roots, set()) == [(f"{base}/first", False), (f"{base}/second", True)]
    assert scan_child_paths(f"{base}/first", set()) == (f"{base}/first/to_second",)


@windows_only
def test_junctions_that_point_at_each_other_stop_at_the_second_visit(tmp_path):
    base = make_dirs(tmp_path, "root", "x", "z")
    make_junction(tmp_path / "root" / "j", tmp_path / "x")
    make_junction(tmp_path / "x" / "to_z", tmp_path / "z")
    make_junction(tmp_path / "z" / "to_x", tmp_path / "x")
    roots = [f"{base}/root"]
    assert scan_child_paths(f"{base}/root/j", set(), roots=roots) == (f"{base}/root/j/to_z",)
    assert scan_child_paths(f"{base}/root/j/to_z", set(), roots=roots) == ()


@windows_only
def test_a_junction_filter_resolves_paths_only_for_junctions(tmp_path, monkeypatch):
    make_dirs(tmp_path, "root/plain", "outside")
    make_junction(tmp_path / "root" / "linked", tmp_path / "outside")
    resolved = []
    real_realpath = os.path.realpath
    monkeypatch.setattr(folder_scan.os.path, "realpath", lambda path: resolved.append(path) or real_realpath(path))
    junctions = JunctionFilter([str(tmp_path / "root")])

    assert junctions.skips(junction_entry(tmp_path / "root", "plain")) is False
    assert resolved == []
    assert junctions.skips(junction_entry(tmp_path / "root", "linked")) is False
    assert resolved

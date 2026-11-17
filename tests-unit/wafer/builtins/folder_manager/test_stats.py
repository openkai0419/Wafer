import os
import re
import shutil

import pytest

from wafer.app.viewer.widgets.foldertree import _scan_child_paths
from wafer.builtins.folder_manager.stats import (
    DiskTree,
    FolderValues,
    count_sources_by_folder,
    list_folder,
    walk_disk,
)
from wafer.core.common.paths import normalize_path


class FakeCancel:
    def __init__(self):
        self.cancelled = False

    def is_cancelled(self):
        return self.cancelled


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def build_tree(tmp_path):
    root = tmp_path / "root"
    touch(root / "1.txt")
    touch(root / "a" / "2.txt")
    touch(root / "a" / "b" / "3.txt")
    (root / "c").mkdir()
    return normalize_path(str(root))


def scan(root):
    tree = DiskTree([root])
    walk_disk([root], set(), None, FakeCancel(), lambda batch: [tree.add(*item) for item in batch])
    return tree


def test_list_folder_counts_files_and_child_folders(tmp_path):
    touch(tmp_path / "a" / "1.txt")
    touch(tmp_path / "a" / "2.png")
    (tmp_path / "a" / "b").mkdir()
    a = normalize_path(str(tmp_path / "a"))
    assert list_folder(a, set(), None) == ([f"{a}/b"], 2)


def test_list_folder_skips_excluded_and_ignored(tmp_path):
    for name in ("keep", "skip", ".thumbs"):
        (tmp_path / name).mkdir()
    base = normalize_path(str(tmp_path))
    dirs, files = list_folder(base, {f"{base}/skip"}, re.compile(r".*/\.[^/]*$"))
    assert dirs == [f"{base}/keep"]
    assert files == 0


def test_unreadable_folder_counts_as_empty(tmp_path, monkeypatch):
    root = build_tree(tmp_path)
    real_scandir = os.scandir

    def deny(path):
        if normalize_path(str(path)) == f"{root}/a":
            raise PermissionError(path)
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", deny)
    assert list_folder(f"{root}/a", set(), None) == ([], 0)
    tree = scan(root)
    tree.finish()
    assert tree.values(f"{root}/a") == FolderValues(files=0, all_files=0, folders=0, all_folders=0)
    assert tree.values(root) == FolderValues(files=1, all_files=1, folders=2, all_folders=2)


def test_tree_totals_roll_up_after_finish(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    assert tree.finished
    assert tree.values(root) == FolderValues(files=1, all_files=3, folders=2, all_folders=3)
    assert tree.values(f"{root}/a") == FolderValues(files=1, all_files=2, folders=1, all_folders=1)
    assert tree.values(f"{root}/nope") is None


def test_totals_are_unknown_until_finish(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    assert not tree.finished
    assert tree.values(root).all_files == -1
    assert tree.values(root).all_folders == -1


def test_direct_folder_count_is_exact_before_children_are_walked():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", ["D:/x/sub", "D:/x/other"], 3)
    assert tree.values("D:/x") == FolderValues(files=3, all_files=-1, folders=2, all_folders=-1)
    tree.add("D:/x/sub", [], 0)
    tree.add("D:/x/other", [], 0)
    tree.finish()
    assert tree.values("D:/x") == FolderValues(files=3, all_files=3, folders=2, all_folders=2)


def walk_entries(paths):
    entries = []
    walk_disk(paths, set(), None, FakeCancel(), entries.extend)
    return entries


def walked_tree(paths):
    walked = DiskTree(paths)
    for entry in walk_entries(paths):
        walked.add(*entry)
    walked.finish()
    return walked


def fresh_totals(tree):
    fresh = DiskTree(tree.roots)
    for path, (child_dirs, file_count) in tree.nodes.items():
        fresh.add(path, child_dirs, file_count)
    fresh.finish()
    return fresh.totals


def test_update_folder_pushes_the_difference_up(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    touch(tmp_path / "root" / "a" / "b" / "4.txt")
    touch(tmp_path / "root" / "a" / "b" / "5.txt")
    tree.update_folder(f"{root}/a/b", *list_folder(f"{root}/a/b", set(), None))
    assert tree.finished
    assert tree.values(root) == FolderValues(files=1, all_files=5, folders=2, all_folders=3)
    assert tree.values(f"{root}/a") == FolderValues(files=1, all_files=4, folders=1, all_folders=1)
    assert tree.totals == fresh_totals(tree)


def test_update_folder_forgets_removed_child_folders(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    tree.update_folder(f"{root}/a", [], 1)
    assert tree.values(root) == FolderValues(files=1, all_files=2, folders=2, all_folders=2)
    assert tree.orphans == [f"{root}/a/b"]
    assert not tree.dispose()
    assert tree.values(f"{root}/a/b") is None
    assert tree.totals == fresh_totals(tree)


def test_removed_subtrees_are_disposed_in_batches():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", ["D:/x/big"], 0)
    tree.add("D:/x/big", [f"D:/x/big/{n}" for n in range(5)], 1)
    for n in range(5):
        tree.add(f"D:/x/big/{n}", [], 1)
    tree.finish()
    tree.update_folder("D:/x", [], 0)
    assert tree.values("D:/x") == FolderValues(files=0, all_files=0, folders=0, all_folders=0)
    assert tree.dispose(budget=2)
    assert tree.dispose(budget=2)
    assert not tree.dispose(budget=2)
    assert set(tree.nodes) == set(tree.totals) == {"D:/x"}
    assert tree.orphan_roots == set()


def test_a_folder_that_comes_back_before_disposal_is_not_lost():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", ["D:/x/a"], 0)
    tree.add("D:/x/a", ["D:/x/a/old"], 1)
    tree.add("D:/x/a/old", [], 1)
    tree.finish()
    tree.update_folder("D:/x", [], 0)
    tree.update_folder("D:/x", ["D:/x/a"], 0)
    assert "D:/x/a" not in tree.nodes and tree.orphans == []
    back = DiskTree(["D:/x/a"])
    back.add("D:/x/a", [], 4)
    back.finish()
    tree.merge(back)
    assert tree.values("D:/x") == FolderValues(files=0, all_files=4, folders=1, all_folders=1)
    assert tree.totals == fresh_totals(tree)


def test_merging_inside_a_pending_orphan_disposes_it_first():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", ["D:/x/a"], 0)
    tree.add("D:/x/a", ["D:/x/a/b"], 0)
    tree.add("D:/x/a/b", [], 2)
    tree.finish()
    tree.update_folder("D:/x", [], 0)
    walked = DiskTree(["D:/x/a/b"])
    walked.add("D:/x/a/b", [], 5)
    walked.finish()
    tree.merge(walked)
    assert tree.orphans == []
    assert tree.dispose() is False
    assert tree.values("D:/x/a/b").files == 5


def test_update_folder_counts_a_new_child_once_it_is_walked(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    touch(tmp_path / "root" / "c" / "new" / "deep" / "6.txt")
    tree.update_folder(f"{root}/c", *list_folder(f"{root}/c", set(), None))
    assert tree.values(f"{root}/c") == FolderValues(files=0, all_files=0, folders=1, all_folders=0)
    tree.merge(walked_tree([f"{root}/c/new"]))
    assert tree.finished
    assert tree.values(root) == FolderValues(files=1, all_files=4, folders=2, all_folders=5)
    assert tree.totals == fresh_totals(tree)


def test_merge_swaps_a_walked_subtree(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    shutil.rmtree(tmp_path / "root" / "a" / "b")
    touch(tmp_path / "root" / "a" / "x" / "y" / "7.txt")
    touch(tmp_path / "root" / "c" / "8.txt")
    tree.merge(walked_tree([f"{root}/a", f"{root}/c"]))
    assert tree.finished
    assert tree.values(f"{root}/a/b") is None
    assert tree.values(f"{root}/a") == FolderValues(files=1, all_files=2, folders=1, all_folders=2)
    assert tree.values(root) == FolderValues(files=1, all_files=4, folders=2, all_folders=4)
    assert tree.totals == fresh_totals(tree)


def test_incremental_updates_before_finish_only_store_listings():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", ["D:/x/sub"], 0)
    tree.update_folder("D:/x", [], 2)
    other = DiskTree(["D:/x/other"])
    other.add("D:/x/other", [], 1)
    other.finish()
    tree.merge(other)
    assert not tree.finished
    assert tree.values("D:/x") == FolderValues(files=2, all_files=-1, folders=0, all_folders=-1)


def test_drive_root_updates_stop_at_the_root():
    tree = DiskTree(["D:/"])
    tree.add("D:/", ["D:/a"], 1)
    tree.add("D:/a", [], 1)
    tree.finish()
    tree.update_folder("D:/a", [], 3)
    assert tree.values("D:/") == FolderValues(files=1, all_files=4, folders=1, all_folders=1)


def test_walk_batches_and_stops_when_cancelled(tmp_path):
    root = tmp_path / "root"
    for i in range(4):
        (root / f"d{i}").mkdir(parents=True)
    base = normalize_path(str(root))
    cancel = FakeCancel()
    calls = []

    def on_batch(batch):
        calls.append(batch)
        if len(calls) == 1:
            cancel.cancelled = True

    walk_disk([base], set(), None, cancel, on_batch, batch_size=2)
    assert len(calls) == 1
    assert len(calls[0]) == 2

    calls.clear()
    walk_disk([base], set(), None, FakeCancel(), on_batch, batch_size=2)
    assert sum(len(b) for b in calls) == 5
    assert len(calls) == 3


def test_count_sources_by_folder_rolls_up_by_path():
    result = count_sources_by_folder(["C:/r/a/1.png", "C:/r/a/b/2.png"], ["C:/r"])
    assert result == {"C:/r/a/b": (1, 1), "C:/r/a": (1, 2), "C:/r": (0, 2)}


def test_count_sources_under_a_drive_root():
    result = count_sources_by_folder(["D:/1.png", "D:/a/2.png"], ["D:/"])
    assert result == {"D:/": (1, 2), "D:/a": (1, 1)}


CWD_ROOT = os.path.splitdrive(os.getcwd())[0] + "/"


def test_count_sources_under_the_current_drive_root():
    result = count_sources_by_folder([f"{CWD_ROOT}1.png", f"{CWD_ROOT}a/2.png", f"{CWD_ROOT}a/b/3.png"], [CWD_ROOT])
    assert result == {CWD_ROOT: (1, 3), f"{CWD_ROOT}a": (1, 2), f"{CWD_ROOT}a/b": (1, 1)}


def test_updates_reach_the_current_drive_root():
    tree = DiskTree([CWD_ROOT])
    tree.add(CWD_ROOT, [f"{CWD_ROOT}a"], 1)
    tree.add(f"{CWD_ROOT}a", [], 1)
    tree.finish()
    tree.update_folder(f"{CWD_ROOT}a", [], 3)
    assert tree.values(CWD_ROOT) == FolderValues(files=1, all_files=4, folders=1, all_folders=1)
    assert tree.totals == fresh_totals(tree)


def test_counting_stops_when_cancelled(monkeypatch):
    from wafer.builtins.folder_manager import stats as stats_module

    monkeypatch.setattr(stats_module, "CANCEL_CHECK_EVERY", 2)
    sources = [f"C:/r/{n}/x.png" for n in range(10)]
    cancel = FakeCancel()
    checks = []

    def is_cancelled():
        checks.append(1)
        return len(checks) > 2

    cancel.is_cancelled = is_cancelled
    assert count_sources_by_folder(sources, ["C:/r"], cancel) == {}
    assert len(checks) == 3
    assert count_sources_by_folder(sources, ["C:/r"], FakeCancel())["C:/r"] == (0, 10)


def test_clear_releases_every_folder():
    tree = DiskTree(["D:/x"])
    tree.add("D:/x", [], 1)
    tree.finish()
    tree.clear()
    assert tree.nodes == {} and tree.totals == {}


def test_sources_outside_roots_are_ignored():
    assert count_sources_by_folder(["D:/x/1.png"], ["C:/r"]) == {}


def test_nested_roots_use_the_longest_and_siblings_do_not_match():
    result = count_sources_by_folder(["C:/r/a/1.png", "C:/rr/2.png"], ["C:/r", "C:/r/a"])
    assert result == {"C:/r/a": (1, 1)}


def test_list_folder_matches_foldertree_rules(tmp_path):
    for name in ("keep", "skip", ".thumbs", "tmp_x", "z"):
        (tmp_path / name / "inner").mkdir(parents=True)
    base = normalize_path(str(tmp_path))
    excluded = {f"{base}/skip"}
    pattern = re.compile(r".*/tmp_[^/]*$")
    for ignore in (None, pattern):
        mine = sorted(list_folder(base, excluded, ignore)[0])
        assert mine == sorted(_scan_child_paths(base, excluded, ignore))
    assert f"{base}/tmp_x" not in list_folder(base, excluded, pattern)[0]


def test_ignore_pattern_matches_the_full_path_not_the_name(tmp_path):
    (tmp_path / "plain").mkdir()
    base = normalize_path(str(tmp_path))
    assert list_folder(base, set(), re.compile(r"plain"))[0] == [f"{base}/plain"]
    assert list_folder(base, set(), re.compile(r".*/plain$"))[0] == []


def test_excluded_or_ignored_roots_are_not_walked(tmp_path):
    for name in ("x", "y", "z"):
        (tmp_path / name / "sub").mkdir(parents=True)
    base = normalize_path(str(tmp_path))
    roots = [f"{base}/x", f"{base}/y", f"{base}/z"]
    seen = []
    walk_disk(roots, {f"{base}/x"}, re.compile(r".*/y$"), FakeCancel(), lambda batch: seen.extend(p for p, _, _ in batch))
    assert seen == [f"{base}/z", f"{base}/z/sub"]


def test_directory_links_are_not_followed(tmp_path):
    target = tmp_path / "target"
    (target / "inner").mkdir(parents=True)
    root = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(target, root / "link", target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks unavailable")
    base = normalize_path(str(root))
    assert list_folder(base, set(), None) == ([], 1)
    assert list_folder(base, set(), None)[0] == list(_scan_child_paths(base, set()))

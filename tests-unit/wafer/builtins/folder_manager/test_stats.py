import os
import re

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


def test_drop_subtree_removes_folder_and_descendants(tmp_path):
    root = build_tree(tmp_path)
    tree = scan(root)
    tree.finish()
    tree.drop_subtree(f"{root}/a")
    tree.finish()
    assert tree.values(f"{root}/a") is None
    assert tree.values(f"{root}/a/b") is None
    assert tree.values(root) == FolderValues(files=1, all_files=1, folders=1, all_folders=1)


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

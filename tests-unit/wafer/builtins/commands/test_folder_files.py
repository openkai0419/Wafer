import os
import subprocess

import pytest

from wafer.builtins.commands import folder_files as folder_files_module
from wafer.builtins.commands.folder_files import disk_files, narrows, query_folder_sources, query_sources
from wafer.builtins.filters import DirectoryFilter, TextFilter
from wafer.core.common.virtual_paths import build_virtual_path
from wafer.core.db.file_db import FileDB


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "folders.db")
    file_db = FileDB(db_path)
    file_db.start()
    file_db.initialize_database()
    zip_path = "C:/lib/pack.zip"
    plain = ["C:/lib/a.png", "C:/lib/sub/b.png", "C:/lib/sub/deep/c.png", "C:/other/d.png", "C:/root.png"]
    members = [build_virtual_path(zip_path, "x/1.png"), build_virtual_path(zip_path, "2.png")]
    sources = [(p, f"hash_{i}", 100, 1.0) for i, p in enumerate([*plain, zip_path])]
    images = [(p, p, p.rsplit("/", 1)[1], 1.0, None) for p in [*plain, zip_path]]
    images += [(m, zip_path, m.rsplit("/", 1)[1], 1.0, "zip") for m in members]
    metas = [(p, "Comment", "cat", None) for p in ("C:/lib/a.png", "C:/lib/sub/deep/c.png")]
    file_db.upsert_basic_sources(sources, images, metas)
    file_db.conn.execute("ANALYZE")
    file_db.conn.commit()
    file_db.close()
    return db_path


def cat_entries():
    return [(TextFilter, {"keys": ["Comment"], "keywords": "cat"}, None)]


def test_query_direct_sources_are_only_the_folder_itself(db):
    assert query_folder_sources(db, ["C:/lib"], False, cat_entries()) == ["C:/lib/a.png"]


def test_query_recursive_sources_include_every_subfolder(db):
    assert sorted(query_folder_sources(db, ["C:/lib"], True, cat_entries())) == ["C:/lib/a.png", "C:/lib/sub/deep/c.png"]


def test_query_sources_of_several_folders_are_combined_without_duplicates(db):
    assert query_folder_sources(db, ["C:/lib/sub", "C:/lib/sub/deep"], True, cat_entries()) == ["C:/lib/sub/deep/c.png"]


def test_query_sources_of_nested_direct_folders_keep_each_folder(db):
    assert sorted(query_folder_sources(db, ["C:/lib", "C:/lib/sub/deep"], False, cat_entries())) == ["C:/lib/a.png", "C:/lib/sub/deep/c.png"]


def test_virtual_paths_count_as_their_source(db):
    assert query_sources(db, []).count("C:/lib/pack.zip") == 1


def text_entry(keywords, keys=("path",), op=None):
    return (TextFilter, {"keys": list(keys) if keys is not None else None, "keywords": keywords}, op)


def test_only_entries_that_filter_count_as_a_query():
    assert not narrows([])
    assert not narrows([text_entry("")])
    assert not narrows([text_entry(""), text_entry("  ", op="AND")])
    assert narrows([text_entry("cat", ["Comment"])])
    assert narrows([text_entry(""), text_entry("cat", ["Comment"], op="AND")])
    assert narrows([text_entry("", ["Comment"])])
    assert narrows([text_entry("", None)])
    assert narrows([(DirectoryFilter, {"directories": ["C:/lib"]}, None)])


def test_post_filters_count_as_a_query():
    class PostOnly(TextFilter):
        NAME = ""

        @classmethod
        def build_path_query(cls, params, normalize_path):
            return None, []

        @classmethod
        def post_filter(cls, params, rows):
            return rows

    assert narrows([(PostOnly, {}, None)])


def test_without_a_query_sources_come_from_the_sources_table(db, monkeypatch):
    expected_all = sorted(folder_files_module.composed_sources(db, []))
    monkeypatch.setattr(folder_files_module, "composed_sources", lambda *args: pytest.fail("composer used without a query"))
    assert sorted(query_sources(db, [text_entry("")])) == expected_all


def test_a_missing_database_has_no_sources(tmp_path):
    assert query_sources(str(tmp_path / "missing.db"), []) == []


def write_files(root, *names):
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    return root


def norm(*paths):
    return sorted(os.path.abspath(str(path)).replace("\\", "/") for path in paths)


def test_disk_files_of_a_folder_are_its_direct_files_only(tmp_path):
    root = write_files(tmp_path / "root", "a.png", "notes.txt", "sub/b.png")
    assert sorted(disk_files([str(root)], recursive=False)) == norm(root / "a.png", root / "notes.txt")


def test_disk_files_below_include_every_nested_file_and_no_folders(tmp_path):
    root = write_files(tmp_path / "root", "a.png", "sub/b.png", "sub/deep/c.txt", "excluded/d.png", "#ignored/e.png")
    (root / "empty").mkdir()
    assert sorted(disk_files([str(root)], recursive=True)) == norm(
        root / "a.png", root / "sub/b.png", root / "sub/deep/c.txt", root / "excluded/d.png", root / "#ignored/e.png"
    )


def test_disk_files_of_overlapping_folders_have_no_duplicates(tmp_path):
    root = write_files(tmp_path / "root", "a.png", "sub/b.png")
    assert sorted(disk_files([str(root), str(root / "sub")], recursive=True)) == norm(root / "a.png", root / "sub/b.png")
    assert sorted(disk_files([str(root), str(root / "sub")], recursive=False)) == norm(root / "a.png", root / "sub/b.png")


def make_junction(link, target):
    subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], check=True, capture_output=True)


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_disk_files_do_not_follow_junctions(tmp_path):
    outside = write_files(tmp_path / "outside", "secret.png")
    root = write_files(tmp_path / "root", "a.png")
    make_junction(root / "junction", outside)
    assert sorted(disk_files([str(root)], recursive=True)) == norm(root / "a.png")


def test_disk_files_do_not_follow_folder_symlinks_but_keep_file_symlinks(tmp_path):
    outside = write_files(tmp_path / "outside", "secret.png")
    root = write_files(tmp_path / "root", "a.png")
    try:
        os.symlink(outside, root / "folder_link", target_is_directory=True)
        os.symlink(outside / "secret.png", root / "file_link.png")
    except OSError as exc:
        pytest.skip(f"symlinks need privileges here: {exc}")
    assert sorted(disk_files([str(root)], recursive=True)) == norm(root / "a.png", root / "file_link.png")


def test_disk_files_skip_an_unreadable_folder_and_log_it(tmp_path, monkeypatch):
    root = write_files(tmp_path / "root", "a.png", "locked/b.png", "open/c.png")
    locked = os.path.abspath(str(root / "locked")).replace("\\", "/")
    real_scandir = os.scandir
    warnings = []

    def scandir(path):
        if os.path.abspath(path).replace("\\", "/") == locked:
            raise PermissionError(13, "Access is denied", path)
        return real_scandir(path)

    monkeypatch.setattr(folder_files_module.os, "scandir", scandir)
    monkeypatch.setattr(folder_files_module.AppLogger, "warning", warnings.append)

    assert sorted(disk_files([str(root)], recursive=True)) == norm(root / "a.png", root / "open/c.png")
    assert len(warnings) == 1 and locked in warnings[0]


def test_disk_files_of_a_missing_folder_are_empty_and_logged(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(folder_files_module.AppLogger, "warning", warnings.append)
    assert disk_files([str(tmp_path / "gone")], recursive=True) == []
    assert len(warnings) == 1 and "no longer exists" in warnings[0]


def test_disk_files_skip_a_broken_folder_symlink(tmp_path):
    root = write_files(tmp_path / "root", "a.png")
    gone = tmp_path / "gone"
    gone.mkdir()
    try:
        os.symlink(gone, root / "broken_link", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks need privileges here: {exc}")
    gone.rmdir()
    assert sorted(disk_files([str(root)], recursive=True)) == norm(root / "a.png")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows feature")
def test_disk_files_skip_a_broken_junction(tmp_path):
    root = write_files(tmp_path / "root", "a.png")
    gone = tmp_path / "gone"
    gone.mkdir()
    make_junction(root / "junction", gone)
    gone.rmdir()
    assert sorted(disk_files([str(root)], recursive=True)) == norm(root / "a.png")


class CancelAfter:
    def __init__(self, checks):
        self.checks = checks

    def is_cancelled(self):
        self.checks -= 1
        return self.checks < 0


def test_a_cancelled_disk_walk_stops_and_returns_nothing(tmp_path, monkeypatch):
    root = write_files(tmp_path / "root", "a.png", *(f"sub{n}/b.png" for n in range(5)))
    listed = []
    real_scandir = os.scandir
    monkeypatch.setattr(folder_files_module.os, "scandir", lambda path: listed.append(path) or real_scandir(path))

    assert disk_files([str(root)], recursive=True, cancel=CancelAfter(1)) == []
    assert len(listed) == 1
    assert len(disk_files([str(root)], recursive=True, cancel=CancelAfter(100))) == 6

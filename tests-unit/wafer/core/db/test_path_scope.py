import os

import pytest

from wafer.core.db import path_scope
from wafer.core.db.path_scope import compile_ignore_patterns, databases_containing, is_under, path_in_scope
from wafer.core.db.setting_db import SettingDB


def test_same_path_and_child_are_inside():
    assert is_under("F:/photos", "F:/photos")
    assert is_under("F:/photos/a/b.png", "F:/photos")


def test_sibling_prefix_is_not_inside():
    assert not is_under("F:/photos2/a.png", "F:/photos")


def test_parent_is_not_inside():
    assert not is_under("F:/", "F:/photos")


def test_backslashes_are_normalized():
    assert is_under("F:\\photos\\a.png", "F:/photos")


@pytest.mark.skipif(os.name != "nt", reason="case-insensitive on Windows")
def test_case_is_ignored_on_windows():
    assert is_under("f:/Photos/a.png", "F:/photos")


def test_path_in_scope_under_root():
    assert path_in_scope("F:/p/a.png", ["F:/p"], [], [])
    assert not path_in_scope("F:/q/a.png", ["F:/p"], [], [])


def test_any_root_is_enough():
    assert path_in_scope("F:/q/a.png", ["F:/p", "F:/q"], [], [])


def test_no_roots_is_never_in_scope():
    assert not path_in_scope("F:/p/a.png", [], [], [])


def test_ignore_folder_excludes():
    assert not path_in_scope("F:/p/skip/a.png", ["F:/p"], ["F:/p/skip"], [])
    assert path_in_scope("F:/p/skipped/a.png", ["F:/p"], ["F:/p/skip"], [])


def test_ignore_pattern_excludes():
    assert not path_in_scope("F:/p/a.tmp", ["F:/p"], [], ["*.tmp"])
    assert path_in_scope("F:/p/a.png", ["F:/p"], [], ["*.tmp"])


def test_compile_ignore_patterns_empty_returns_none():
    assert compile_ignore_patterns([]) is None


def make_setting_db(tmp_path, name, roots, ignore_folders=(), ignore_patterns=()):
    db = SettingDB(str(tmp_path / f"{name}.db"))
    db.sync_parent_folders(roots)
    db.sync_ignore_folders(ignore_folders)
    db.sync_ignore_patterns(ignore_patterns)


@pytest.fixture
def setting_dbs(tmp_path, monkeypatch):
    names = []
    monkeypatch.setattr(path_scope, "list_setting_db_names", lambda: list(names))
    monkeypatch.setattr(path_scope, "setting_db_path", lambda name: str(tmp_path / f"{name}.db"))

    def register(name, *args, **kwargs):
        make_setting_db(tmp_path, name, *args, **kwargs)
        names.append(name)

    return register


def test_databases_containing_lists_matching_dbs_only(setting_dbs):
    setting_dbs("a", ["F:/p"])
    setting_dbs("b", ["F:/p"], ignore_folders=["F:/p/skip"])
    assert databases_containing("F:/p/skip/x.png") == ["a"]


def test_databases_containing_keeps_listing_order(setting_dbs):
    setting_dbs("z", ["F:/p"])
    setting_dbs("a", ["F:/p"])
    setting_dbs("m", ["F:/other"])
    assert databases_containing("F:/p/x.png") == ["z", "a"]


def test_databases_containing_respects_ignore_patterns(setting_dbs):
    setting_dbs("a", ["F:/p"], ignore_patterns=["*.tmp"])
    setting_dbs("b", ["F:/p"])
    assert databases_containing("F:/p/x.tmp") == ["b"]


def test_databases_containing_without_databases_is_empty(setting_dbs):
    assert databases_containing("F:/p/x.png") == []

from wafer.builtins.folder_manager import database
from wafer.builtins.folder_manager.database import initial_database, read_folder_settings
from wafer.core.common.paths import normalize_path
from wafer.core.db.setting_db import SettingDB


def test_read_folder_settings_normalises_roots_and_compiles_patterns(tmp_path, monkeypatch):
    db_file = tmp_path / "main.db"
    monkeypatch.setattr(database, "setting_db_path", lambda name: str(db_file))
    setting = SettingDB(str(db_file))
    root = str(tmp_path / "root")
    skipped = str(tmp_path / "root" / "skip")
    setting.add_parent_folder(root)
    setting.add_ignore_folder(skipped)
    setting.add_ignore_pattern("*.tmp")

    result = read_folder_settings("main")

    assert result.roots == [normalize_path(root)]
    assert result.excluded == {normalize_path(skipped)}
    assert result.ignore_pattern_re is not None
    assert result.ignore_pattern_re.match("a.tmp")
    assert not result.ignore_pattern_re.match("a.png")


def test_database_without_folder_settings_gives_no_roots(tmp_path, monkeypatch):
    db_file = tmp_path / "missing.db"
    monkeypatch.setattr(database, "setting_db_path", lambda name: str(db_file))

    result = read_folder_settings("missing")

    assert result.roots == []
    assert result.excluded == set()
    assert result.ignore_pattern_re is None
    assert not db_file.exists()


def test_initial_database_prefers_the_host_then_the_last_choice():
    names = ["a", "b", "c"]
    assert initial_database("c", "b", names) == "c"
    assert initial_database(None, "b", names) == "b"
    assert initial_database("zz", "", names) == "a"


def test_initial_database_skips_names_that_no_longer_exist():
    assert initial_database("gone", "also_gone", ["x", "y"]) == "x"
    assert initial_database("gone", "x", ["x", "y"]) == "x"
    assert initial_database(None, "", []) == ""

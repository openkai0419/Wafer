import pytest

from extensions.exiftool.settings import exiftool_config, migrate_legacy_filter, MODE_BLACKLIST, MODE_WHITELIST
from wafer.plugin.key_filter import KeyFilter


@pytest.fixture(autouse=True)
def _isolate_ini(tmp_path, monkeypatch):
    ini = tmp_path / "viewer_plugins.ini"
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(ini))
    monkeypatch.setattr(KeyFilter, "_broadcast_reload", staticmethod(lambda: None))
    exiftool_config._cache = {}
    KeyFilter._cache = None
    yield
    KeyFilter._cache = None


class TestMigration:
    def test_no_legacy_config_marks_migrated(self):
        migrate_legacy_filter()
        assert exiftool_config.load().get("migrated") is True
        assert KeyFilter.get("exiftool") == (MODE_BLACKLIST, frozenset())

    def test_migrates_blacklist_keys(self):
        exiftool_config.save(filter_mode=MODE_BLACKLIST, filter_keys=["IFD0:Make", "File:FileType"])
        exiftool_config._cache = {}
        migrate_legacy_filter()
        mode, keys = KeyFilter.get("exiftool")
        assert mode == MODE_BLACKLIST
        assert keys == frozenset({"IFD0:Make", "File:FileType"})

    def test_migrates_whitelist_keys(self):
        exiftool_config.save(filter_mode=MODE_WHITELIST, filter_keys=["IFD0:Model"])
        exiftool_config._cache = {}
        migrate_legacy_filter()
        mode, keys = KeyFilter.get("exiftool")
        assert mode == MODE_WHITELIST
        assert keys == frozenset({"IFD0:Model"})

    def test_migration_runs_once(self):
        exiftool_config.save(filter_mode=MODE_BLACKLIST, filter_keys=["A"])
        exiftool_config._cache = {}
        migrate_legacy_filter()
        KeyFilter.set_keys("exiftool", MODE_BLACKLIST, {"B"})
        migrate_legacy_filter()
        assert KeyFilter.get("exiftool")[1] == frozenset({"B"})

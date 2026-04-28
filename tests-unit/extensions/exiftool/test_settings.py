import pytest

from extensions.exiftool.settings import (
    exiftool_config,
    read_filter_config,
    write_filter_config,
    read_sort_config,
    write_sort_config,
    MODE_BLACKLIST,
    MODE_WHITELIST,
    SORT_NAME,
    SORT_COUNT,
)


@pytest.fixture(autouse=True)
def _isolate_ini(tmp_path, monkeypatch):
    ini = tmp_path / "viewer_plugins.ini"
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(ini))
    exiftool_config._cache = {}


class TestFilterConfig:
    def test_returns_default_when_no_file(self):
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()

    def test_roundtrip_blacklist(self):
        write_filter_config(MODE_BLACKLIST, {"IFD0:Make", "File:FileType"})
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"IFD0:Make", "File:FileType"}

    def test_roundtrip_whitelist(self):
        write_filter_config(MODE_WHITELIST, {"IFD0:Make", "IFD0:Model"})
        mode, keys = read_filter_config()
        assert mode == MODE_WHITELIST
        assert keys == {"IFD0:Make", "IFD0:Model"}

    def test_invalid_mode_falls_back_to_blacklist(self):
        exiftool_config.save(filter_mode="bogus", filter_keys=["X"])
        exiftool_config._cache = {}
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"X"}


class TestSortConfig:
    def test_default_sort_config(self):
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is False

    def test_roundtrip_name_ascending(self):
        write_sort_config(SORT_NAME, True)
        mode, ascending = read_sort_config()
        assert mode == SORT_NAME
        assert ascending is True

    def test_roundtrip_count_descending(self):
        write_sort_config(SORT_COUNT, False)
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is False

    def test_invalid_sort_mode_falls_back_to_count(self):
        exiftool_config.save(sort_mode=99, sort_ascending=True)
        exiftool_config._cache = {}
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is True

import json
import os
from configparser import ConfigParser
import pytest
import extensions.exiftool.settings as _settings
from extensions.exiftool.settings import (
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
    monkeypatch.setattr(
        "extensions.exiftool.settings._ini_path",
        lambda: str(tmp_path / "viewer_plugins.ini"),
    )


class TestReadFilterConfig:
    def test_returns_default_when_no_file(self):
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()

    def test_reads_saved_blacklist(self):
        write_filter_config(MODE_BLACKLIST, {"IFD0:Make", "File:FileType"})
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"IFD0:Make", "File:FileType"}

    def test_reads_saved_whitelist(self):
        write_filter_config(MODE_WHITELIST, {"IFD0:Make", "IFD0:Model"})
        mode, keys = read_filter_config()
        assert mode == MODE_WHITELIST
        assert keys == {"IFD0:Make", "IFD0:Model"}

    def test_returns_default_for_corrupt_json(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[exiftool]\nfilter_keys = not_json\n")
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()

    def test_migration_legacy_blacklist_key(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        legacy = json.dumps(["IFD0:Make", "IFD0:Model"])
        with open(path, "w") as f:
            f.write(f"[exiftool]\nblacklist = {legacy}\n")
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"IFD0:Make", "IFD0:Model"}


class TestWriteFilterConfig:
    def test_creates_ini_file(self):
        write_filter_config(MODE_BLACKLIST, {"IFD0:Make", "IFD0:Model"})
        path = _settings._ini_path()
        assert os.path.isfile(path)
        content = open(path, encoding="utf-8").read()
        assert "[exiftool]" in content
        assert "filter_mode" in content
        assert "filter_keys" in content

    def test_removes_legacy_blacklist_key(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        legacy = json.dumps(["OldKey"])
        with open(path, "w") as f:
            f.write(f"[exiftool]\nblacklist = {legacy}\n")
        write_filter_config(MODE_WHITELIST, {"NewKey"})
        cp = ConfigParser()
        cp.read(path, encoding="utf-8")
        assert not cp.has_option("exiftool", "blacklist")

    def test_preserves_existing_sections(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[plugins]\nenabled = [\"panel:exiftool_settings\"]\n")
        write_filter_config(MODE_BLACKLIST, {"GPS:GPSLatitude"})
        content = open(path, encoding="utf-8").read()
        assert "[plugins]" in content
        assert "[exiftool]" in content

    def test_roundtrip_blacklist(self):
        keys = {"IFD0:Make", "IFD0:Model", "GPS:GPSLatitude", "GPS:GPSLongitude", "ExifIFD:UserComment"}
        write_filter_config(MODE_BLACKLIST, keys)
        mode, result = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert result == keys


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

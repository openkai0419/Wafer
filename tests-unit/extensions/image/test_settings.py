import json
import os
from configparser import ConfigParser
import pytest
import extensions.image.settings as _settings
from extensions.image.settings import (
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
        "extensions.image.settings._ini_path",
        lambda: str(tmp_path / "viewer_plugins.ini"),
    )


class TestReadFilterConfig:
    def test_returns_default_when_no_file(self):
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()

    def test_reads_saved_blacklist(self):
        write_filter_config(MODE_BLACKLIST, {"GPS/GPSLatitude", "ExifOffset"})
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"GPS/GPSLatitude", "ExifOffset"}

    def test_reads_saved_whitelist(self):
        write_filter_config(MODE_WHITELIST, {"Make", "Model"})
        mode, keys = read_filter_config()
        assert mode == MODE_WHITELIST
        assert keys == {"Make", "Model"}

    def test_returns_default_for_corrupt_json(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[exif]\nfilter_keys = not_json\n")
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()

    def test_migration_legacy_blacklist_key(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        legacy = json.dumps(["Make", "Model"])
        with open(path, "w") as f:
            f.write(f"[exif]\nblacklist = {legacy}\n")
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == {"Make", "Model"}


class TestWriteFilterConfig:
    def test_creates_ini_file(self):
        write_filter_config(MODE_BLACKLIST, {"Make", "Model"})
        path = _settings._ini_path()
        assert os.path.isfile(path)
        content = open(path, encoding="utf-8").read()
        assert "[exif]" in content
        assert "filter_mode" in content
        assert "filter_keys" in content

    def test_removes_legacy_blacklist_key(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        legacy = json.dumps(["OldKey"])
        with open(path, "w") as f:
            f.write(f"[exif]\nblacklist = {legacy}\n")
        write_filter_config(MODE_WHITELIST, {"NewKey"})
        cp = ConfigParser()
        cp.read(path, encoding="utf-8")
        assert not cp.has_option("exif", "blacklist")

    def test_preserves_existing_sections(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[plugins]\nenabled = [\"panel:exif_settings\"]\n")
        write_filter_config(MODE_BLACKLIST, {"GPS/GPSLatitude"})
        content = open(path, encoding="utf-8").read()
        assert "[plugins]" in content
        assert "[exif]" in content

    def test_roundtrip_blacklist(self):
        keys = {"Make", "Model", "GPS/GPSLatitude", "GPS/GPSLongitude", "UserComment"}
        write_filter_config(MODE_BLACKLIST, keys)
        mode, result = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert result == keys

    def test_roundtrip_whitelist(self):
        keys = {"Make", "Model"}
        write_filter_config(MODE_WHITELIST, keys)
        mode, result = read_filter_config()
        assert mode == MODE_WHITELIST
        assert result == keys

    def test_empty_set(self):
        write_filter_config(MODE_BLACKLIST, set())
        mode, keys = read_filter_config()
        assert mode == MODE_BLACKLIST
        assert keys == set()


class TestReadSortConfig:
    def test_returns_default_when_no_file(self):
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is False

    def test_reads_saved_name_ascending(self):
        write_sort_config(SORT_NAME, True)
        mode, ascending = read_sort_config()
        assert mode == SORT_NAME
        assert ascending is True

    def test_reads_saved_count_descending(self):
        write_sort_config(SORT_COUNT, False)
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is False

    def test_unknown_mode_defaults_to_count(self):
        path = _settings._ini_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write("[exif]\nsort_mode = unknown\n")
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is False


class TestWriteSortConfig:
    def test_creates_ini_file(self):
        write_sort_config(SORT_NAME, True)
        path = _settings._ini_path()
        assert os.path.isfile(path)
        cp = ConfigParser()
        cp.read(path, encoding="utf-8")
        assert cp.get("exif", "sort_mode") == "name"
        assert cp.get("exif", "sort_ascending") == "true"

    def test_preserves_filter_config(self):
        write_filter_config(MODE_WHITELIST, {"Make", "Model"})
        write_sort_config(SORT_COUNT, False)
        mode, keys = read_filter_config()
        assert mode == MODE_WHITELIST
        assert keys == {"Make", "Model"}

    def test_roundtrip(self):
        write_sort_config(SORT_NAME, False)
        mode, ascending = read_sort_config()
        assert mode == SORT_NAME
        assert ascending is False
        write_sort_config(SORT_COUNT, True)
        mode, ascending = read_sort_config()
        assert mode == SORT_COUNT
        assert ascending is True

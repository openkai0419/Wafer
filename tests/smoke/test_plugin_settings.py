import os
from configparser import ConfigParser

from wafer.plugin.settings import PluginSettings, _write_ini_value, _read_ini_value


class TestIniReadWrite:
    def test_write_and_read_string(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "test.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        _write_ini_value("General/theme", "dark")
        assert _read_ini_value("General/theme") == "dark"

    def test_write_and_read_list(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "test.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        _write_ini_value("plugins/enabled", ["image", "video"])
        result = _read_ini_value("plugins/enabled")
        assert result == ["image", "video"]

    def test_read_missing_key_returns_default(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "test.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        assert _read_ini_value("nope/key", default="fallback") == "fallback"

    def test_read_missing_file_returns_default(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "nonexistent.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        assert _read_ini_value("section/key", default=42) == 42


class TestPluginSettings:
    def test_enabled_names_roundtrip(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "plugins.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        ps.set_enabled({"image", "video", "animated"})
        result = ps.enabled_names()
        assert result == {"image", "video", "animated"}

    def test_enabled_names_empty_file(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "empty.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        assert ps.enabled_names() is None

    def test_priority_order_roundtrip(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "priority.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        ps.set_priority_order("grid", ["image", "animated", "system_thumbnail"])
        result = ps.priority_order("grid")
        assert result == ["image", "animated", "system_thumbnail"]

    def test_priority_order_missing(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "empty.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        assert ps.priority_order("grid") == []

    def test_default_enabled_collectors_roundtrip(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "defaults.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        ps.set_default_enabled_collectors(["exif", "ffmpeg"])
        result = ps.default_enabled_collectors()
        assert result == ["exif", "ffmpeg"]

    def test_default_enabled_collectors_missing(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "empty.ini")
        monkeypatch.setattr("wafer.plugin.settings._ini_path", lambda: ini_path)

        ps = PluginSettings()
        assert ps.default_enabled_collectors() is None

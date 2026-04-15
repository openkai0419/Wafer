import os
import json
import pytest
from wafer.plugin.settings import PluginSettings, _ini_path, _write_ini_value, _read_ini_value
import wafer.plugin.settings as settings_mod


@pytest.fixture(autouse=True)
def isolate_ini(tmp_path, monkeypatch):
    ini = str(tmp_path / "viewer_plugins.ini")
    monkeypatch.setattr(settings_mod, "_ini_path", lambda: ini)
    yield ini


class TestPluginSettingsEnabledNames:
    def test_none_when_no_file(self):
        ps = PluginSettings()
        assert ps.enabled_names() is None

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_enabled({"image", "exif", "animated"})
        result = ps.enabled_names()
        assert result == {"image", "exif", "animated"}

    def test_empty_set_roundtrip(self):
        ps = PluginSettings()
        ps.set_enabled(set())
        assert ps.enabled_names() == set()

    def test_overwrite(self):
        ps = PluginSettings()
        ps.set_enabled({"image", "exif"})
        ps.set_enabled({"video"})
        assert ps.enabled_names() == {"video"}


class TestPluginSettingsPriorityOrder:
    def test_empty_when_no_file(self):
        ps = PluginSettings()
        assert ps.priority_order("viewer") == []

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_priority_order("viewer", ["animated", "video", "image"])
        assert ps.priority_order("viewer") == ["animated", "video", "image"]

    def test_preserves_order(self):
        ps = PluginSettings()
        ps.set_priority_order("viewer", ["image", "animated", "video"])
        assert ps.priority_order("viewer") == ["image", "animated", "video"]

    def test_different_keys_independent(self):
        ps = PluginSettings()
        ps.set_priority_order("viewer", ["image"])
        ps.set_priority_order("grid", ["image", "animated"])
        assert ps.priority_order("viewer") == ["image"]
        assert ps.priority_order("grid") == ["image", "animated"]

    def test_all_registry_keys(self):
        ps = PluginSettings()
        for key in ["viewer", "grid", "collector", "filter", "sort", "layout", "rename_source"]:
            ps.set_priority_order(key, [f"{key}_a", f"{key}_b"])
            assert ps.priority_order(key) == [f"{key}_a", f"{key}_b"]

    def test_backward_compat_reads_old_key(self, isolate_ini):
        _write_ini_value("plugins/viewer_order", ["old_a", "old_b"])
        ps = PluginSettings()
        assert ps.priority_order("viewer") == ["old_a", "old_b"]

    def test_new_key_takes_precedence_over_old(self, isolate_ini):
        _write_ini_value("plugins/viewer_order", ["old_a"])
        ps = PluginSettings()
        ps.set_priority_order("viewer", ["new_a", "new_b"])
        assert ps.priority_order("viewer") == ["new_a", "new_b"]


class TestRestartPending:
    def test_false_when_no_file(self):
        ps = PluginSettings()
        assert ps.is_restart_pending() is False

    def test_set_and_read(self):
        ps = PluginSettings()
        ps.set_restart_pending(True)
        assert ps.is_restart_pending() is True

    def test_clear(self):
        ps = PluginSettings()
        ps.set_restart_pending(True)
        ps.clear_restart_pending()
        assert ps.is_restart_pending() is False

    def test_set_false_explicitly(self):
        ps = PluginSettings()
        ps.set_restart_pending(True)
        ps.set_restart_pending(False)
        assert ps.is_restart_pending() is False


class TestIniLowLevel:
    def test_read_missing_key(self):
        assert _read_ini_value("nonexistent/key") is None

    def test_write_and_read_json_list(self):
        _write_ini_value("test/mylist", ["a", "b", "c"])
        assert _read_ini_value("test/mylist") == ["a", "b", "c"]

    def test_write_creates_directory(self, isolate_ini):
        assert not os.path.isfile(isolate_ini)
        _write_ini_value("section/key", "value")
        assert os.path.isfile(isolate_ini)

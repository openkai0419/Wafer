import os
import json
import pytest
from wafer.plugin.settings import PluginSettings, _ini_path, _write_ini_value, _read_ini_value
from wafer.plugin.installer import RestartScope
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


class TestRestartScope:
    def test_none_when_no_file(self):
        ps = PluginSettings()
        assert ps.restart_scope() == RestartScope.NONE

    def test_set_viewer(self):
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.VIEWER)
        assert ps.restart_scope() == RestartScope.VIEWER

    def test_set_tray(self):
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.TRAY)
        assert ps.restart_scope() == RestartScope.TRAY

    def test_set_all(self):
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.ALL)
        scope = ps.restart_scope()
        assert RestartScope.VIEWER in scope
        assert RestartScope.TRAY in scope

    def test_merge_viewer_then_tray(self):
        ps = PluginSettings()
        ps.merge_restart_scope(RestartScope.VIEWER)
        assert ps.restart_scope() == RestartScope.VIEWER
        ps.merge_restart_scope(RestartScope.TRAY)
        scope = ps.restart_scope()
        assert RestartScope.VIEWER in scope
        assert RestartScope.TRAY in scope

    def test_clear_scope(self):
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.ALL)
        ps.clear_restart_scope()
        assert ps.restart_scope() == RestartScope.NONE

    def test_backward_compat_old_restart_pending(self, isolate_ini):
        _write_ini_value("plugins/restart_pending", True)
        ps = PluginSettings()
        scope = ps.restart_scope()
        assert RestartScope.VIEWER in scope
        assert RestartScope.TRAY in scope

    def test_needs_restart_with_pending_packages(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "wafer.plugin.installer_queue.has_pending_queue", lambda d: True
        )
        ps = PluginSettings()
        scope = ps.needs_restart(str(tmp_path))
        assert RestartScope.VIEWER in scope
        assert RestartScope.TRAY in scope

    def test_needs_restart_no_pending_no_scope(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "wafer.plugin.installer_queue.has_pending_queue", lambda d: False
        )
        ps = PluginSettings()
        assert ps.needs_restart(str(tmp_path)) == RestartScope.NONE

    def test_needs_restart_viewer_scope_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "wafer.plugin.installer_queue.has_pending_queue", lambda d: False
        )
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.VIEWER)
        scope = ps.needs_restart(str(tmp_path))
        assert scope == RestartScope.VIEWER
        assert RestartScope.TRAY not in scope


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

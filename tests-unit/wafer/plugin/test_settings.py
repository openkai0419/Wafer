import os
import pytest
from wafer.plugin.settings import PluginSettings, _write_ini_value
from wafer.plugin.installer import RestartScope
from wafer.plugin.kinds import PLUGIN_KINDS
import wafer.plugin.settings as settings_mod


class DefaultEnabledPlugin:
    DEFAULT_ENABLED = True


class DefaultDisabledPlugin:
    DEFAULT_ENABLED = False


@pytest.fixture(autouse=True)
def isolate_ini(tmp_path, monkeypatch):
    ini = str(tmp_path / "viewer_plugins.ini")
    monkeypatch.setattr(settings_mod, "_ini_path", lambda: ini)
    yield ini


class TestPluginSettingsActiveFolders:
    def test_empty_when_no_file(self):
        assert PluginSettings().active_folders() == []

    def test_roundtrip_sorted_deduped(self):
        ps = PluginSettings()
        ps.set_active_folders(["video", "image", "image"])
        assert ps.active_folders() == ["image", "video"]

    def test_empty_roundtrip(self):
        ps = PluginSettings()
        ps.set_active_folders([])
        assert ps.active_folders() == []


class TestPluginSettingsEnabledOverrides:
    def test_empty_when_no_file(self):
        ps = PluginSettings()
        assert ps.enabled_overrides() == {}

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_enabled_overrides({"viewer:Video": False, "grid:Zip": True})
        assert ps.enabled_overrides() == {"viewer:Video": False, "grid:Zip": True}

    def test_missing_override_uses_default_enabled(self):
        ps = PluginSettings()
        assert ps.is_plugin_enabled("viewer:DefaultEnabledPlugin", DefaultEnabledPlugin)
        assert not ps.is_plugin_enabled("viewer:DefaultDisabledPlugin", DefaultDisabledPlugin)

    def test_override_false_disables_default_enabled(self):
        ps = PluginSettings()
        overrides = {"viewer:DefaultEnabledPlugin": False}
        assert not ps.is_plugin_enabled("viewer:DefaultEnabledPlugin", DefaultEnabledPlugin, overrides)

    def test_override_true_enables_default_disabled(self):
        ps = PluginSettings()
        overrides = {"viewer:DefaultDisabledPlugin": True}
        assert ps.is_plugin_enabled("viewer:DefaultDisabledPlugin", DefaultDisabledPlugin, overrides)

    def test_enabled_override_omits_default_matching_state(self):
        assert PluginSettings.enabled_override("viewer:DefaultEnabledPlugin", DefaultEnabledPlugin, True) is None
        assert PluginSettings.enabled_override("viewer:DefaultEnabledPlugin", DefaultEnabledPlugin, False) == (
            "viewer:DefaultEnabledPlugin",
            False,
        )


class TestPluginSettingsPriorityOrder:
    def test_empty_when_no_file(self):
        ps = PluginSettings()
        assert ps.priority_order("viewer") == []

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_priority_order("viewer", ["animated", "video", "image"])
        assert ps.priority_order("viewer") == ["animated", "video", "image"]

    def test_all_registry_keys_independent(self):
        ps = PluginSettings()
        for key in PLUGIN_KINDS:
            ps.set_priority_order(key, [f"{key}_a", f"{key}_b"])
        for key in PLUGIN_KINDS:
            assert ps.priority_order(key) == [f"{key}_a", f"{key}_b"]


class TestRestartScope:
    def test_none_when_no_file(self):
        ps = PluginSettings()
        assert ps.restart_scope() == RestartScope.NONE

    def test_set_roundtrip(self):
        ps = PluginSettings()
        for scope in (RestartScope.VIEWER, RestartScope.TRAY, RestartScope.ALL):
            ps.set_restart_scope(scope)
            assert ps.restart_scope() == scope

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

    def test_needs_restart_with_pending_packages(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wafer.plugin.installer_queue.has_pending_queue", lambda d: True)
        ps = PluginSettings()
        scope = ps.needs_restart(str(tmp_path))
        assert RestartScope.VIEWER in scope
        assert RestartScope.TRAY in scope

    def test_needs_restart_no_pending_no_scope(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wafer.plugin.installer_queue.has_pending_queue", lambda d: False)
        ps = PluginSettings()
        assert ps.needs_restart(str(tmp_path)) == RestartScope.NONE

    def test_needs_restart_viewer_scope_only(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wafer.plugin.installer_queue.has_pending_queue", lambda d: False)
        ps = PluginSettings()
        ps.set_restart_scope(RestartScope.VIEWER)
        scope = ps.needs_restart(str(tmp_path))
        assert scope == RestartScope.VIEWER
        assert RestartScope.TRAY not in scope


class TestIniLowLevel:
    def test_write_creates_directory(self, isolate_ini):
        assert not os.path.isfile(isolate_ini)
        _write_ini_value("section/key", "value")
        assert os.path.isfile(isolate_ini)

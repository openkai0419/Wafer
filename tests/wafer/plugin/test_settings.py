import os
import json
import pytest
from wafer.plugin.settings import PluginSettings, _ini_path, _write_ini_value, _read_ini_value
import wafer.plugin.settings as settings_mod


@pytest.fixture(autouse=True)
def isolate_ini(tmp_path, monkeypatch):
    ini = str(tmp_path / 'viewer_plugins.ini')
    monkeypatch.setattr(settings_mod, '_ini_path', lambda: ini)
    yield ini


class TestPluginSettingsEnabledNames:

    def test_none_when_no_file(self):
        ps = PluginSettings()
        assert ps.enabled_names() is None

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_enabled({'image', 'exif', 'animated'})
        result = ps.enabled_names()
        assert result == {'image', 'exif', 'animated'}

    def test_empty_set_roundtrip(self):
        ps = PluginSettings()
        ps.set_enabled(set())
        assert ps.enabled_names() == set()

    def test_overwrite(self):
        ps = PluginSettings()
        ps.set_enabled({'image', 'exif'})
        ps.set_enabled({'video'})
        assert ps.enabled_names() == {'video'}


class TestPluginSettingsViewerOrder:

    def test_empty_when_no_file(self):
        ps = PluginSettings()
        assert ps.viewer_order() == []

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_viewer_order(['animated', 'video', 'image'])
        assert ps.viewer_order() == ['animated', 'video', 'image']

    def test_preserves_order(self):
        ps = PluginSettings()
        ps.set_viewer_order(['image', 'animated', 'video'])
        assert ps.viewer_order() == ['image', 'animated', 'video']


class TestPluginSettingsGridOrder:

    def test_empty_when_no_file(self):
        ps = PluginSettings()
        assert ps.grid_order() == []

    def test_roundtrip(self):
        ps = PluginSettings()
        ps.set_grid_order(['animated', 'image'])
        assert ps.grid_order() == ['animated', 'image']


class TestPluginSettingsIndependence:

    def test_settings_independent(self):
        ps = PluginSettings()
        ps.set_enabled({'image', 'exif'})
        ps.set_viewer_order(['image'])
        ps.set_grid_order(['image', 'animated'])
        assert ps.enabled_names() == {'image', 'exif'}
        assert ps.viewer_order() == ['image']
        assert ps.grid_order() == ['image', 'animated']

    def test_separate_instances_share_file(self):
        ps1 = PluginSettings()
        ps1.set_enabled({'image'})
        ps2 = PluginSettings()
        assert ps2.enabled_names() == {'image'}


class TestIniLowLevel:

    def test_read_missing_key(self):
        assert _read_ini_value('nonexistent/key') is None

    def test_write_and_read_json_list(self):
        _write_ini_value('test/mylist', ['a', 'b', 'c'])
        assert _read_ini_value('test/mylist') == ['a', 'b', 'c']

    def test_write_creates_directory(self, isolate_ini):
        assert not os.path.isfile(isolate_ini)
        _write_ini_value('section/key', 'value')
        assert os.path.isfile(isolate_ini)

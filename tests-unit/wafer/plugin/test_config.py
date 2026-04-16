import os
import pytest

from wafer.plugin.config import PluginConfig


@pytest.fixture()
def ini_dir(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.plugin.config.resolve_data_path", lambda name: str(tmp_path / name))
    return tmp_path


class TestPluginConfigLoad:
    def test_load_returns_defaults_when_no_file(self, ini_dir):
        cfg = PluginConfig("test", {"min_length": 5, "max_length": 50})
        result = cfg.load()
        assert result == {"min_length": 5, "max_length": 50}

    def test_load_returns_defaults_when_section_missing(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[other]\nfoo = bar\n", encoding="utf-8")
        cfg = PluginConfig("test", {"x": 10})
        assert cfg.load() == {"x": 10}

    def test_load_casts_int(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[blip]\nmin_length = 10\nmax_length = 100\n", encoding="utf-8")
        cfg = PluginConfig("blip", {"min_length": 5, "max_length": 50})
        result = cfg.load()
        assert result["min_length"] == 10
        assert result["max_length"] == 100
        assert isinstance(result["min_length"], int)

    def test_load_casts_float(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[s]\nthreshold = 0.75\n", encoding="utf-8")
        cfg = PluginConfig("s", {"threshold": 0.5})
        assert cfg.load()["threshold"] == 0.75

    def test_load_casts_bool(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[s]\nenabled = true\n", encoding="utf-8")
        cfg = PluginConfig("s", {"enabled": False})
        assert cfg.load()["enabled"] is True

    def test_load_invalid_int_uses_default(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[s]\ncount = abc\n", encoding="utf-8")
        cfg = PluginConfig("s", {"count": 42})
        assert cfg.load()["count"] == 42

    def test_load_json_list(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text('[s]\nkeys = ["a", "b"]\n', encoding="utf-8")
        cfg = PluginConfig("s", {"keys": []})
        assert cfg.load()["keys"] == ["a", "b"]


class TestPluginConfigSave:
    def test_save_creates_ini(self, ini_dir):
        cfg = PluginConfig("blip", {"min_length": 5, "max_length": 50})
        cfg.save(min_length=10, max_length=80)
        cfg2 = PluginConfig("blip", {"min_length": 5, "max_length": 50})
        result = cfg2.load()
        assert result["min_length"] == 10
        assert result["max_length"] == 80

    def test_save_preserves_other_sections(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[exiftool]\nfilter_mode = blacklist\n", encoding="utf-8")
        cfg = PluginConfig("blip", {"x": 1})
        cfg.save(x=2)
        from configparser import ConfigParser
        cp = ConfigParser()
        cp.read(str(ini_path), encoding="utf-8")
        assert cp.get("exiftool", "filter_mode") == "blacklist"
        assert cp.get("blip", "x") == "2"

    def test_save_and_notify_calls_ipc(self, ini_dir):
        from unittest.mock import MagicMock, patch
        mock_node = MagicMock()
        mock_registry = MagicMock()
        mock_registry.resolve_node.return_value = mock_node
        cfg = PluginConfig("blip", {"min_length": 5})
        with patch("wafer.core.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
            cfg.save_and_notify("blip", min_length=10)
        mock_node.send.assert_called_once()
        call_args = mock_node.send.call_args
        assert call_args[0][0] == "plugin.notify"
        assert call_args[1]["dst"] == "collector-blip"
        assert call_args[0][1] == {"min_length": 10}

    def test_save_updates_cache(self, ini_dir):
        cfg = PluginConfig("s", {"a": 1, "b": 2})
        cfg.load()
        cfg.save(a=10)
        assert cfg.get("a") == 10
        assert cfg.get("b") == 2


class TestPluginConfigGet:
    def test_get_loads_on_first_call(self, ini_dir):
        cfg = PluginConfig("s", {"x": 42})
        assert cfg.get("x") == 42

    def test_get_returns_none_for_unknown_key(self, ini_dir):
        cfg = PluginConfig("s", {"x": 42})
        assert cfg.get("nonexistent") is None

    def test_to_dict_returns_copy(self, ini_dir):
        cfg = PluginConfig("s", {"x": 1})
        d = cfg.to_dict()
        d["x"] = 999
        assert cfg.get("x") == 1

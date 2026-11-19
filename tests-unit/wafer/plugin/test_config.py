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
        with patch("wafer.qt.commands.binding.instance_registry.InstanceRegistry.instance", return_value=mock_registry):
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


class TestPluginConfigSharedFile:
    def test_save_keeps_keys_another_instance_wrote(self, ini_dir):
        defaults = {"filters": {}, "sort_mode": 1}
        viewer_a = PluginConfig("key_filter", defaults)
        viewer_a.load()
        PluginConfig("key_filter", defaults).save(filters={"exif": {"mode": "blacklist", "keys": ["a"]}})
        viewer_a.save(sort_mode=0)
        assert PluginConfig("key_filter", defaults).load() == {"filters": {"exif": {"mode": "blacklist", "keys": ["a"]}}, "sort_mode": 0}

    def test_save_before_load_keeps_untouched_keys(self, ini_dir):
        (ini_dir / "viewer_plugins.ini").write_text("[wd14]\na = 5\nb = 7\n", encoding="utf-8")
        cfg = PluginConfig("wd14", {"a": 1, "b": 2})
        cfg.save(a=9)
        assert cfg.get("b") == 7
        assert PluginConfig("wd14", {"a": 1, "b": 2}).load() == {"a": 9, "b": 7}

    def test_failed_write_leaves_the_file_intact(self, ini_dir, monkeypatch):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[s]\nx = 1\n", encoding="utf-8")

        def fail(path, parser):
            raise OSError("disk full")

        monkeypatch.setattr("wafer.plugin.config.write_ini", fail)
        with pytest.raises(OSError):
            PluginConfig("s", {"x": 0}).save(x=2)
        assert ini_path.read_text(encoding="utf-8") == "[s]\nx = 1\n"

    def test_unreadable_file_loads_defaults(self, ini_dir):
        (ini_dir / "viewer_plugins.ini").write_text("x = 1\n", encoding="utf-8")
        assert PluginConfig("s", {"x": 0}).load() == {"x": 0}

    def test_unparsable_file_is_moved_aside_before_save(self, ini_dir, monkeypatch):
        ini_path = ini_dir / "viewer_plugins.ini"
        original = '[plugins]\nenabled_overrides = {"a.B": true}\n[wd14]\nthreshold = 0.3\nthreshold = 0.4\n'
        ini_path.write_text(original, encoding="utf-8")
        warnings = []
        monkeypatch.setattr("wafer.plugin.config.AppLogger.warning", lambda text, exc=None: warnings.append(text))

        PluginConfig("key_filter", {"sort_mode": 1}).save(sort_mode=0)

        bad_files = list(ini_dir.glob("viewer_plugins.ini.*.bad"))
        assert len(bad_files) == 1
        assert bad_files[0].read_text(encoding="utf-8") == original
        assert any(str(bad_files[0]) in text for text in warnings)
        assert PluginConfig("key_filter", {"sort_mode": 1}).load() == {"sort_mode": 0}

    def test_each_unparsable_file_gets_its_own_bad_copy(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        for content in ("x = 1\n", "y = 2\n"):
            ini_path.write_text(content, encoding="utf-8")
            PluginConfig("s", {"x": 0}).save(x=3)
        bad_contents = sorted(p.read_text(encoding="utf-8") for p in ini_dir.glob("viewer_plugins.ini.*.bad"))
        assert bad_contents == ["x = 1\n", "y = 2\n"]

    def test_undecodable_file_is_moved_aside_before_save(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_bytes(b"[s]\nx = \xe3\x81\n")
        assert PluginConfig("s", {"x": "d"}).load() == {"x": "d"}
        PluginConfig("s", {"x": "d"}).save(x="new")
        assert [p.read_bytes() for p in ini_dir.glob("viewer_plugins.ini.*.bad")] == [b"[s]\nx = \xe3\x81\n"]
        assert PluginConfig("s", {"x": "d"}).load() == {"x": "new"}

    def test_values_with_a_percent_sign_are_saved_and_loaded_as_written(self, ini_dir):
        PluginConfig("wd14", {"tag_blacklist": ""}).save(tag_blacklist="a, 50%")
        assert PluginConfig("wd14", {"tag_blacklist": ""}).load() == {"tag_blacklist": "a, 50%"}

    def test_a_file_saved_with_a_bom_is_read_and_not_moved_aside(self, ini_dir):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[zip]\ncache_limit_gb = 20\n", encoding="utf-8-sig")
        PluginConfig("wd14", {"color": "red"}).save(color="blue")
        assert list(ini_dir.glob("viewer_plugins.ini.*.bad")) == []
        assert PluginConfig("zip", {"cache_limit_gb": 5}).load() == {"cache_limit_gb": 20}

    def test_file_that_cannot_be_opened_is_neither_moved_nor_overwritten(self, ini_dir, monkeypatch):
        ini_path = ini_dir / "viewer_plugins.ini"
        ini_path.write_text("[s]\nx = 1\n[other]\nkeep = yes\n", encoding="utf-8")
        monkeypatch.setattr("wafer.core.common.atomic_file._IN_USE_TIMEOUT", 0)

        def locked(*args, **kwargs):
            raise PermissionError(13, "The process cannot access the file", str(ini_path))

        monkeypatch.setattr("wafer.plugin.config.open", locked, raising=False)
        assert PluginConfig("s", {"x": 0}).load() == {"x": 0}
        with pytest.raises(PermissionError):
            PluginConfig("s", {"x": 0}).save(x=2)
        monkeypatch.undo()
        assert ini_path.read_text(encoding="utf-8") == "[s]\nx = 1\n[other]\nkeep = yes\n"
        assert list(ini_dir.glob("viewer_plugins.ini.*.bad")) == []

    def test_update_holds_the_process_lock(self, ini_dir):
        from wafer.core.platform.process_lock import file_lock
        from wafer.plugin.config import update_ini

        lock_path = str(ini_dir / "viewer_plugins.ini.lock")
        with update_ini():
            with pytest.raises(TimeoutError):
                with file_lock(lock_path, timeout=0.05):
                    pass
        with file_lock(lock_path, timeout=0.05):
            pass

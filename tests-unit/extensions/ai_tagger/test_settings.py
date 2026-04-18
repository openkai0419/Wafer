from extensions.ai_tagger.settings import wd14_config


class TestWD14Config:
    def test_section_name(self):
        assert wd14_config._section == "wd14"

    def test_defaults_contain_thresholds(self):
        defaults = wd14_config._defaults
        assert "general_threshold" in defaults
        assert "character_threshold" in defaults

    def test_defaults_contain_rating_mode(self):
        defaults = wd14_config._defaults
        assert defaults["rating_mode"] == "top"

    def test_defaults_contain_enable_flags(self):
        defaults = wd14_config._defaults
        assert defaults["enable_rating"] is True
        assert defaults["enable_character"] is True
        assert defaults["enable_tags"] is True

    def test_defaults_contain_blacklist(self):
        defaults = wd14_config._defaults
        assert defaults["tag_blacklist"] == ""

    def test_default_threshold_values(self):
        defaults = wd14_config._defaults
        assert defaults["general_threshold"] == 0.057
        assert defaults["character_threshold"] == 0.8

    def test_load_returns_defaults_when_no_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(tmp_path / "nonexistent.ini"))
        settings = wd14_config.load()
        assert settings["general_threshold"] == 0.057
        assert settings["character_threshold"] == 0.8
        assert settings["rating_mode"] == "top"
        assert settings["enable_rating"] is True
        assert settings["enable_character"] is True
        assert settings["enable_tags"] is True
        assert settings["tag_blacklist"] == ""

    def test_save_and_load_round_trip(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "test_plugins.ini")
        monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: ini_path)
        wd14_config.save(general_threshold=0.1, character_threshold=0.5, rating_mode="all")
        loaded = wd14_config.load()
        assert loaded["general_threshold"] == 0.1
        assert loaded["character_threshold"] == 0.5
        assert loaded["rating_mode"] == "all"

    def test_save_blacklist_round_trip(self, tmp_path, monkeypatch):
        ini_path = str(tmp_path / "test_plugins.ini")
        monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: ini_path)
        wd14_config.save(tag_blacklist="1boy, cat, simple_background")
        loaded = wd14_config.load()
        assert loaded["tag_blacklist"] == "1boy, cat, simple_background"

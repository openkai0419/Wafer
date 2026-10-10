import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from extensions.wd14._downloader import KNOWN_MODELS, DEFAULT_MODEL
from extensions.wd14.collector import WD14TaggerCollector, _CACHE_MAX, _ENGINE_IDLE_TIMEOUT
from extensions.wd14.settings import parse_blacklist
from extensions.wd14.settings import wd14_config


class TestKnownModels:
    def test_default_model_in_known(self):
        assert DEFAULT_MODEL in KNOWN_MODELS


class TestBuildTags:
    TOP_SETTINGS = {"enable_rating": True, "rating_mode": "top", "enable_character": True, "enable_tags": True}

    def setup_method(self):
        self.collector = WD14TaggerCollector()
        self.result = {
            "ratings": {"general": 0.85, "sensitive": 0.10, "questionable": 0.03, "explicit": 0.02},
            "general": {"1girl": 0.95, "blue_hair": 0.80, "smile": 0.70},
            "character": {"hatsune_miku": 0.90},
        }

    def teardown_method(self):
        self.collector.shutdown()

    # --- rating_mode="top" (default) ---

    def test_top_mode_picks_highest_rating(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["rating"] == "general"
        assert tags["rating_score"] == "0.85"
        self.result["ratings"] = {"sensitive": 0.90, "general": 0.05, "questionable": 0.03, "explicit": 0.02}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["rating"] == "sensitive"

    # --- rating_mode="all" ---

    def test_all_mode_individual_keys(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "all", "enable_character": True, "enable_tags": True})
        assert tags["rating_general"] == "0.85"
        assert tags["rating_sensitive"] == "0.1"
        assert tags["rating_questionable"] == "0.03"
        assert tags["rating_explicit"] == "0.02"
        assert "rating" not in tags
        assert "rating_score" not in tags

    # --- rating_mode="none" (enable_rating=False) ---

    def test_none_mode_no_rating(self):
        tags = self.collector._build_tags(self.result, settings={"enable_rating": False, "rating_mode": "top", "enable_character": True, "enable_tags": True})
        assert "rating" not in tags
        assert "rating_score" not in tags
        assert "rating_general" not in tags

    # --- rating_mode="name" ---

    def test_name_mode_rating_key_only(self):
        tags = self.collector._build_tags(self.result, settings={"enable_rating": True, "rating_mode": "name", "enable_character": True, "enable_tags": True})
        assert tags["rating"] == "general"
        assert "rating_score" not in tags

    # --- general tags ---

    def test_general_comma_separated(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "1girl" in tags["tags"]
        assert "blue_hair" in tags["tags"]
        assert "smile" in tags["tags"]

    def test_empty_general(self):
        self.result["general"] = {}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "tags" not in tags

    def test_disable_tags(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": True, "enable_tags": False})
        assert "tags" not in tags

    # --- character tags ---

    def test_character_comma_separated(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["character"] == "hatsune_miku"
        self.result["character"] = {"hatsune_miku": 0.90, "kagamine_rin": 0.85}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "hatsune_miku" in tags["character"]
        assert "kagamine_rin" in tags["character"]

    def test_empty_character(self):
        self.result["character"] = {}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "character" not in tags

    def test_disable_character(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": False, "enable_tags": True})
        assert "character" not in tags

    # --- blacklist ---

    def test_blacklist_removes_tags(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": True, "enable_tags": True, "tag_blacklist": "1girl, smile"})
        assert "1girl" not in tags["tags"]
        assert "smile" not in tags["tags"]
        assert "blue_hair" in tags["tags"]

    def test_blacklist_all_general_no_tags_key(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": True, "enable_tags": True, "tag_blacklist": "1girl, blue_hair, smile"})
        assert "tags" not in tags

    # --- uses instance settings ---

    def test_uses_instance_settings_by_default(self):
        self.collector._settings = {"enable_rating": False, "rating_mode": "top", "enable_character": True, "enable_tags": True, "tag_blacklist": ""}
        tags = self.collector._build_tags(self.result)
        assert "rating" not in tags
        assert "rating_score" not in tags
        assert "character" in tags
        assert "tags" in tags


class TestParseBlacklist:
    def test_empty_string(self):
        assert parse_blacklist("") == []

    def test_multiple_tags(self):
        assert parse_blacklist("1boy, cat, simple_background") == ["1boy", "cat", "simple_background"]

    def test_whitespace_handling(self):
        assert parse_blacklist("  1boy , cat ,  ") == ["1boy", "cat"]


class TestTwoLevelCache:
    def setup_method(self):
        self.collector = WD14TaggerCollector()
        self.tags = {
            "rating": "general",
            "character": "",
            "general": "1girl, smile",
        }

    def teardown_method(self):
        self.collector.shutdown()

    def test_l1_hash_cache_hit(self):
        self.collector._hash_cache["abc123"] = self.tags
        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
            mock_resolver.load_pil.assert_not_called()
        assert result.status is True
        assert result.tags == self.tags

    def test_l2_pixel_cache_hit(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        assert result.status is True
        assert result.tags == self.tags
        assert self.collector._hash_cache["xyz789"] == self.tags
        self.collector._engine.predict.assert_not_called()

    def test_cache_miss_runs_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        mock_result = {
            "ratings": {"general": 0.85, "sensitive": 0.10, "questionable": 0.03, "explicit": 0.02},
            "general": {"1girl": 0.95},
            "character": {},
        }

        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert result.status is True
        assert result.tags["rating"] == "general"
        assert result.tags["tags"] == "1girl"
        self.collector._engine.predict.assert_called_once()
        assert "new_hash" in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache

    def test_thumbnail_none_returns_failure(self):
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "some_hash"))
        assert result.status is False

    def test_inference_error_returns_failure(self):
        thumb = Image.new("RGB", (10, 10), (128, 128, 128))

        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.side_effect = RuntimeError("ONNX error")

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "err_hash"))
        assert result.status is False


class TestPostInstall:
    def test_post_install_propagates_model_error(self):
        with patch("extensions.wd14.collector.ensure_model", side_effect=RuntimeError("dl failed")):
            with pytest.raises(RuntimeError, match="dl failed"):
                WD14TaggerCollector.post_install("/fake/dir")


class TestCacheEviction:
    def test_hash_cache_evicts_oldest(self):
        collector = WD14TaggerCollector()
        tags = {"rating": "general"}
        for i in range(_CACHE_MAX + 10):
            WD14TaggerCollector._cache_put(collector._hash_cache, f"key_{i}", tags)
        assert len(collector._hash_cache) == _CACHE_MAX
        assert "key_0" not in collector._hash_cache
        assert f"key_{_CACHE_MAX + 9}" in collector._hash_cache


class TestIdleTimeout:
    def setup_method(self):
        self.collector = WD14TaggerCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_touch_starts_timer(self):
        assert self.collector._idle_timer is None
        assert self.collector._last_used == 0.0
        self.collector._touch()
        assert self.collector._last_used > 0.0
        assert self.collector._idle_timer is not None
        assert self.collector._idle_timer.daemon is True

    def test_touch_replaces_previous_timer(self):
        self.collector._touch()
        first_timer = self.collector._idle_timer
        self.collector._touch()
        second_timer = self.collector._idle_timer
        assert first_timer is not second_timer

    def test_check_idle_unloads_engine(self):
        engine = MagicMock()
        self.collector._engine = engine
        self.collector._last_used = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector._check_idle()
        assert self.collector._engine is None

    def test_check_idle_keeps_engine_when_recent(self):
        engine = MagicMock()
        self.collector._engine = engine
        self.collector._last_used = time.monotonic()
        self.collector._check_idle()
        assert self.collector._engine is engine

    def test_process_calls_touch(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        mock_result = {
            "ratings": {"general": 0.85, "sensitive": 0.10, "questionable": 0.03, "explicit": 0.02},
            "general": {"1girl": 0.95},
            "character": {},
        }
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        before = self.collector._last_used
        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert self.collector._last_used > before
        assert self.collector._idle_timer is not None

    def test_engine_reloads_after_unload(self):
        engine = MagicMock()
        self.collector._engine = engine
        self.collector._last_used = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector._check_idle()
        assert self.collector._engine is None

        mock_inference_mod = MagicMock()
        mock_session = MagicMock()
        mock_session.get_providers.return_value = ["CPUExecutionProvider"]
        mock_instance = MagicMock()
        mock_instance.session = mock_session
        mock_inference_mod.WD14Inference.return_value = mock_instance

        with patch("extensions.wd14.collector.ensure_model") as mock_ensure, patch.dict("sys.modules", {"extensions.wd14._inference": mock_inference_mod}):
            mock_ensure.return_value = "/fake/model"

            self.collector._ensure_engine()
            assert self.collector._engine is mock_instance


class TestOnNotify:
    def setup_method(self):
        self.collector = WD14TaggerCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_on_notify_reloads_settings(self):
        original = dict(self.collector._settings)
        with patch.object(wd14_config, "load", return_value={**original, "general_threshold": 0.1}):
            self.collector.on_notify()
        assert self.collector._settings["general_threshold"] == 0.1


class TestOnRequest:
    def setup_method(self):
        self.collector = WD14TaggerCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_unknown_action_returns_none(self):
        assert self.collector.on_request("unknown.action", {}, None) is None

    def test_device_info_action(self):
        result = self.collector.on_request("wd14.device_info", {}, None)
        assert "device" in result
        assert "device_name" in result

    def test_preview_no_path_returns_error(self):
        result = self.collector.on_request("wd14.preview", {"path": ""}, None)
        assert result["error"] == "no_path"

    def test_preview_thumbnail_failed(self):
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.on_request("wd14.preview", {"path": "/test.jpg", "settings": {}}, None)
        assert result["error"] == "thumbnail_failed"

    def test_preview_success(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        mock_result = {
            "ratings": {"general": 0.85, "sensitive": 0.10},
            "general": {"1girl": 0.95},
            "character": {"hatsune_miku": 0.90},
        }
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.on_request(
                "wd14.preview",
                {"path": "/test.jpg", "settings": {"general_threshold": 0.05, "character_threshold": 0.5}},
                None,
            )
        assert "ratings" in result
        assert result["ratings"]["general"] == 0.85
        assert "general" in result
        assert "character" in result
        assert result["path"] == "/test.jpg"


class TestSettingsIntegration:
    def test_process_uses_settings_thresholds(self):
        collector = WD14TaggerCollector()
        collector._settings["general_threshold"] = 0.1
        collector._settings["character_threshold"] = 0.9

        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        mock_result = {
            "ratings": {"general": 0.85},
            "general": {"1girl": 0.95},
            "character": {},
        }
        collector._engine = MagicMock()
        collector._engine.input_height = 448
        collector._engine.predict.return_value = mock_result

        try:
            with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
                mock_resolver.load_pil.return_value = thumb
                collector.process("/test/file.jpg", (1000.0, 500, "hash_x"))
            collector._engine.predict.assert_called_once_with(thumb, general_threshold=0.1, character_threshold=0.9)
        finally:
            collector.shutdown()

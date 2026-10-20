import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from extensions.wd14._downloader import DEFAULT_MODEL
from extensions.wd14.collector import WD14TaggerCollector, _CACHE_MAX, _ENGINE_IDLE_TIMEOUT
from extensions.wd14.settings import parse_blacklist
from extensions.wd14.settings import wd14_config


def mock_engine(result=None, input_size=448):
    engine = MagicMock()
    engine.input_size = input_size
    engine.predict.return_value = result
    return engine


RESULT = {
    "rating": {"general": 0.85, "sensitive": 0.10, "questionable": 0.03, "explicit": 0.02},
    "general": {"1girl": 0.95},
    "character": {},
    "copyright": {},
    "artist": {},
    "meta": {},
}


class TestBuildTags:
    TOP_SETTINGS = {"enable_rating": True, "rating_mode": "top", "enable_character": True, "enable_tags": True}

    def setup_method(self):
        self.collector = WD14TaggerCollector()
        self.result = {
            "rating": {"general": 0.85, "sensitive": 0.10, "questionable": 0.03, "explicit": 0.02},
            "general": {"1girl": 0.95, "blue_hair": 0.80, "smile": 0.70},
            "character": {"hatsune_miku": 0.90},
            "copyright": {"vocaloid": 0.88},
            "artist": {"some_artist": 0.81},
            "meta": {"highres": 0.99, "commentary": 0.4},
        }

    def teardown_method(self):
        self.collector.shutdown()

    def test_top_mode_picks_highest_rating(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["rating"] == "general"
        assert tags["rating_score"] == "0.85"
        self.result["rating"] = {"sensitive": 0.90, "general": 0.05, "questionable": 0.03, "explicit": 0.02}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["rating"] == "sensitive"

    def test_all_mode_individual_keys(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "all", "enable_character": True, "enable_tags": True})
        assert tags["rating_general"] == "0.85"
        assert tags["rating_sensitive"] == "0.1"
        assert tags["rating_questionable"] == "0.03"
        assert tags["rating_explicit"] == "0.02"
        assert "rating" not in tags
        assert "rating_score" not in tags

    def test_none_mode_no_rating(self):
        tags = self.collector._build_tags(self.result, settings={"enable_rating": False, "rating_mode": "top", "enable_character": True, "enable_tags": True})
        assert not any(k.startswith("rating") for k in tags)

    def test_name_mode_rating_key_only(self):
        tags = self.collector._build_tags(self.result, settings={"enable_rating": True, "rating_mode": "name", "enable_character": True, "enable_tags": True})
        assert tags["rating"] == "general"
        assert "rating_score" not in tags

    def test_model_without_ratings_skips_rating(self):
        self.result["rating"] = {}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert not any(k.startswith("rating") for k in tags)
        assert "tags" in tags

    def test_general_comma_separated(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["tags"] == "1girl, blue_hair, smile"

    def test_empty_general(self):
        self.result["general"] = {}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "tags" not in tags

    def test_disable_tags_drops_general_and_meta(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": True, "enable_tags": False})
        assert "tags" not in tags
        assert "meta" not in tags

    def test_named_categories_have_own_keys(self):
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert tags["character"] == "hatsune_miku"
        assert tags["copyright"] == "vocaloid"
        assert tags["artist"] == "some_artist"
        assert tags["meta"] == "highres, commentary"

    def test_empty_character(self):
        self.result["character"] = {}
        tags = self.collector._build_tags(self.result, settings=self.TOP_SETTINGS)
        assert "character" not in tags

    def test_disable_character_drops_named_categories(self):
        tags = self.collector._build_tags(self.result, settings={"rating_mode": "top", "enable_character": False, "enable_tags": True})
        assert "character" not in tags
        assert "copyright" not in tags
        assert "artist" not in tags

    def test_blacklist_removes_general_and_meta_tags(self):
        tags = self.collector._build_tags(self.result, settings={**self.TOP_SETTINGS, "tag_blacklist": "1girl, smile, highres"})
        assert tags["tags"] == "blue_hair"
        assert tags["meta"] == "commentary"

    def test_blacklist_all_general_no_tags_key(self):
        tags = self.collector._build_tags(self.result, settings={**self.TOP_SETTINGS, "tag_blacklist": "1girl, blue_hair, smile"})
        assert "tags" not in tags

    def test_uses_instance_settings_by_default(self):
        self.collector._settings = {"enable_rating": False, "rating_mode": "top", "enable_character": True, "enable_tags": True, "tag_blacklist": ""}
        tags = self.collector._build_tags(self.result)
        assert "rating" not in tags
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
        self.collector._settings = {**wd14_config._defaults}
        self.tags = {"rating": "general", "tags": "1girl, smile", "model": DEFAULT_MODEL}

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
        engine = mock_engine()
        self.collector._engines[DEFAULT_MODEL] = engine

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        assert result.status is True
        assert result.tags == self.tags
        assert self.collector._hash_cache["xyz789"] == self.tags
        engine.predict.assert_not_called()

    def test_cache_miss_runs_inference_and_records_model(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        engine = mock_engine(RESULT)
        self.collector._engines[DEFAULT_MODEL] = engine

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
            mock_resolver.load_pil.assert_called_once_with("/test/file.jpg", size=448)
        assert result.status is True
        assert result.tags["rating"] == "general"
        assert result.tags["tags"] == "1girl"
        assert result.tags["model"] == DEFAULT_MODEL
        engine.predict.assert_called_once()
        assert "new_hash" in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache

    def test_uses_selected_model(self):
        self.collector._settings["model"] = "other-tagger"
        engine = mock_engine(RESULT, input_size=1008)
        self.collector._engines["other-tagger"] = engine

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = Image.new("RGB", (10, 10))
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "h"))
            mock_resolver.load_pil.assert_called_once_with("/test/file.jpg", size=1008)
        assert result.tags["model"] == "other-tagger"
        engine.predict.assert_called_once()

    def test_thumbnail_none_returns_failure(self):
        self.collector._engines[DEFAULT_MODEL] = mock_engine()
        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "some_hash"))
        assert result.status is False

    def test_inference_error_returns_failure(self):
        engine = mock_engine()
        engine.predict.side_effect = RuntimeError("ONNX error")
        self.collector._engines[DEFAULT_MODEL] = engine
        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = Image.new("RGB", (10, 10), (128, 128, 128))
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "err_hash"))
        assert result.status is False


class TestPostInstall:
    def test_post_install_propagates_model_error(self):
        with patch("extensions.wd14.collector.ensure_default_model", side_effect=RuntimeError("dl failed")):
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


class TestEngines:
    def setup_method(self):
        self.collector = WD14TaggerCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def load_patches(self):
        inference_mod = MagicMock()
        inference_mod.TaggerInference.side_effect = lambda spec: MagicMock(spec_name=spec)
        return (
            patch("extensions.wd14.collector.ensure_default_model"),
            patch("extensions.wd14.collector.load_spec", side_effect=lambda name: name),
            patch.dict("sys.modules", {"extensions.wd14._inference": inference_mod}),
        )

    def test_preview_engines_replace_each_other_but_keep_active(self):
        self.collector._settings = {"model": DEFAULT_MODEL}
        p1, p2, p3 = self.load_patches()
        with p1, p2, p3:
            active = self.collector.engine(DEFAULT_MODEL)
            self.collector.engine("preview-a")
            self.collector.engine("preview-b")
        assert set(self.collector._engines) == {DEFAULT_MODEL, "preview-b"}
        assert self.collector._engines[DEFAULT_MODEL] is active

    def test_engine_loads_once_per_model_and_starts_timer(self):
        self.collector._settings = {"model": DEFAULT_MODEL}
        p1, p2, p3 = self.load_patches()
        with p1 as ensure, p2, p3:
            first = self.collector.engine(DEFAULT_MODEL)
            again = self.collector.engine(DEFAULT_MODEL)
            other = self.collector.engine("other-tagger")
        assert first is again
        assert other is not first
        assert ensure.call_count == 1
        assert self.collector._idle_timer is not None
        assert self.collector._idle_timer.daemon is True

    def test_unload_idle_engines_keeps_recent(self):
        idle, recent = MagicMock(), MagicMock()
        self.collector._engines = {"idle": idle, "recent": recent}
        self.collector._last_used = {"idle": time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1, "recent": time.monotonic()}
        self.collector.unload_idle_engines()
        assert self.collector._engines == {"recent": recent}
        assert self.collector._idle_timer is not None

    def test_unload_idle_engines_stops_timer_when_empty(self):
        self.collector._engines = {"idle": MagicMock()}
        self.collector._last_used = {"idle": time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1}
        self.collector.unload_idle_engines()
        assert self.collector._engines == {}
        assert self.collector._idle_timer is None

    def test_engine_reloads_after_unload(self):
        p1, p2, p3 = self.load_patches()
        with p1, p2, p3:
            first = self.collector.engine(DEFAULT_MODEL)
            self.collector._last_used[DEFAULT_MODEL] -= _ENGINE_IDLE_TIMEOUT + 1
            self.collector.unload_idle_engines()
            second = self.collector.engine(DEFAULT_MODEL)
        assert second is not first


class TestOnNotify:
    def test_on_notify_reloads_settings_and_clears_caches(self):
        collector = WD14TaggerCollector()
        collector._hash_cache["h"] = {}
        original = dict(collector._settings)
        with patch.object(wd14_config, "load", return_value={**original, "model": "other-tagger"}):
            collector.on_notify()
        assert collector.model == "other-tagger"
        assert not collector._hash_cache


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
        self.collector._engines[self.collector.model] = mock_engine()
        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.on_request("wd14.preview", {"path": "/test.jpg", "settings": {}}, None)
        assert result["error"] == "thumbnail_failed"

    def test_preview_uses_requested_model(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        engine = mock_engine({**RESULT, "character": {"hatsune_miku": 0.90}})
        self.collector._engines["preview-tagger"] = engine

        with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.on_request(
                "wd14.preview",
                {"path": "/test.jpg", "settings": {"model": "preview-tagger", "general_threshold": 0.05, "character_threshold": 0.5}},
                None,
            )
        engine.predict.assert_called_once_with(thumb, general_threshold=0.05, character_threshold=0.5)
        assert result["rating"]["general"] == 0.85
        assert result["character"] == {"hatsune_miku": 0.90}
        assert result["model"] == "preview-tagger"
        assert result["path"] == "/test.jpg"
        assert result["elapsed_ms"] >= 0


class TestSettingsIntegration:
    def test_process_uses_settings_thresholds(self):
        collector = WD14TaggerCollector()
        collector._settings = {**wd14_config._defaults, "general_threshold": 0.1, "character_threshold": 0.9}
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        engine = mock_engine(RESULT)
        collector._engines[DEFAULT_MODEL] = engine
        try:
            with patch("extensions.wd14.collector.image_loader_resolver") as mock_resolver:
                mock_resolver.load_pil.return_value = thumb
                collector.process("/test/file.jpg", (1000.0, 500, "hash_x"))
            engine.predict.assert_called_once_with(thumb, general_threshold=0.1, character_threshold=0.9)
        finally:
            collector.shutdown()

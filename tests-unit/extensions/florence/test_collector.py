import hashlib
import time
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from extensions.florence._downloader import MODELS, DEFAULT_VARIANT, ensure_model
from extensions.florence.collector import FlorenceCollector, _CACHE_MAX, _ENGINE_IDLE_TIMEOUT


class TestDownloaderConfig:
    def test_default_variant(self):
        assert DEFAULT_VARIANT == "base"

    def test_models_have_base_and_large(self):
        assert "base" in MODELS
        assert "large" in MODELS

    def test_each_model_has_repo_and_revision(self):
        for variant, (repo, revision) in MODELS.items():
            assert "Florence-2" in repo
            assert len(revision) == 40

    def test_unknown_variant_rejected(self):
        with pytest.raises(ValueError, match="Unknown variant"):
            ensure_model("nonexistent")


class TestCollectorClassAttributes:
    def test_name(self):
        assert FlorenceCollector.NAME == "florence"

    def test_extensions_all_files(self):
        assert FlorenceCollector.EXTENSIONS == ()

    def test_priority(self):
        assert FlorenceCollector.PRIORITY == 50

    def test_default_enabled(self):
        assert FlorenceCollector.DEFAULT_ENABLED is False

    def test_batch_size(self):
        assert FlorenceCollector.BATCH_SIZE == 50


class TestTwoLevelCache:
    def setup_method(self):
        self.collector = FlorenceCollector()
        self.tags = {"caption": "a girl standing in a field", "detailed": "a detailed description"}

    def teardown_method(self):
        self.collector.shutdown()

    def test_l1_hash_cache_hit(self):
        self.collector._hash_cache["abc123"] = self.tags
        result = self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
        assert result.status is True
        assert result.tags == self.tags

    def test_l1_cache_skips_thumbnail(self):
        self.collector._hash_cache["abc123"] = self.tags
        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
            mock_resolver.load_pil.assert_not_called()

    def test_l2_pixel_cache_hit(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        self.collector._engine = MagicMock()
        self.collector._loaded_variant = "base"

        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        assert result.status is True
        assert result.tags == self.tags
        assert self.collector._hash_cache["xyz789"] == self.tags

    def test_l2_cache_skips_inference(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        self.collector._engine = MagicMock()
        self.collector._loaded_variant = "base"

        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        self.collector._engine.predict.assert_not_called()

    def test_cache_miss_runs_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))

        engine = MagicMock()
        engine.predict.return_value = "a girl standing in a field"
        self.collector._engine = engine
        self.collector._loaded_variant = "base"

        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert result.status is True
        assert result.tags is not None
        assert "caption" in result.tags

    def test_cache_populated_after_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 0, 255))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]

        engine = MagicMock()
        engine.predict.return_value = "a test caption"
        self.collector._engine = engine
        self.collector._loaded_variant = "base"

        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "hash_a"))
        assert "hash_a" in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache

    def test_thumbnail_none_returns_failure(self):
        self.collector._engine = MagicMock()
        self.collector._loaded_variant = "base"

        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "some_hash"))
        assert result.status is False


class TestSettings:
    def test_enabled_tasks_default(self):
        from extensions.florence.settings import enabled_tasks

        settings = {"enable_caption": True, "enable_detailed": True, "enable_more_detailed": True}
        tasks = enabled_tasks(settings)
        assert "<CAPTION>" in tasks
        assert "<DETAILED_CAPTION>" in tasks
        assert "<MORE_DETAILED_CAPTION>" in tasks

    def test_enabled_tasks_partial(self):
        from extensions.florence.settings import enabled_tasks

        settings = {"enable_caption": True, "enable_detailed": False, "enable_more_detailed": False}
        tasks = enabled_tasks(settings)
        assert tasks == ["<CAPTION>"]

    def test_tag_map_keys(self):
        from extensions.florence.settings import TAG_MAP

        assert TAG_MAP["<CAPTION>"] == "caption"
        assert TAG_MAP["<DETAILED_CAPTION>"] == "detailed"
        assert TAG_MAP["<MORE_DETAILED_CAPTION>"] == "more_detailed"

    def test_inference_error_returns_failure(self):
        collector = FlorenceCollector()
        thumb = Image.new("RGB", (10, 10), (128, 128, 128))

        engine = MagicMock()
        engine.predict.side_effect = RuntimeError("Model error")
        collector._engine = engine
        collector._loaded_variant = "base"

        try:
            with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
                mock_resolver.load_pil.return_value = thumb
                result = collector.process("/test/file.jpg", (1000.0, 500, "err_hash"))
            assert result.status is False
        finally:
            collector.shutdown()

    def test_no_file_hash_still_works(self):
        collector = FlorenceCollector()
        thumb = Image.new("RGB", (10, 10), (0, 128, 0))

        engine = MagicMock()
        engine.predict.return_value = "a test caption"
        collector._engine = engine
        collector._loaded_variant = "base"

        try:
            with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
                mock_resolver.load_pil.return_value = thumb
                result = collector.process("/test/file.jpg", (1000.0, 500))
            assert result.status is True
            assert result.tags is not None
            assert len(collector._hash_cache) == 0
        finally:
            collector.shutdown()

    def test_tags_keys_match_enabled_tasks(self):
        collector = FlorenceCollector()
        collector._hash_cache["h1"] = {"caption": "a cat", "detailed": "a detailed cat"}
        try:
            result = collector.process("/test/file.jpg", (1000.0, 500, "h1"))
            assert "caption" in result.tags
            assert "detailed" in result.tags
            assert result.meta_info is None
        finally:
            collector.shutdown()


class TestCacheEviction:
    def test_hash_cache_evicts_oldest(self):
        collector = FlorenceCollector()
        for i in range(_CACHE_MAX + 10):
            FlorenceCollector._cache_put(collector._hash_cache, f"key_{i}", {"caption": f"cap_{i}"})
        assert len(collector._hash_cache) == _CACHE_MAX
        assert "key_0" not in collector._hash_cache
        assert f"key_{_CACHE_MAX + 9}" in collector._hash_cache

    def test_pixel_cache_evicts_oldest(self):
        collector = FlorenceCollector()
        for i in range(_CACHE_MAX + 5):
            FlorenceCollector._cache_put(collector._pixel_cache, f"px_{i}", {"caption": f"cap_{i}"})
        assert len(collector._pixel_cache) == _CACHE_MAX
        assert "px_0" not in collector._pixel_cache

    def test_cache_hit_moves_to_end(self):
        collector = FlorenceCollector()
        collector._hash_cache["oldest"] = {"caption": "old"}
        for i in range(_CACHE_MAX - 1):
            FlorenceCollector._cache_put(collector._hash_cache, f"key_{i}", {"caption": f"cap_{i}"})
        collector._hash_cache.move_to_end("oldest")
        FlorenceCollector._cache_put(collector._hash_cache, "new_entry", {"caption": "new"})
        assert "oldest" in collector._hash_cache
        assert "key_0" not in collector._hash_cache


class TestIdleTimeout:
    def setup_method(self):
        self.collector = FlorenceCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_touch_sets_last_used(self):
        assert self.collector._last_used == 0.0
        self.collector._touch()
        assert self.collector._last_used > 0.0

    def test_touch_starts_timer(self):
        assert self.collector._idle_timer is None
        self.collector._touch()
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

    def test_check_idle_noop_when_no_engine(self):
        self.collector._last_used = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector._check_idle()
        assert self.collector._engine is None

    def test_process_calls_touch(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        self.collector._engine = MagicMock()
        self.collector._engine.predict.return_value = "caption"
        self.collector._loaded_variant = "base"

        before = self.collector._last_used
        with patch("extensions.florence.collector.image_loader_resolver") as mock_resolver:
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
        mock_instance = MagicMock()
        mock_inference_mod.FlorenceInference.return_value = mock_instance

        with patch("extensions.florence.collector.ensure_model") as mock_ensure, patch.dict("sys.modules", {"extensions.florence._inference": mock_inference_mod}):
            mock_ensure.return_value = "/fake/model"
            self.collector._ensure_engine()
            assert self.collector._engine is mock_instance

    def test_ensure_engine_passes_post_install_version(self):
        from extensions.florence.collector import POST_INSTALL_VERSION

        self.collector._settings["model_variant"] = "large"
        mock_inference_mod = MagicMock()
        mock_inference_mod.FlorenceInference.return_value = MagicMock()

        with patch("extensions.florence.collector.ensure_model") as mock_ensure, patch.dict("sys.modules", {"extensions.florence._inference": mock_inference_mod}):
            mock_ensure.return_value = "/fake/model"
            self.collector._ensure_engine()
            mock_ensure.assert_called_once_with("large", version=POST_INSTALL_VERSION)



class TestPostInstall:
    def test_post_install_calls_ensure_model(self):
        with patch("extensions.florence.collector.ensure_model") as mock_model:
            FlorenceCollector.post_install("/fake/dir")
            mock_model.assert_called_once()

    def test_post_install_propagates_model_error(self):
        with patch("extensions.florence.collector.ensure_model", side_effect=RuntimeError("dl failed")):
            with pytest.raises(RuntimeError, match="dl failed"):
                FlorenceCollector.post_install("/fake/dir")

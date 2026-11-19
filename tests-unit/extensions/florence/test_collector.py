import hashlib
import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from extensions.florence._downloader import MODELS, ensure_model
from extensions.florence.collector import FlorenceCollector

_ENGINE_IDLE_TIMEOUT = FlorenceCollector.ENGINE_IDLE_TIMEOUT


class TestDownloaderConfig:
    def test_each_model_has_repo_and_revision(self):
        for variant, (repo, revision) in MODELS.items():
            assert "Florence-2" in repo
            assert len(revision) == 40

    def test_unknown_variant_rejected(self):
        with pytest.raises(ValueError, match="Unknown variant"):
            ensure_model("nonexistent")


class TestTwoLevelCache:
    def setup_method(self):
        self.collector = FlorenceCollector()
        self.tags = {"caption": "a girl standing in a field", "detailed": "a detailed description"}

    def teardown_method(self):
        self.collector.shutdown()

    def test_l1_hash_cache_hit(self):
        self.collector._hash_cache["abc123"] = self.tags
        with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
            mock_resolver.load_pil.assert_not_called()
        assert result.status is True
        assert result.tags == self.tags
        assert result.meta_info is None

    def test_l2_pixel_cache_hit(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        engine = self.collector._engines["base"] = MagicMock()

        with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        assert result.status is True
        assert result.tags == self.tags
        assert self.collector._hash_cache["xyz789"] == self.tags
        engine.predict.assert_not_called()

    def test_cache_miss_runs_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]

        engine = MagicMock()
        engine.predict.return_value = "a girl standing in a field"
        self.collector._engines["base"] = engine

        with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert result.status is True
        assert result.tags is not None
        assert "caption" in result.tags
        assert "new_hash" in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache

    def test_thumbnail_none_returns_failure(self):
        engine = self.collector._engines["base"] = MagicMock()

        with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "some_hash"))
        assert result.status is False


class TestSettings:
    def test_enabled_tasks(self):
        from extensions.florence.settings import enabled_tasks

        settings = {"enable_caption": True, "enable_detailed": True, "enable_more_detailed": True}
        tasks = enabled_tasks(settings)
        assert "<CAPTION>" in tasks
        assert "<DETAILED_CAPTION>" in tasks
        assert "<MORE_DETAILED_CAPTION>" in tasks
        settings = {"enable_caption": True, "enable_detailed": False, "enable_more_detailed": False}
        assert enabled_tasks(settings) == ["<CAPTION>"]

    def test_inference_error_returns_failure(self):
        collector = FlorenceCollector()
        thumb = Image.new("RGB", (10, 10), (128, 128, 128))

        engine = MagicMock()
        engine.predict.side_effect = RuntimeError("Model error")
        collector._engines["base"] = engine

        try:
            with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
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
        collector._engines["base"] = engine

        try:
            with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
                mock_resolver.load_pil.return_value = thumb
                result = collector.process("/test/file.jpg", (1000.0, 500))
            assert result.status is True
            assert result.tags is not None
            assert len(collector._hash_cache) == 0
        finally:
            collector.shutdown()


class TestCacheEviction:
    def test_hash_cache_evicts_oldest(self):
        collector = FlorenceCollector()
        for i in range(collector.CACHE_MAX + 10):
            collector.cache_put(collector._hash_cache, f"key_{i}", {"caption": f"cap_{i}"})
        assert len(collector._hash_cache) == collector.CACHE_MAX
        assert "key_0" not in collector._hash_cache
        assert f"key_{collector.CACHE_MAX + 9}" in collector._hash_cache


def inference_module():
    module = MagicMock()
    module.FlorenceInference.side_effect = lambda model_dir: MagicMock(model_dir=model_dir)
    return module


class TestIdleTimeout:
    def setup_method(self):
        self.collector = FlorenceCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_engine_starts_daemon_timer(self):
        assert self.collector._idle_timer is None
        with patch("extensions.florence.collector.ensure_model", side_effect=lambda variant, version: variant), patch.dict("sys.modules", {"extensions.florence._inference": inference_module()}):
            self.collector.engine("base")
        assert self.collector._last_used["base"] > 0.0
        assert self.collector._idle_timer is not None
        assert self.collector._idle_timer.daemon is True

    def test_unload_idle_engines_unloads_engine(self):
        self.collector._engines["base"] = MagicMock()
        self.collector._last_used["base"] = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector.unload_idle_engines()
        assert self.collector._engines == {}
        assert self.collector._idle_timer is None

    def test_unload_idle_engines_keeps_recent_engine(self):
        engine = self.collector._engines["base"] = MagicMock()
        self.collector._last_used["base"] = time.monotonic()
        self.collector.unload_idle_engines()
        assert self.collector._engines == {"base": engine}
        assert self.collector._idle_timer is not None

    def test_process_marks_engine_used(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))
        self.collector._engines["base"] = MagicMock()
        self.collector._engines["base"].predict.return_value = "caption"

        with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert self.collector._last_used["base"] > 0.0
        assert self.collector._idle_timer is not None

    def test_engine_reloads_after_unload(self):
        self.collector._engines["base"] = MagicMock()
        self.collector._last_used["base"] = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector.unload_idle_engines()
        assert self.collector._engines == {}

        with patch("extensions.florence.collector.ensure_model", return_value="/fake/model"), patch.dict("sys.modules", {"extensions.florence._inference": inference_module()}):
            engine = self.collector.engine("base")
        assert self.collector._engines == {"base": engine}

    def test_variant_switch_replaces_the_loaded_engine(self):
        with patch("extensions.florence.collector.ensure_model", side_effect=lambda variant, version: variant), patch.dict("sys.modules", {"extensions.florence._inference": inference_module()}):
            self.collector.engine("base")
            large = self.collector.engine("large")
        assert self.collector._engines == {"large": large}

    def test_saving_a_new_variant_unloads_the_old_engine(self):
        self.collector._engines["base"] = MagicMock()
        with patch("extensions.florence.collector.florence_config.load", return_value={**self.collector._settings, "model_variant": "large"}):
            self.collector.on_notify()
        assert self.collector._engines == {}

    def test_ensure_engine_passes_post_install_version(self):
        from extensions.florence.collector import POST_INSTALL_VERSION

        self.collector._settings["model_variant"] = "large"
        mock_inference_mod = MagicMock()
        mock_inference_mod.FlorenceInference.return_value = MagicMock()

        with patch("extensions.florence.collector.ensure_model") as mock_ensure, patch.dict("sys.modules", {"extensions.florence._inference": mock_inference_mod}):
            mock_ensure.return_value = "/fake/model"
            self.collector.engine(self.collector.model)
            mock_ensure.assert_called_once_with("large", version=POST_INSTALL_VERSION)


    def test_preview_uses_the_panel_variant(self):
        mock_inference_mod = MagicMock()
        mock_inference_mod.FlorenceInference.return_value.predict.return_value = "caption"
        self.collector._settings["model_variant"] = "base"
        with (
            patch("extensions.florence.collector.ensure_model", return_value="/fake/model") as mock_ensure,
            patch.dict("sys.modules", {"extensions.florence._inference": mock_inference_mod}),
            patch("wafer.plugin.collector.inference.image_loader_resolver") as mock_resolver,
        ):
            mock_resolver.load_pil.return_value = Image.new("RGB", (10, 10))
            self.collector._handle_preview({"path": "/a.jpg", "settings": {"model_variant": "large"}})
        assert mock_ensure.call_args.args[0] == "large"
        assert list(self.collector._engines) == ["large"]

    def test_settings_reload_retries_failed_engine(self):
        mock_inference_mod = MagicMock()
        with (
            patch("extensions.florence.collector.ensure_model", side_effect=[RuntimeError("missing"), "/fake/model"]),
            patch.dict("sys.modules", {"extensions.florence._inference": mock_inference_mod}),
            patch("extensions.florence.collector.florence_config.load", return_value=dict(self.collector._settings)),
        ):
            with pytest.raises(RuntimeError):
                self.collector.engine("base")
            with pytest.raises(RuntimeError, match="previously failed"):
                self.collector.engine("base")
            self.collector.on_notify()
            self.collector.engine("base")
        assert self.collector._engines["base"] is mock_inference_mod.FlorenceInference.return_value


class TestPostInstall:
    def test_post_install_propagates_model_error(self):
        with patch("extensions.florence.collector.ensure_model", side_effect=RuntimeError("dl failed")):
            with pytest.raises(RuntimeError, match="dl failed"):
                FlorenceCollector.post_install("/fake/dir")

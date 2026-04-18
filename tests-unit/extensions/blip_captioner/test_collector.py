import hashlib
import time
from collections import OrderedDict
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from extensions.blip_captioner._downloader import MODEL_REPO, DEFAULT_MODEL, ensure_model
from extensions.blip_captioner.collector import BlipCaptionerCollector, _CACHE_MAX, _ENGINE_IDLE_TIMEOUT


class TestDownloaderConfig:
    def test_default_model_key(self):
        assert DEFAULT_MODEL == "blip-large"

    def test_model_repo(self):
        assert MODEL_REPO == "Salesforce/blip-image-captioning-large"

    def test_path_traversal_rejected(self):
        with pytest.raises(ValueError, match="Invalid model key"):
            ensure_model("../../etc/passwd")


class TestCollectorClassAttributes:
    def test_name(self):
        assert BlipCaptionerCollector.NAME == "blip"

    def test_extensions_all_files(self):
        assert BlipCaptionerCollector.EXTENSIONS == ()

    def test_priority(self):
        assert BlipCaptionerCollector.PRIORITY == 50

    def test_default_enabled(self):
        assert BlipCaptionerCollector.DEFAULT_ENABLED is False

    def test_batch_size(self):
        assert BlipCaptionerCollector.BATCH_SIZE == 150


class TestTwoLevelCache:
    def setup_method(self):
        self.collector = BlipCaptionerCollector()
        self.caption = "a girl standing in a field of flowers"

    def test_l1_hash_cache_hit(self):
        self.collector._hash_cache["abc123"] = self.caption
        result = self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
        assert result.status is True
        assert result.meta_info == {"caption": self.caption}

    def test_l1_cache_skips_thumbnail(self):
        self.collector._hash_cache["abc123"] = self.caption
        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            self.collector.process("/test/file.jpg", (1000.0, 500, "abc123"))
            mock_resolver.load_pil.assert_not_called()

    def test_l2_pixel_cache_hit(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.caption

        self.collector._engine = MagicMock()

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        assert result.status is True
        assert result.meta_info == {"caption": self.caption}
        assert self.collector._hash_cache["xyz789"] == self.caption

    def test_l2_cache_skips_inference(self):
        thumb = Image.new("RGB", (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.caption

        self.collector._engine = MagicMock()

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "xyz789"))
        self.collector._engine.predict.assert_not_called()

    def test_cache_miss_runs_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 255, 0))

        self.collector._engine = MagicMock()
        self.collector._engine.predict.return_value = self.caption

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert result.status is True
        assert result.meta_info == {"caption": self.caption}
        self.collector._engine.predict.assert_called_once()

    def test_cache_populated_after_inference(self):
        thumb = Image.new("RGB", (10, 10), (0, 0, 255))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]

        self.collector._engine = MagicMock()
        self.collector._engine.predict.return_value = self.caption

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "hash_a"))
        assert "hash_a" in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache
        assert self.collector._hash_cache["hash_a"] == self.caption
        assert self.collector._pixel_cache[pixel_hash] == self.caption

    def test_thumbnail_none_returns_failure(self):
        self.collector._engine = MagicMock()

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = None
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "some_hash"))
        assert result.status is False

    def test_inference_error_returns_failure(self):
        thumb = Image.new("RGB", (10, 10), (128, 128, 128))

        self.collector._engine = MagicMock()
        self.collector._engine.predict.side_effect = RuntimeError("Model error")

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500, "err_hash"))
        assert result.status is False

    def test_no_file_hash_still_works(self):
        thumb = Image.new("RGB", (10, 10), (0, 128, 0))

        self.collector._engine = MagicMock()
        self.collector._engine.predict.return_value = self.caption

        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            result = self.collector.process("/test/file.jpg", (1000.0, 500))
        assert result.status is True
        assert result.meta_info == {"caption": self.caption}
        assert len(self.collector._hash_cache) == 0

    def test_meta_info_uses_caption_key(self):
        self.collector._hash_cache["h1"] = "a cat on a couch"
        result = self.collector.process("/test/file.jpg", (1000.0, 500, "h1"))
        assert "caption" in result.meta_info
        assert result.tags is None


class TestCacheEviction:
    def test_hash_cache_evicts_oldest(self):
        collector = BlipCaptionerCollector()
        for i in range(_CACHE_MAX + 10):
            BlipCaptionerCollector._cache_put(collector._hash_cache, f"key_{i}", f"caption_{i}")
        assert len(collector._hash_cache) == _CACHE_MAX
        assert "key_0" not in collector._hash_cache
        assert f"key_{_CACHE_MAX + 9}" in collector._hash_cache

    def test_pixel_cache_evicts_oldest(self):
        collector = BlipCaptionerCollector()
        for i in range(_CACHE_MAX + 5):
            BlipCaptionerCollector._cache_put(collector._pixel_cache, f"px_{i}", f"caption_{i}")
        assert len(collector._pixel_cache) == _CACHE_MAX
        assert "px_0" not in collector._pixel_cache

    def test_cache_hit_moves_to_end(self):
        collector = BlipCaptionerCollector()
        collector._hash_cache["oldest"] = "old caption"
        for i in range(_CACHE_MAX - 1):
            BlipCaptionerCollector._cache_put(collector._hash_cache, f"key_{i}", f"cap_{i}")
        collector._hash_cache.move_to_end("oldest")
        BlipCaptionerCollector._cache_put(collector._hash_cache, "new_entry", "new caption")
        assert "oldest" in collector._hash_cache
        assert "key_0" not in collector._hash_cache


class TestIdleTimeout:
    def setup_method(self):
        self.collector = BlipCaptionerCollector()

    def test_touch_sets_last_used(self):
        assert self.collector._last_used == 0.0
        self.collector._touch()
        assert self.collector._last_used > 0.0

    def test_touch_starts_timer(self):
        assert self.collector._idle_timer is None
        self.collector._touch()
        assert self.collector._idle_timer is not None
        assert self.collector._idle_timer.daemon is True
        self.collector._idle_timer.cancel()

    def test_touch_replaces_previous_timer(self):
        self.collector._touch()
        first_timer = self.collector._idle_timer
        self.collector._touch()
        second_timer = self.collector._idle_timer
        assert first_timer is not second_timer
        first_timer.cancel()
        second_timer.cancel()

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

        before = self.collector._last_used
        with patch("extensions.blip_captioner.collector.image_loader_resolver") as mock_resolver:
            mock_resolver.load_pil.return_value = thumb
            self.collector.process("/test/file.jpg", (1000.0, 500, "new_hash"))
        assert self.collector._last_used > before
        assert self.collector._idle_timer is not None
        self.collector._idle_timer.cancel()

    def test_engine_reloads_after_unload(self):
        engine = MagicMock()
        self.collector._engine = engine
        self.collector._last_used = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector._check_idle()
        assert self.collector._engine is None

        mock_inference_mod = MagicMock()
        mock_instance = MagicMock()
        mock_inference_mod.BlipInference.return_value = mock_instance

        with patch("extensions.blip_captioner.collector.ensure_model") as mock_ensure, patch.dict("sys.modules", {"extensions.blip_captioner._inference": mock_inference_mod}):
            mock_ensure.return_value = "/fake/model"
            self.collector._ensure_engine()
            assert self.collector._engine is mock_instance


class TestPostInstall:
    def test_post_install_calls_ensure_model(self):
        with patch("wafer.plugin.installer.install_packages", return_value=(True, False)), patch("extensions.blip_captioner.collector.ensure_model") as mock_model:
            BlipCaptionerCollector.post_install("/fake/dir")
            mock_model.assert_called_once()

    def test_post_install_installs_transformers(self):
        with patch("extensions.blip_captioner.collector.ensure_model"), patch("wafer.plugin.installer.install_packages", return_value=(True, False)) as mock_install:
            BlipCaptionerCollector.post_install("/fake/dir")
            transformers_calls = [
                c for c in mock_install.call_args_list
                if any("transformers" in p for p in c[0][1])
            ]
            assert len(transformers_calls) == 1

    @patch("extensions.blip_captioner.collector.sys")
    def test_post_install_tries_cuda_torch_on_windows(self, mock_sys):
        mock_sys.platform = "win32"
        with patch("extensions.blip_captioner.collector.ensure_model"), patch("wafer.plugin.installer.install_packages", return_value=(True, False)) as mock_install:
            BlipCaptionerCollector.post_install("/fake/dir")
            first_call = mock_install.call_args_list[0]
            assert any("torch" in p for p in first_call[0][1])
            extra = first_call[1].get("extra_args") or []
            assert "--index-url" in extra

    @patch("extensions.blip_captioner.collector.sys")
    def test_post_install_retries_default_on_pip_failure(self, mock_sys):
        mock_sys.platform = "win32"
        call_count = [0]

        def side_effect(plugin_dir, packages, on_progress=None, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return (False, False)
            return (True, False)

        with patch("extensions.blip_captioner.collector.ensure_model"), patch("wafer.plugin.installer.install_packages", side_effect=side_effect) as mock_install:
            BlipCaptionerCollector.post_install("/fake/dir")
            second_call = mock_install.call_args_list[1]
            assert any("torch" in p for p in second_call[0][1])
            assert second_call[1].get("extra_args") is None

    @patch("extensions.blip_captioner.collector.sys")
    def test_post_install_no_retry_on_deferred(self, mock_sys):
        mock_sys.platform = "win32"
        with patch("extensions.blip_captioner.collector.ensure_model"), patch("wafer.plugin.installer.install_packages", return_value=(True, True)) as mock_install:
            BlipCaptionerCollector.post_install("/fake/dir")
            torch_calls = [
                c for c in mock_install.call_args_list
                if any("torch" in p for p in c[0][1])
            ]
            assert len(torch_calls) == 1

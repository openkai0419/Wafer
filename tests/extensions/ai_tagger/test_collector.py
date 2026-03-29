import hashlib
import time
from collections import OrderedDict
from unittest.mock import MagicMock, patch, PropertyMock

import pytest
from PIL import Image

from extensions.ai_tagger._downloader import KNOWN_MODELS, DEFAULT_MODEL
from extensions.ai_tagger.collector import WD14TaggerCollector, _CACHE_MAX, _ENGINE_IDLE_TIMEOUT


class TestKnownModels:
    def test_default_model_in_known(self):
        assert DEFAULT_MODEL in KNOWN_MODELS

    def test_all_models_have_repo_id(self):
        for key, repo_id in KNOWN_MODELS.items():
            assert repo_id.startswith('SmilingWolf/')

    def test_eva02_large_included(self):
        assert 'wd-eva02-large-tagger-v3' in KNOWN_MODELS


class TestBuildTags:
    def setup_method(self):
        self.result = {
            'ratings': {'general': 0.85, 'sensitive': 0.10, 'questionable': 0.03, 'explicit': 0.02},
            'general': {'1girl': 0.95, 'blue_hair': 0.80, 'smile': 0.70},
            'character': {'hatsune_miku': 0.90},
        }

    def test_rating_top_one(self):
        tags = WD14TaggerCollector._build_tags(self.result)
        assert tags['wd14.rating'] == 'general'

    def test_general_comma_separated(self):
        tags = WD14TaggerCollector._build_tags(self.result)
        assert '1girl' in tags['wd14.general']
        assert 'blue_hair' in tags['wd14.general']
        assert 'smile' in tags['wd14.general']

    def test_character_comma_separated(self):
        tags = WD14TaggerCollector._build_tags(self.result)
        assert tags['wd14.character'] == 'hatsune_miku'

    def test_empty_character(self):
        self.result['character'] = {}
        tags = WD14TaggerCollector._build_tags(self.result)
        assert 'wd14.character' not in tags

    def test_empty_general(self):
        self.result['general'] = {}
        tags = WD14TaggerCollector._build_tags(self.result)
        assert 'wd14.general' not in tags

    def test_multiple_characters(self):
        self.result['character'] = {'hatsune_miku': 0.90, 'kagamine_rin': 0.85}
        tags = WD14TaggerCollector._build_tags(self.result)
        assert 'hatsune_miku' in tags['wd14.character']
        assert 'kagamine_rin' in tags['wd14.character']

    def test_sensitive_rating(self):
        self.result['ratings'] = {'sensitive': 0.90, 'general': 0.05, 'questionable': 0.03, 'explicit': 0.02}
        tags = WD14TaggerCollector._build_tags(self.result)
        assert tags['wd14.rating'] == 'sensitive'


class TestTwoLevelCache:
    def setup_method(self):
        self.collector = WD14TaggerCollector()
        self.tags = {
            'wd14.rating': 'general',
            'wd14.character': '',
            'wd14.general': '1girl, smile',
        }

    def test_l1_hash_cache_hit(self):
        self.collector._hash_cache['abc123'] = self.tags
        result = self.collector.process('/test/file.jpg', (1000.0, 500, 'abc123'))
        assert result.status is True
        assert result.tags == self.tags

    def test_l1_cache_skips_thumbnail(self):
        self.collector._hash_cache['abc123'] = self.tags
        self.collector._thumbnailer = MagicMock()
        self.collector.process('/test/file.jpg', (1000.0, 500, 'abc123'))
        self.collector._thumbnailer.get_thumbnail.assert_not_called()

    def test_l2_pixel_cache_hit(self):
        thumb = Image.new('RGB', (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        result = self.collector.process('/test/file.jpg', (1000.0, 500, 'xyz789'))
        assert result.status is True
        assert result.tags == self.tags
        assert self.collector._hash_cache['xyz789'] == self.tags

    def test_l2_cache_skips_inference(self):
        thumb = Image.new('RGB', (10, 10), (255, 0, 0))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        self.collector._pixel_cache[pixel_hash] = self.tags

        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        self.collector.process('/test/file.jpg', (1000.0, 500, 'xyz789'))
        self.collector._engine.predict.assert_not_called()

    def test_cache_miss_runs_inference(self):
        thumb = Image.new('RGB', (10, 10), (0, 255, 0))
        mock_result = {
            'ratings': {'general': 0.85, 'sensitive': 0.10, 'questionable': 0.03, 'explicit': 0.02},
            'general': {'1girl': 0.95},
            'character': {},
        }

        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        result = self.collector.process('/test/file.jpg', (1000.0, 500, 'new_hash'))
        assert result.status is True
        assert result.tags['wd14.rating'] == 'general'
        assert result.tags['wd14.general'] == '1girl'
        self.collector._engine.predict.assert_called_once()

    def test_cache_populated_after_inference(self):
        thumb = Image.new('RGB', (10, 10), (0, 0, 255))
        pixel_hash = hashlib.sha256(thumb.tobytes(), usedforsecurity=False).hexdigest()[:16]
        mock_result = {
            'ratings': {'general': 0.85, 'sensitive': 0.10, 'questionable': 0.03, 'explicit': 0.02},
            'general': {'1girl': 0.95},
            'character': {},
        }

        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        self.collector.process('/test/file.jpg', (1000.0, 500, 'hash_a'))
        assert 'hash_a' in self.collector._hash_cache
        assert pixel_hash in self.collector._pixel_cache

    def test_thumbnail_none_returns_failure(self):
        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = None
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448

        result = self.collector.process('/test/file.jpg', (1000.0, 500, 'some_hash'))
        assert result.status is False

    def test_inference_error_returns_failure(self):
        thumb = Image.new('RGB', (10, 10), (128, 128, 128))

        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.side_effect = RuntimeError("ONNX error")

        result = self.collector.process('/test/file.jpg', (1000.0, 500, 'err_hash'))
        assert result.status is False


class TestPostInstall:
    def test_post_install_calls_ensure_model(self):
        with patch('wafer.plugin.installer.install_packages', return_value=True), \
             patch('extensions.ai_tagger.collector.ensure_model') as mock_model:
            WD14TaggerCollector.post_install('/fake/dir')
            mock_model.assert_called_once()

    def test_post_install_tries_gpu_first(self):
        with patch('extensions.ai_tagger.collector.ensure_model'), \
             patch('wafer.plugin.installer.install_packages', return_value=True) as mock_install:
            WD14TaggerCollector.post_install('/fake/dir')
            first_call = mock_install.call_args_list[0]
            assert 'onnxruntime-gpu' in first_call[0][1]

    def test_post_install_falls_back_to_cpu(self):
        call_count = [0]
        def side_effect(plugin_dir, packages, on_progress=None):
            call_count[0] += 1
            if call_count[0] == 1:
                return False
            return True
        with patch('extensions.ai_tagger.collector.ensure_model'), \
             patch('wafer.plugin.installer.install_packages', side_effect=side_effect) as mock_install:
            WD14TaggerCollector.post_install('/fake/dir')
            cpu_call = mock_install.call_args_list[1]
            assert cpu_call[0][1] == ['onnxruntime']


class TestCollectorClassAttributes:
    def test_name(self):
        assert WD14TaggerCollector.NAME == 'wd14'

    def test_extensions_all_files(self):
        assert WD14TaggerCollector.EXTENSIONS == ()

    def test_priority(self):
        assert WD14TaggerCollector.PRIORITY == 50

    def test_default_enabled(self):
        assert WD14TaggerCollector.DEFAULT_ENABLED is False

    def test_batch_size(self):
        assert WD14TaggerCollector.BATCH_SIZE == 32


class TestCacheEviction:
    def test_hash_cache_evicts_oldest(self):
        collector = WD14TaggerCollector()
        tags = {'wd14.rating': 'general'}
        for i in range(_CACHE_MAX + 10):
            WD14TaggerCollector._cache_put(collector._hash_cache, f'key_{i}', tags)
        assert len(collector._hash_cache) == _CACHE_MAX
        assert 'key_0' not in collector._hash_cache
        assert f'key_{_CACHE_MAX + 9}' in collector._hash_cache

    def test_pixel_cache_evicts_oldest(self):
        collector = WD14TaggerCollector()
        tags = {'wd14.rating': 'general'}
        for i in range(_CACHE_MAX + 5):
            WD14TaggerCollector._cache_put(collector._pixel_cache, f'px_{i}', tags)
        assert len(collector._pixel_cache) == _CACHE_MAX
        assert 'px_0' not in collector._pixel_cache

    def test_cache_hit_moves_to_end(self):
        collector = WD14TaggerCollector()
        tags = {'wd14.rating': 'general'}
        collector._hash_cache['oldest'] = tags
        for i in range(_CACHE_MAX - 1):
            WD14TaggerCollector._cache_put(collector._hash_cache, f'key_{i}', tags)
        collector._hash_cache.move_to_end('oldest')
        WD14TaggerCollector._cache_put(collector._hash_cache, 'new_entry', tags)
        assert 'oldest' in collector._hash_cache
        assert 'key_0' not in collector._hash_cache


class TestIdleTimeout:
    def setup_method(self):
        self.collector = WD14TaggerCollector()

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
        thumb = Image.new('RGB', (10, 10), (0, 255, 0))
        mock_result = {
            'ratings': {'general': 0.85, 'sensitive': 0.10, 'questionable': 0.03, 'explicit': 0.02},
            'general': {'1girl': 0.95},
            'character': {},
        }
        self.collector._thumbnailer = MagicMock()
        self.collector._thumbnailer.get_thumbnail.return_value = thumb
        self.collector._engine = MagicMock()
        self.collector._engine.input_height = 448
        self.collector._engine.predict.return_value = mock_result

        before = self.collector._last_used
        self.collector.process('/test/file.jpg', (1000.0, 500, 'new_hash'))
        assert self.collector._last_used > before
        assert self.collector._idle_timer is not None
        self.collector._idle_timer.cancel()

    def test_engine_reloads_after_unload(self):
        engine = MagicMock()
        self.collector._engine = engine
        self.collector._last_used = time.monotonic() - _ENGINE_IDLE_TIMEOUT - 1
        self.collector._check_idle()
        assert self.collector._engine is None

        with patch('extensions.ai_tagger.collector.ensure_model') as mock_ensure, \
             patch('extensions.ai_tagger.collector.WD14Inference') as MockInference:
            mock_session = MagicMock()
            mock_session.get_providers.return_value = ['CPUExecutionProvider']
            mock_instance = MagicMock()
            mock_instance.session = mock_session
            MockInference.return_value = mock_instance
            mock_ensure.return_value = '/fake/model'

            self.collector._ensure_engine()
            assert self.collector._engine is mock_instance

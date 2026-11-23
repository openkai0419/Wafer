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


TASKS = ["<CAPTION>", "<DETAILED_CAPTION>", "<MORE_DETAILED_CAPTION>"]


def color_of(path: str) -> tuple[int, int, int]:
    value = sum(path.encode()) % 256
    return (value, 255 - value, 7)


def fake_load_pil(images: dict):
    return lambda path, size=None: images[path] if path in images else Image.new("RGB", (8, 8), color_of(path))


def text_of(image, task: str) -> str:
    return f"{task}:{image.getpixel((0, 0))}"


def echo_engine() -> MagicMock:
    engine = MagicMock()
    engine.input_size = 384
    engine.predict.side_effect = lambda image, task, **kw: text_of(image, task)
    engine.predict_batch.side_effect = lambda images, task, **kw: [text_of(image, task) for image in images]
    return engine


def run_batch(collector, paths, info=None, images=None):
    info = info or {path: (1.0, 1, f"hash-{path}") for path in paths}
    with patch("wafer.plugin.collector.inference.image_loader_resolver") as resolver:
        resolver.load_pil.side_effect = fake_load_pil(images or {})
        return collector.process_batch(paths, info), resolver


class TestBatchInference:
    def setup_method(self):
        self.collector = FlorenceCollector()

    def teardown_method(self):
        self.collector.shutdown()

    def test_batch_infers_four_images_per_call(self):
        engine = self.collector._engines["base"] = echo_engine()
        paths = [f"/img/{i}.jpg" for i in range(6)]
        results, _ = run_batch(self.collector, paths)
        sizes = [len(call.args[0]) for call in engine.predict_batch.call_args_list]
        assert sizes == [4] * len(TASKS) + [2] * len(TASKS)
        assert [r.source for r in results] == paths
        assert all(r.status is True for r in results)
        engine.predict.assert_not_called()

    def test_batch_matches_one_by_one(self):
        paths = ["/cached.jpg", "/broken.jpg", "/pixel.jpg", "/new1.jpg", "/new2.jpg"]
        info = {path: (1.0, 1, f"hash-{path}") for path in paths}
        pixel_image = Image.new("RGB", (8, 8), (9, 9, 9))
        images = {"/pixel.jpg": pixel_image, "/broken.jpg": None}

        def prepare(collector):
            collector._engines["base"] = echo_engine()
            collector._hash_cache["hash-/cached.jpg"] = {"caption": "cached"}
            collector._pixel_cache[collector.pixel_key(pixel_image)] = {"caption": "pixel"}

        batched = FlorenceCollector()
        single = FlorenceCollector()
        try:
            prepare(batched)
            prepare(single)
            batch_results, resolver = run_batch(batched, paths, info, images)
            with patch("wafer.plugin.collector.inference.image_loader_resolver") as resolver_single:
                resolver_single.load_pil.side_effect = fake_load_pil(images)
                single_results = [single.process(path, info[path]) for path in paths]
            loaded = [call.args[0] for call in resolver.load_pil.call_args_list]
            assert "/cached.jpg" not in loaded
            assert [(r.source, r.status, r.tags) for r in batch_results] == [(r.source, r.status, r.tags) for r in single_results]
        finally:
            batched.shutdown()
            single.shutdown()

    def test_failed_batch_retries_one_by_one(self):
        engine = echo_engine()
        engine.predict_batch.side_effect = RuntimeError("out of memory")
        paths = [f"/img/{i}.jpg" for i in range(4)]
        images = {path: Image.new("RGB", (8, 8), (i * 40, 0, 0)) for i, path in enumerate(paths)}

        def predict(image, task, **kw):
            if image is images[paths[1]]:
                raise RuntimeError("bad image")
            return text_of(image, task)

        engine.predict.side_effect = predict
        self.collector._engines["base"] = engine
        results, _ = run_batch(self.collector, paths, images=images)
        assert [r.status for r in results] == [True, False, True, True]

    def test_stop_between_groups_skips_the_rest(self):
        engine = echo_engine()
        calls = []

        def predict_batch(images, task, **kw):
            calls.append(len(images))
            if len(calls) == len(TASKS):
                self.collector.shutdown()
            return [text_of(image, task) for image in images]

        engine.predict_batch.side_effect = predict_batch
        self.collector._engines["base"] = engine
        paths = [f"/img/{i}.jpg" for i in range(8)]

        def no_load(model):
            raise AssertionError("engine must not be reloaded while stopping")

        with patch.object(self.collector, "load_engine", side_effect=no_load):
            results, _ = run_batch(self.collector, paths)
        assert [r.source for r in results] == paths[:4]
        assert calls == [4] * len(TASKS)
        assert self.collector._engines == {}

    def test_engine_stays_loaded_while_groups_outlast_the_idle_timeout(self, monkeypatch):
        clock = [time.monotonic()]
        monkeypatch.setattr("wafer.plugin.collector.inference.time.monotonic", lambda: clock[0])
        engine = echo_engine()

        def predict_batch(images, task, **kw):
            clock[0] += self.collector.ENGINE_IDLE_TIMEOUT * 0.4
            self.collector.unload_idle_engines()
            return [text_of(image, task) for image in images]

        engine.predict_batch.side_effect = predict_batch
        paths = [f"/img/{i}.jpg" for i in range(12)]
        with patch.object(self.collector, "load_engine", return_value=engine) as load:
            results, _ = run_batch(self.collector, paths)
        assert load.call_count == 1
        assert all(r.status is True for r in results)

    def test_same_pixels_in_a_group_are_inferred_once(self):
        engine = self.collector._engines["base"] = echo_engine()
        paths = [f"/img/{i}.jpg" for i in range(4)]
        same = Image.new("RGB", (8, 8), (5, 5, 5))
        results, _ = run_batch(self.collector, paths, images={path: same for path in paths})
        assert [len(call.args[0]) for call in engine.predict_batch.call_args_list] == [1] * len(TASKS)
        assert len({tuple(sorted(r.tags.items())) for r in results}) == 1
        assert [r.source for r in results] == paths

    def test_group_exception_fails_only_that_group(self):
        engine = self.collector._engines["base"] = echo_engine()
        paths = [f"/img/{i}.jpg" for i in range(8)]
        real = self.collector.process_group
        calls = []

        def process_group(group):
            calls.append(len(group))
            if len(calls) == 1:
                raise RuntimeError("boom")
            return real(group)

        with patch.object(self.collector, "process_group", side_effect=process_group):
            results, _ = run_batch(self.collector, paths)
        assert [(r.source, r.status) for r in results] == [(path, False) for path in paths[:4]] + [(path, True) for path in paths[4:]]

    def test_group_exception_while_stopping_returns_no_results(self):
        self.collector._engines["base"] = echo_engine()

        def process_group(group):
            self.collector.shutdown()
            raise RuntimeError("interrupted")

        with patch.object(self.collector, "process_group", side_effect=process_group):
            results, _ = run_batch(self.collector, [f"/img/{i}.jpg" for i in range(4)])
        assert results == []

    def test_stop_during_batch_inference_logs_no_warning(self):
        self.collector._engines["base"] = echo_engine()

        def stop_then_fail(model, images, settings):
            self.collector.shutdown()
            raise RuntimeError("stopping")

        with patch.object(self.collector, "run_tasks_batch", side_effect=stop_then_fail), patch("extensions.florence.collector.AppLogger.warning") as warning:
            results, _ = run_batch(self.collector, [f"/img/{i}.jpg" for i in range(4)])
        assert results == []
        warning.assert_not_called()

    def test_load_engine_refuses_while_stopping(self):
        self.collector.shutdown()
        with pytest.raises(RuntimeError, match="stopping"):
            self.collector.load_engine("base")
        assert self.collector.engine_failed_at is None

    def test_batch_size_is_a_multiple_of_the_inference_batch(self):
        from extensions.florence.collector import INFER_BATCH

        assert self.collector.BATCH_SIZE == 12
        assert self.collector.BATCH_SIZE % INFER_BATCH == 0

    def test_stop_between_tasks_abandons_the_group(self):
        engine = echo_engine()
        calls = []

        def predict_batch(images, task, **kw):
            calls.append(task)
            self.collector.shutdown()
            return [text_of(image, task) for image in images]

        engine.predict_batch.side_effect = predict_batch
        self.collector._engines["base"] = engine

        def no_load(model):
            raise AssertionError("engine must not be reloaded while stopping")

        with patch.object(self.collector, "load_engine", side_effect=no_load):
            results, _ = run_batch(self.collector, [f"/img/{i}.jpg" for i in range(4)])
        assert results == []
        assert calls == TASKS[:1]
        assert self.collector._engines == {}

    def test_engine_load_failure_leaves_the_batch_for_retry(self):
        self.collector._hash_cache["hash-/cached.jpg"] = {"caption": "cached"}
        paths = ["/cached.jpg"] + [f"/img/{i}.jpg" for i in range(6)]
        with patch("extensions.florence.collector.ensure_model", side_effect=RuntimeError("network down")) as ensure:
            results, _ = run_batch(self.collector, paths)
        assert [(r.source, r.status) for r in results] == [("/cached.jpg", True)]
        assert ensure.call_count == 1

    def test_failed_engine_is_tried_again_after_the_retry_interval(self, monkeypatch):
        from extensions.florence import collector as collector_module

        now = [1000.0]
        monkeypatch.setattr(collector_module.time, "monotonic", lambda: now[0])
        engine = echo_engine()
        inference = MagicMock()
        inference.FlorenceInference.return_value = engine
        paths = [f"/img/{i}.jpg" for i in range(2)]
        with (
            patch("extensions.florence.collector.ensure_model", side_effect=[RuntimeError("network down"), "/fake/model"]) as ensure,
            patch.dict("sys.modules", {"extensions.florence._inference": inference}),
        ):
            assert run_batch(self.collector, paths)[0] == []
            now[0] += collector_module.ENGINE_RETRY_INTERVAL - 1
            assert run_batch(self.collector, paths)[0] == []
            assert ensure.call_count == 1
            now[0] += 2
            results, _ = run_batch(self.collector, paths)
        assert ensure.call_count == 2
        assert [r.status for r in results] == [True, True]

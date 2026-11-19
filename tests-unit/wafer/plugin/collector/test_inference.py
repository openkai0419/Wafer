import time
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from wafer.plugin import BaseInferenceCollector
from wafer.plugin.config import PluginConfig


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr("wafer.plugin.config._ini_path", lambda: str(tmp_path / "viewer_plugins.ini"))


config = PluginConfig("dummy_inference", {"model": "a", "threshold": 0.5})


class Engine:
    input_size = 32

    def __init__(self, model):
        self.model = model
        self.calls = 0

    def predict(self, thumb, threshold):
        self.calls += 1
        return {"label": f"{self.model}:{threshold}"}


class DummyCollector(BaseInferenceCollector):
    NAME = "dummy"
    ENGINE_IDLE_TIMEOUT = 10.0
    DEFAULT_MODEL = "a"
    plugin_config = config

    def __init__(self):
        super().__init__()
        self.loaded = []

    def load_engine(self, model):
        self.loaded.append(model)
        return Engine(model)

    def infer(self, engine, thumb, model):
        return engine.predict(thumb, self._settings["threshold"])

    def preview(self, engine, thumb, settings):
        return engine.predict(thumb, settings.get("threshold", 0.0))

    def device_info(self):
        return {"device": "cpu", "device_name": "CPU"}


class SingleEngineCollector(DummyCollector):
    KEEP_ACTIVE_ENGINE = False


@pytest.fixture
def collector():
    c = DummyCollector()
    yield c
    c.shutdown()


@pytest.fixture
def resolver():
    with patch("wafer.plugin.collector.inference.image_loader_resolver") as mock:
        mock.load_pil.side_effect = lambda path, size: Image.new("RGB", (size, size), (len(path), 0, 0))
        yield mock


def test_base_has_no_name_and_is_abstract():
    assert BaseInferenceCollector.NAME == ""
    with pytest.raises(TypeError):
        BaseInferenceCollector()


def test_process_caches_by_file_hash_and_pixels(collector, resolver):
    first = collector.process("/a.png", (0.0, 1, "h1"))
    assert first.status and first.tags == {"label": "a:0.5"}
    again = collector.process("/b.png", (0.0, 1, "h1"))
    assert again.tags == first.tags
    same_pixels = collector.process("/c.png", (0.0, 1, "h2"))
    assert same_pixels.tags == first.tags
    assert collector._engines["a"].calls == 1
    assert resolver.load_pil.call_count == 2
    assert resolver.load_pil.call_args.kwargs["size"] == Engine.input_size


def test_process_reports_failures(collector, resolver):
    resolver.load_pil.side_effect = lambda path, size: None
    assert collector.process("/a.png", (0.0, 1)).status is False
    resolver.load_pil.side_effect = lambda path, size: Image.new("RGB", (4, 4))
    collector.engine("a").predict = MagicMock(side_effect=RuntimeError("boom"))
    assert collector.process("/a.png", (0.0, 1)).status is False


def test_preview_uses_the_requested_model_and_settings(collector, resolver):
    result = collector.on_request("dummy.preview", {"path": "/a.png", "settings": {"model": "b", "threshold": 0.9}}, None)
    assert result["label"] == "b:0.9"
    assert result["model"] == "b"
    assert result["path"] == "/a.png"
    assert result["elapsed_ms"] >= 0
    assert collector.on_request("dummy.preview", {"path": ""}, None) == {"error": "no_path"}
    assert collector.on_request("dummy.device_info", {}, None)["device"] == "cpu"
    assert collector.on_request("other.preview", {}, None) is None


def test_preview_error_is_returned(collector, resolver):
    collector.engine("a").predict = MagicMock(side_effect=RuntimeError("boom"))
    assert collector.on_request("dummy.preview", {"path": "/a.png", "settings": {}}, None) == {"error": "boom"}


def test_active_engine_stays_while_previews_replace_each_other(collector):
    active = collector.engine("a")
    collector.engine("b")
    collector.engine("c")
    assert collector._engines == {"a": active, "c": collector._engines["c"]}


def test_single_engine_collector_replaces_the_active_engine():
    c = SingleEngineCollector()
    try:
        c.engine("a")
        b = c.engine("b")
        assert c._engines == {"b": b}
    finally:
        c.shutdown()


def test_settings_change_keeps_only_the_new_model(collector):
    collector.engine("a")
    b = collector.engine("b")
    collector._hash_cache["h"] = {}
    with patch.object(config, "load", return_value={"model": "b", "threshold": 0.5}):
        collector.on_notify()
    assert collector._engines == {"b": b}
    assert not collector._hash_cache


def test_settings_change_without_model_change_keeps_engines(collector):
    collector.engine("a")
    collector.engine("b")
    with patch.object(config, "load", return_value={"model": "a", "threshold": 0.1}):
        collector.on_notify()
    assert set(collector._engines) == {"a", "b"}


def test_idle_check_waits_only_for_the_remaining_time(collector):
    collector.engine("a")
    collector._idle_timer.cancel()
    collector._idle_timer = None
    collector._last_used["a"] = time.monotonic() - 7.0
    collector.unload_idle_engines()
    assert "a" in collector._engines
    assert collector._idle_timer.interval == pytest.approx(3.0, abs=0.5)


def test_idle_engines_unload_and_reload(collector):
    first = collector.engine("a")
    collector._last_used["a"] -= collector.ENGINE_IDLE_TIMEOUT + 1
    collector.unload_idle_engines()
    assert collector._engines == {}
    assert collector._idle_timer is None
    assert collector.engine("a") is not first


def test_shutdown_stops_the_timer(collector):
    collector.engine("a")
    timer = collector._idle_timer
    collector.shutdown()
    assert collector._engines == {}
    assert collector._idle_timer is None
    assert timer.finished.is_set()

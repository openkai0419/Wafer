import json
import time

import pytest

from wafer.core.ipc.broker import Broker
from wafer.plugin.parser.handler import parser_resolver
from extensions.text_generation.novelai_parser import NovelAiImageParser
from extensions.text_generation.webui_parser import WebUiImageParser


@pytest.fixture(autouse=True)
def _register_parser():
    for cls in (NovelAiImageParser, WebUiImageParser):
        parser_resolver.registry.register(cls)
    yield
    for cls in (NovelAiImageParser, WebUiImageParser):
        parser_resolver.registry._plugins.pop(cls.NAME, None)
        parser_resolver.registry._instances.pop(cls.NAME, None)


def _poll_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


class TestSmokeParser:
    def test_worker_registers_with_broker(self):
        broker = Broker()
        broker.start()
        try:
            from wafer.app.parser.worker import ParserWorker

            worker = ParserWorker("testdb", "novelai")
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)
                assert _poll_until(lambda: any("parser" in role for role in broker.peer_counts()))
            finally:
                worker.stop()
        finally:
            broker.stop()

    def test_worker_processes_batch(self):
        broker = Broker()
        broker.start()
        try:
            from wafer.app.parser.worker import ParserWorker

            worker = ParserWorker("testdb", "novelai")
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)

                captured = {}
                orig_send_reliable = worker._node.send_reliable

                def _capture_send(topic, payload=None, **kw):
                    captured["topic"] = topic
                    captured["payload"] = payload

                worker._node.send_reliable = _capture_send

                comment_data = json.dumps({"prompt": "a cat", "steps": 20})
                paths = ["/fake/img1.png", "/fake/img2.png"]
                file_info = {p: (1.0, 100, "hash123") for p in paths}
                metadata = {p: {"exiftool.PNG:Comment": comment_data} for p in paths}

                worker._process_batch(paths, file_info, metadata, "testdb")

                assert captured.get("topic") == "parse.result"
                results = captured["payload"]["results"]
                assert len(results) == 2
                for r in results:
                    assert r.get("status") is True or r.get("status") == 1
                    assert r.get("source") is not None
                    assert "prompt" in r.get("meta_info", {})
                    assert r["meta_info"]["prompt"] == "a cat"
            finally:
                worker._node.send_reliable = orig_send_reliable
                worker.stop()
        finally:
            broker.stop()

    def test_worker_handles_invalid_json(self):
        broker = Broker()
        broker.start()
        try:
            from wafer.app.parser.worker import ParserWorker

            worker = ParserWorker("testdb", "novelai")
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)

                captured = {}
                orig_send_reliable = worker._node.send_reliable

                def _capture_send(topic, payload=None, **kw):
                    captured["topic"] = topic
                    captured["payload"] = payload

                worker._node.send_reliable = _capture_send

                paths = ["/fake/img.png"]
                file_info = {"/fake/img.png": (1.0, 100, "hash456")}
                metadata = {"/fake/img.png": {"exiftool.PNG:Comment": "not valid json"}}

                worker._process_batch(paths, file_info, metadata, "testdb")

                assert captured.get("topic") == "parse.result"
                results = captured["payload"]["results"]
                assert len(results) == 1
                assert results[0].get("status") is False or results[0].get("status") == 0
            finally:
                worker._node.send_reliable = orig_send_reliable
                worker.stop()
        finally:
            broker.stop()

    def test_plugin_processes_directly(self):
        plugin = parser_resolver.registry.instance("novelai")
        assert plugin is not None

        data = json.dumps({"seed": 42, "model": "nai-v3"})
        result = plugin.process("/fake/image.png", (1.0, 100), {"exiftool.PNG:Comment": data})

        assert result.status is True
        assert result.meta_info == {"seed": "42", "model": "nai-v3"}
        assert result.delete_keys == ["exiftool.PNG:Comment"]

    def test_plugin_fail_on_non_json(self):
        plugin = parser_resolver.registry.instance("novelai")
        result = plugin.process("/fake/image.png", (1.0, 100), {"exiftool.PNG:Comment": "plain text"})
        assert result.status is False

    def test_plugin_fail_on_missing_key(self):
        plugin = parser_resolver.registry.instance("novelai")
        result = plugin.process("/fake/image.png", (1.0, 100), {})
        assert result is None


_WEBUI_INFOTEXT = (
    "masterpiece, 1girl\n"
    "Negative prompt: lowres\n"
    "Steps: 20, Sampler: Euler a, CFG scale: 7, Seed: 12345, Size: 512x768"
)


class TestSmokeWebUiParser:
    def test_worker_processes_batch(self):
        broker = Broker()
        broker.start()
        try:
            from wafer.app.parser.worker import ParserWorker

            worker = ParserWorker("testdb", "webui")
            worker.start()
            try:
                assert worker._node.wait_registered(timeout=5.0)

                captured = {}
                orig_send_reliable = worker._node.send_reliable

                def _capture_send(topic, payload=None, **kw):
                    captured["topic"] = topic
                    captured["payload"] = payload

                worker._node.send_reliable = _capture_send

                paths = ["/fake/img1.png", "/fake/img2.jpg"]
                file_info = {p: (1.0, 100, "hash123") for p in paths}
                metadata = {
                    "/fake/img1.png": {"exiftool.PNG:Parameters": _WEBUI_INFOTEXT},
                    "/fake/img2.jpg": {"exiftool.ExifIFD:UserComment": _WEBUI_INFOTEXT},
                }

                worker._process_batch(paths, file_info, metadata, "testdb")

                assert captured.get("topic") == "parse.result"
                results = captured["payload"]["results"]
                assert len(results) == 2
                for r in results:
                    assert r.get("status") is True or r.get("status") == 1
                    meta = r.get("meta_info", {})
                    assert meta["prompt"] == "masterpiece, 1girl"
                    assert meta["Steps"] == "20"
                    assert meta["width"] == "512"
                    assert meta["height"] == "768"
            finally:
                worker._node.send_reliable = orig_send_reliable
                worker.stop()
        finally:
            broker.stop()

    def test_plugin_processes_directly(self):
        plugin = parser_resolver.registry.instance("webui")
        assert plugin is not None

        result = plugin.process("/fake/image.png", (1.0, 100), {"exiftool.PNG:Parameters": _WEBUI_INFOTEXT})

        assert result.status is True
        assert result.meta_info["negative_prompt"] == "lowres"
        assert result.meta_info["Seed"] == "12345"
        assert result.delete_keys == ["exiftool.PNG:Parameters"]

    def test_plugin_fail_on_novelai_json(self):
        plugin = parser_resolver.registry.instance("webui")
        data = json.dumps({"prompt": "a cat", "steps": 28})
        result = plugin.process("/fake/image.png", (1.0, 100), {"exiftool.ExifIFD:UserComment": data})
        assert result.status is False

    def test_plugin_fail_on_missing_key(self):
        plugin = parser_resolver.registry.instance("webui")
        result = plugin.process("/fake/image.png", (1.0, 100), {})
        assert result is None

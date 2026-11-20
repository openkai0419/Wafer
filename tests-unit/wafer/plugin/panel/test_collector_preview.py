from types import SimpleNamespace

import pytest

from wafer.plugin import CollectorPreviewWidget
from wafer.qt.commands.binding.instance_registry import InstanceRegistry


class PreviewWidget(CollectorPreviewWidget):
    COLLECTOR = "dummy"
    PREVIEW_TIMEOUT = 5.0

    def __init__(self):
        super().__init__()
        self.shown = []
        self.errors = []
        self.started = 0

    def current_settings(self):
        return {"model": "m"}

    def on_preview_started(self):
        self.started += 1

    def show_preview(self, result):
        self.shown.append(result)

    def show_preview_error(self, error):
        self.errors.append(error)


class Node:
    def __init__(self, reply):
        self.reply = reply
        self.requests = []

    def request(self, topic, payload, dst, timeout):
        self.requests.append((topic, payload, dst, timeout))
        return self.reply


@pytest.fixture
def widget(qtbot, monkeypatch):
    w = PreviewWidget()
    qtbot.addWidget(w)
    w._dispatcher.post = lambda fn: fn()
    monkeypatch.setattr(w, "request_device_info", lambda: None)
    return w


def use_node(monkeypatch, node):
    monkeypatch.setattr(InstanceRegistry.instance(), "resolve_node", lambda: node)


def test_preview_request_goes_to_the_collector(widget, monkeypatch, qtbot):
    node = Node(SimpleNamespace(payload={"label": "x"}))
    use_node(monkeypatch, node)
    widget._current_path = "/a.png"
    widget.request_preview()
    qtbot.waitUntil(lambda: bool(widget.shown), timeout=2000)
    assert node.requests == [("service.request", {"action": "dummy.preview", "path": "/a.png", "settings": {"model": "m"}}, "collector-dummy", 5.0)]
    assert widget.shown == [{"label": "x"}]
    assert widget.started == 1
    assert widget.preview_btn.isEnabled()


@pytest.mark.parametrize(
    ("node", "error"),
    [
        (None, "No IPC node"),
        (Node(None), "Collector not running or timed out"),
        (Node(SimpleNamespace(payload="bad")), "Unexpected response"),
    ],
)
def test_preview_errors_are_shown(widget, monkeypatch, qtbot, node, error):
    use_node(monkeypatch, node)
    widget._current_path = "/a.png"
    widget.request_preview()
    qtbot.waitUntil(lambda: bool(widget.errors), timeout=2000)
    assert widget.errors == [error]
    assert not widget.shown


def test_drop_during_request_previews_the_new_file(widget, monkeypatch):
    sent = []
    monkeypatch.setattr(widget, "_do_preview_request", lambda path, settings: sent.append(path))
    monkeypatch.setattr(widget, "_load_preview_thumb", lambda path: None)
    widget.set_preview_path("/a.png")
    widget.set_preview_path("/b.png")
    assert sent == ["/a.png"]
    widget._on_preview_result({"label": "a"})
    assert sent == ["/a.png", "/b.png"]
    assert widget.shown == []


def test_device_info_shows_unknown_on_error(qtbot, monkeypatch):
    w = PreviewWidget()
    qtbot.addWidget(w)
    w._dispatcher.post = lambda fn: fn()
    use_node(monkeypatch, Node(SimpleNamespace(payload={"device": "cuda", "device_name": "GPU"})))
    w.request_device_info()
    qtbot.waitUntil(lambda: w._device_ok, timeout=2000)
    assert w.device_label.text() == "Device: CUDA  (GPU)"
    use_node(monkeypatch, None)
    w.request_device_info()
    qtbot.waitUntil(lambda: not w._device_ok, timeout=2000)
    assert "No IPC node" in w.device_label.text()

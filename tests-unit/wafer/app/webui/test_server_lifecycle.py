import asyncio
import socket
import time

from aiohttp import web

from wafer.app.webui.backend import server as server_module
from wafer.web import media


def test_create_app_gives_the_saved_limit_to_the_thumbnail_cache(monkeypatch):
    monkeypatch.setattr(media, "_thumb_cache", None)
    monkeypatch.setattr(media, "_thumb_cache_limit_mb", media.THUMB_CACHE_DEFAULT_MB)
    monkeypatch.setattr(server_module.WebUISettings, "thumb_cache_mb", lambda self: 128)
    app = server_module.create_app(with_events=False)
    app[server_module.MEDIA_EXECUTOR].shutdown(wait=True, cancel_futures=True)
    assert media._thumb_cache_limit_mb == 128


def test_stop_before_serve_skips_startup(monkeypatch):
    created = []

    def fake_create_app(**kwargs):
        created.append(kwargs)
        return web.Application()

    monkeypatch.setattr(server_module, "create_app", fake_create_app)
    server = server_module.WebServer("127.0.0.1", 0)
    server.stop(timeout=0.1)
    asyncio.run(server._serve())

    assert created == []


def test_start_then_immediate_stop_terminates_thread(monkeypatch):
    monkeypatch.setattr(server_module, "create_app", lambda **kwargs: web.Application())

    for _ in range(5):
        server = server_module.WebServer("127.0.0.1", 0)
        server.start()
        server.stop(timeout=3.0)

        assert server._thread is not None
        assert not server._thread.is_alive()


def _wait_for(predicate, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return False


def test_server_reports_port_in_use():
    blocker = socket.socket()
    blocker.bind(("127.0.0.1", 0))
    blocker.listen()
    port = blocker.getsockname()[1]
    messages = []
    shutdowns = []
    server = server_module.WebServer("127.0.0.1", port, on_failed=messages.append, on_app_shutdown=lambda: shutdowns.append(1))
    try:
        server.start()
        assert _wait_for(lambda: messages and shutdowns), (messages, shutdowns)
        assert str(port) in messages[0]
        assert "WebUI Settings" in messages[0]
        assert len(messages) == 1
    finally:
        server.stop(timeout=3.0)
        blocker.close()


def test_other_start_failure_does_not_call_on_failed(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(server_module, "create_app", boom)
    messages = []
    shutdowns = []
    server = server_module.WebServer("127.0.0.1", 0, on_failed=messages.append, on_app_shutdown=lambda: shutdowns.append(1))
    server.start()
    assert _wait_for(lambda: shutdowns)
    server.stop(timeout=3.0)
    assert messages == []

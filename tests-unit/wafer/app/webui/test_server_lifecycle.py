import asyncio

from aiohttp import web

from wafer.app.webui.backend import server as server_module


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

from __future__ import annotations

import asyncio
import socket
import threading

import pytest

pytest.importorskip("playwright.sync_api")

from aiohttp import web

from wafer.app.webui.backend import session
from wafer.app.webui.backend.server import allowed_hosts_for, create_app


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _run_loop(loop: asyncio.AbstractEventLoop):
    asyncio.set_event_loop(loop)
    loop.run_forever()


@pytest.fixture
def restartable_webui_server():
    mp = pytest.MonkeyPatch()
    mp.setattr(session, "list_data_db_names", lambda: [])

    host, port = "127.0.0.1", _free_port()
    loop = asyncio.new_event_loop()
    thread = threading.Thread(target=_run_loop, args=(loop,), name="conn-banner-e2e-loop", daemon=True)
    thread.start()

    state: dict = {}

    def start():
        async def _start():
            app = create_app(with_events=False, allowed_hosts=allowed_hosts_for(host, port))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
            state["runner"] = runner

        asyncio.run_coroutine_threadsafe(_start(), loop).result(timeout=20)

    def stop():
        async def _stop():
            await state["runner"].cleanup()

        asyncio.run_coroutine_threadsafe(_stop(), loop).result(timeout=20)
        del state["runner"]

    start()

    yield f"http://{host}:{port}", start, stop

    if "runner" in state:
        stop()
    loop.call_soon_threadsafe(loop.stop)
    thread.join(timeout=10)
    mp.undo()


def test_connection_banner_shows_on_disconnect_and_hides_on_reconnect(page, restartable_webui_server):
    base_url, start, stop = restartable_webui_server
    page.goto(base_url)
    page.wait_for_selector("#conn-banner", state="attached")
    assert page.eval_on_selector("#conn-banner", "el => el.classList.contains('hidden')")

    stop()
    page.wait_for_function(
        "!document.querySelector('#conn-banner').classList.contains('hidden')",
        timeout=15000,
    )

    start()
    page.wait_for_function(
        "document.querySelector('#conn-banner').classList.contains('hidden')",
        timeout=15000,
    )

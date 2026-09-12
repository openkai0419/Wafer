from __future__ import annotations

import asyncio
import socket
import threading

import pytest

pytest.importorskip("playwright.sync_api")

from aiohttp import web

from test_support.webui_dataset import DB_NAME, build_webui_dataset


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session", autouse=True)
def _require_chromium():
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception as e:
        pytest.skip(f"Chromium not available for Playwright (run: playwright install chromium): {e}")


@pytest.fixture(scope="session")
def webui_base_url(tmp_path_factory):
    from extensions.image.loader import ImageFileLoader
    from extensions.zip.resolver import ZipImageLoader
    from wafer.app.webui.backend import api as backend_api
    from wafer.app.webui.backend import session
    from wafer.app.webui.backend.server import allowed_hosts_for, create_app
    from wafer.plugin.imageloader.handler import image_loader_resolver
    from wafer.web import media

    root = tmp_path_factory.mktemp("webui_e2e")
    build_webui_dataset(root)
    thumbs = root / "thumbs"
    thumbs.mkdir()

    image_loader_resolver.registry.register(ImageFileLoader)
    image_loader_resolver.registry.register(ZipImageLoader)

    mp = pytest.MonkeyPatch()
    mp.setattr(session, "data_db_path", lambda name: str(root / "data" / f"{name}.db"))
    mp.setattr(session, "list_data_db_names", lambda: [DB_NAME])
    mp.setattr(backend_api, "setting_db_path", lambda name: str(root / "dirs" / f"{name}.db"))
    mp.setattr(media, "thumb_cache_dir", lambda: str(thumbs))

    host, port = "127.0.0.1", _free_port()
    ready = threading.Event()
    state: dict = {}

    def run():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        state["loop"] = loop

        async def serve():
            app = create_app(with_events=False, allowed_hosts=allowed_hosts_for(host, port))
            runner = web.AppRunner(app)
            await runner.setup()
            await web.TCPSite(runner, host, port).start()
            stop = asyncio.Event()
            state["stop"] = stop
            ready.set()
            await stop.wait()
            await runner.cleanup()

        loop.run_until_complete(serve())
        loop.close()

    thread = threading.Thread(target=run, name="webui-e2e", daemon=True)
    thread.start()
    if not ready.wait(timeout=20):
        pytest.fail("WebUI E2E server did not start in time")

    yield f"http://{host}:{port}"

    state["loop"].call_soon_threadsafe(state["stop"].set)
    thread.join(timeout=10)
    mp.undo()


@pytest.fixture
def ready_page(page, webui_base_url):
    page.goto(webui_base_url)
    page.wait_for_selector("#db-select option", state="attached")
    page.wait_for_function("document.querySelector('#status').textContent.includes('files')")
    page.wait_for_selector("#grid-canvas .cell")
    return page

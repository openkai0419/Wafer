from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlparse

from aiohttp import web

from wafer.utils.logs import AppLogger
from wafer.utils.paths import get_resource_path

from . import api, events, media
from .events import EVENT_HUB, EventHub
from .media import MEDIA_EXECUTOR
from .session import QUERY_SERVICE, QueryService

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

WITH_EVENTS = web.AppKey("with_events", bool)
ALLOWED_HOSTS = web.AppKey("allowed_hosts", frozenset)

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "[::1]"})


def allowed_hosts_for(host: str, port: int) -> frozenset[str] | None:
    if host not in LOOPBACK_HOSTS:
        return None
    names = {"127.0.0.1", "localhost", "[::1]"}
    return frozenset({f"{n}:{port}" for n in names} | names)


@web.middleware
async def same_origin_middleware(request: web.Request, handler):
    allowed = request.app.get(ALLOWED_HOSTS)
    if allowed is not None and request.host not in allowed:
        raise web.HTTPForbidden(reason="host is not allowed")
    if request.headers.get("Sec-Fetch-Site") in ("cross-site", "same-site"):
        raise web.HTTPForbidden(reason="cross-origin requests are not allowed")
    origin = request.headers.get("Origin")
    if origin and urlparse(origin).netloc not in ("", request.host):
        raise web.HTTPForbidden(reason="cross-origin requests are not allowed")
    return await handler(request)


@web.middleware
async def no_cache_middleware(request: web.Request, handler):
    response = await handler(request)
    if request.path == "/" or request.path.startswith(("/js/", "/css/")):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return response


async def index(request: web.Request):
    return web.FileResponse(FRONTEND_DIR / "index.html")


async def favicon(request: web.Request):
    return web.FileResponse(get_resource_path() / "icon.ico")


async def on_startup(app: web.Application):
    if app[WITH_EVENTS]:
        app[EVENT_HUB].start_node()


async def on_shutdown(app: web.Application):
    AppLogger.info("WebUI shutting down.")
    await app[EVENT_HUB].close()
    app[QUERY_SERVICE].close()
    app[MEDIA_EXECUTOR].shutdown(wait=True, cancel_futures=True)


def create_app(with_events: bool = True, on_app_shutdown=None, on_dev_log=None, allowed_hosts=None) -> web.Application:
    app = web.Application(middlewares=[same_origin_middleware, no_cache_middleware])
    app[WITH_EVENTS] = with_events
    if allowed_hosts is not None:
        app[ALLOWED_HOSTS] = allowed_hosts
    app[QUERY_SERVICE] = QueryService()
    app[MEDIA_EXECUTOR] = ThreadPoolExecutor(max_workers=4, thread_name_prefix="webmedia")
    app[EVENT_HUB] = EventHub(on_app_shutdown=on_app_shutdown, on_dev_log=on_dev_log)
    app.router.add_get("/", index)
    app.router.add_get("/favicon.ico", favicon)
    app.add_routes(api.routes)
    app.add_routes(media.routes)
    app.add_routes(events.routes)
    app.router.add_static("/css", FRONTEND_DIR / "css")
    app.router.add_static("/js", FRONTEND_DIR / "js")
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


def quiet_connection_reset_handler(loop, context):
    if isinstance(context.get("exception"), ConnectionResetError):
        return
    loop.default_exception_handler(context)


class WebServer:
    def __init__(self, host: str, port: int, *, on_started=None, on_app_shutdown=None, on_dev_log=None):
        self.host = host
        self.port = port
        self.on_started = on_started
        self.on_app_shutdown = on_app_shutdown
        self.on_dev_log = on_dev_log
        self.app: web.Application | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None
        self._stop_requested = False
        self._state_lock = threading.Lock()
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def browse_url(self) -> str:
        from ..settings import browse_url

        return browse_url(self.host, self.port)

    @property
    def node(self):
        app = self.app
        return app[EVENT_HUB].node if app is not None else None

    def start(self):
        self._thread = threading.Thread(target=self._run, name="webserver", daemon=True)
        self._thread.start()

    def _run(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.set_exception_handler(quiet_connection_reset_handler)
        self.loop = loop
        try:
            loop.run_until_complete(self._serve())
        except Exception as e:
            AppLogger.error(f"WebUI server failed: {e}")
            if self.on_app_shutdown is not None:
                self.on_app_shutdown()
        finally:
            loop.close()

    async def _serve(self):
        with self._state_lock:
            if self._stop_requested:
                AppLogger.info("WebUI server was stopped before it started serving.")
                return
            stop_event = self._stop_event = asyncio.Event()
        self.app = create_app(
            on_app_shutdown=self.on_app_shutdown,
            on_dev_log=self.on_dev_log,
            allowed_hosts=allowed_hosts_for(self.host, self.port),
        )
        runner = web.AppRunner(self.app)
        await runner.setup()
        site = web.TCPSite(runner, self.host, self.port)
        await site.start()
        AppLogger.info(f"WebUI serving at {self.url}")
        if self.host not in LOOPBACK_HOSTS:
            AppLogger.warning(f"WebUI is exposed to the network on {self.host}. Access control is your responsibility (firewall/VPN/reverse proxy).")
        if self.on_started is not None:
            self.on_started()
        await stop_event.wait()
        await runner.cleanup()

    def stop(self, timeout: float = 10.0):
        with self._state_lock:
            self._stop_requested = True
            loop, stop_event = self.loop, self._stop_event
        if loop is not None and stop_event is not None and not loop.is_closed():
            loop.call_soon_threadsafe(stop_event.set)
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                AppLogger.error(f"WebUI server thread did not stop within {timeout}s.")


def run_server(host: str, port: int, on_started=None):
    stop = threading.Event()
    server = WebServer(host, port, on_started=on_started, on_app_shutdown=stop.set)
    server.start()
    try:
        while not stop.wait(0.5):
            pass
    except KeyboardInterrupt:
        AppLogger.info("WebUI interrupted.")
    server.stop()

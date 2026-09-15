from __future__ import annotations

import sys
import webbrowser

from ...core.logs import AppLogger
from .settings import browse_url
from .state import write_state


def _on_started(url: str, open_browser: bool):
    write_state(url)
    AppLogger.info(f"WebUI started at {url}")
    if open_browser:
        webbrowser.open(url)


def run_headless(host: str, port: int, *, open_browser: bool):
    import threading

    from ..startup import StartupTasks
    from .backend.server import run_server

    threading.Thread(target=StartupTasks(headless=True).run, name="webui-update-check", daemon=True).start()
    url = browse_url(host, port)
    run_server(host, port, on_started=lambda: _on_started(url, open_browser))


def run_ui(app, host: str, port: int, *, open_browser: bool):
    from ..startup import StartupTasks
    from .backend.server import WebServer
    from .window import WebUIWindow

    server = WebServer(host, port)
    window = WebUIWindow(server)
    window.bind_remote_logs()
    server.on_started = lambda: _on_started(server.browse_url, open_browser)
    server.on_app_shutdown = window.request_shutdown
    server.start()
    window.show()
    StartupTasks().run()
    sys.exit(app.exec())

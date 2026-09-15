from __future__ import annotations

import os
import threading
from configparser import ConfigParser

from ...core.logs import AppLogger
from ...core.common.paths import resolve_data_path

_FILENAME = "webui_settings.ini"
_SECTION = "webui"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

HOST_LOCAL = "127.0.0.1"
HOST_ALL = "0.0.0.0"

_lock = threading.Lock()


def browse_url(host: str, port: int) -> str:
    reachable = HOST_LOCAL if host == HOST_ALL else host
    return f"http://{reachable}:{port}"


def _path() -> str:
    return resolve_data_path(_FILENAME)


class WebUISettings:
    def _read(self) -> ConfigParser:
        cp = ConfigParser()
        path = _path()
        if os.path.isfile(path):
            cp.read(path, encoding="utf-8")
        return cp

    def host(self) -> str:
        return self._read().get(_SECTION, "host", fallback=DEFAULT_HOST)

    def port(self) -> int:
        try:
            return self._read().getint(_SECTION, "port", fallback=DEFAULT_PORT)
        except ValueError:
            return DEFAULT_PORT

    def set_bind(self, host: str, port: int) -> None:
        with _lock:
            cp = self._read()
            if not cp.has_section(_SECTION):
                cp.add_section(_SECTION)
            cp.set(_SECTION, "host", str(host))
            cp.set(_SECTION, "port", str(int(port)))
            path = _path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                cp.write(f)
        AppLogger.info(f"WebUI settings saved: host={host} port={port}")

    def resolve_bind(self, cli_host: str | None, cli_port: int | None) -> tuple[str, int]:
        host = cli_host if cli_host is not None else self.host()
        port = cli_port if cli_port is not None else self.port()
        return host, int(port)

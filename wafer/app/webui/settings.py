from __future__ import annotations

import os
import re
import threading
from configparser import ConfigParser

from ...core.logs import AppLogger
from ...core.common.ini_io import write_ini
from ...core.common.paths import resolve_data_path
from ...web.media import THUMB_CACHE_DEFAULT_MB

_FILENAME = "webui_settings.ini"
_SECTION = "webui"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787

HOST_LOCAL = "127.0.0.1"
HOST_ALL = "0.0.0.0"

LOOPBACK_HOST_NAMES = ("127.0.0.1", "localhost", "[::1]")
PRIVATE_NAME_SUFFIXES = (".ts.net", ".local", ".lan", ".home", ".home.arpa", ".internal", ".localdomain")

_HOST_PATTERN = re.compile(r"^(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*$")

_lock = threading.Lock()


def browse_url(host: str, port: int) -> str:
    reachable = HOST_LOCAL if host == HOST_ALL else host
    return f"http://{reachable}:{port}"


def classify_allowed_hosts(text: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    hosts: list[str] = []
    invalid: list[str] = []
    for raw in re.split(r"[,\s]+", text or ""):
        entry = raw.strip().lower().split("://", 1)[-1].split("/", 1)[0].rstrip(".")
        if entry.count(":") == 1:
            entry = entry.rsplit(":", 1)[0]
        if not entry:
            continue
        if not _HOST_PATTERN.match(entry) or (entry.startswith("*.") and "." not in entry[2:]):
            invalid.append(raw)
        elif entry not in hosts:
            hosts.append(entry)
    return tuple(hosts), tuple(invalid)


def parse_allowed_hosts(text: str) -> tuple[str, ...]:
    hosts, invalid = classify_allowed_hosts(text)
    for raw in invalid:
        AppLogger.warning(f"WebUI allowed host ignored (use a name like example.com or *.example.com): {raw}")
    return hosts


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

    def allowed_hosts(self) -> tuple[str, ...]:
        return parse_allowed_hosts(self._read().get(_SECTION, "allowed_hosts", fallback=""))

    def thumb_cache_mb(self) -> int:
        try:
            return self._read().getint(_SECTION, "thumb_cache_mb", fallback=THUMB_CACHE_DEFAULT_MB)
        except ValueError:
            return THUMB_CACHE_DEFAULT_MB

    def save(self, host: str, port: int, allowed_hosts: tuple[str, ...] = (), thumb_cache_mb: int | None = None) -> None:
        with _lock:
            cp = self._read()
            if not cp.has_section(_SECTION):
                cp.add_section(_SECTION)
            cp.set(_SECTION, "host", str(host))
            cp.set(_SECTION, "port", str(int(port)))
            cp.set(_SECTION, "allowed_hosts", ", ".join(allowed_hosts))
            if thumb_cache_mb is not None:
                cp.set(_SECTION, "thumb_cache_mb", str(int(thumb_cache_mb)))
            write_ini(_path(), cp)
        AppLogger.info(f"WebUI settings saved: host={host} port={port} allowed_hosts={', '.join(allowed_hosts) or '-'}")

    def resolve_bind(self, cli_host: str | None, cli_port: int | None) -> tuple[str, int]:
        host = cli_host if cli_host is not None else self.host()
        port = cli_port if cli_port is not None else self.port()
        return host, int(port)

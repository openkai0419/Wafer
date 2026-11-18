from __future__ import annotations
import contextlib
import json
import time
from pathlib import Path
from queue import Empty, Full, Queue
from typing import Any

import zmq

from ..logs import debug_non_recursive
from ..common.paths import profile_data_root, resolve_data_path
from ..common.profile import current_profile


class Priority:
    HIGH = 0
    MID = 1
    LOW = 2


HEARTBEAT_INTERVAL = 1
HEARTBEAT_TIMEOUT = 3
NODE_TIMEOUT = 5
POLL_BASE_MS = 10
POLL_MAX_MS = 50
DEFAULT_PORT = 57556
EPHEMERAL_PORT_MIN = 49152
EPHEMERAL_PORT_END = 65536
BROKER_QUEUE_MAX = 1000
NODE_QUEUE_MAX = 200
RECONNECT_FORCE_INTERVAL = 5.0
BROKER_LOST_TIMEOUT = 20
ZMQ_SNDTIMEO_MS = 800
ZMQ_RCVTIMEO_MS = 800
PORT_FILE_REPLACE_RETRIES = 20
PORT_FILE_REPLACE_RETRY_SEC = 0.05
APP_ID = "wafer"

_PORT_FILE = Path(resolve_data_path("ipc/broker.json"))
CURRENT_PROFILE = object()


def resolve_profile(profile: str | None | object) -> str | None:
    return current_profile() if profile is CURRENT_PROFILE else profile


def port_file_for(profile: str | None) -> Path:
    if profile == current_profile():
        return _PORT_FILE
    return profile_data_root(profile) / "ipc" / "broker.json"


def tune_socket(sock: zmq.Socket) -> None:
    for opt, val in ((zmq.SNDTIMEO, ZMQ_SNDTIMEO_MS), (zmq.RCVTIMEO, ZMQ_RCVTIMEO_MS)):
        try:
            sock.setsockopt(opt, val)
        except Exception as e:
            from ..logs import AppLogger

            AppLogger.debug(f"tune_socket setsockopt failed: {e}")


def close_socket(sock: zmq.Socket) -> None:
    try:
        sock.setsockopt(zmq.LINGER, 0)
    except Exception as e:
        from ..logs import AppLogger

        AppLogger.debug(f"close_socket LINGER failed: {e}")
    try:
        sock.close()
    except Exception as e:
        from ..logs import AppLogger

        AppLogger.debug(f"close_socket close failed: {e}")


def try_put(q: Queue, item: Any, label: str = "") -> None:
    try:
        q.put_nowait(item)
    except Full:
        with contextlib.suppress(Empty):
            q.get_nowait()
        try:
            q.put_nowait(item)
        except Full:
            return
        debug_non_recursive(f"zmq queue eviction: {label} (size={q.maxsize})")


def drain_queue(q: Queue, sentinel: object) -> tuple[list[Any], bool]:
    out: list[Any] = []
    seen = False
    while True:
        try:
            x = q.get_nowait()
        except Empty:
            break
        if x is sentinel:
            seen = True
            break
        out.append(x)
    return out, seen


def adaptive_poll(did_work: bool, idle_streak: int) -> tuple[int, int]:
    if did_work:
        return 0, POLL_BASE_MS
    idle_streak = min(idle_streak + 1, POLL_MAX_MS)
    return idle_streak, min(POLL_BASE_MS + idle_streak, POLL_MAX_MS)


def write_broker_port(port: int, *, port_file: Path | None = None):
    path = port_file if port_file is not None else _PORT_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"port": port}))
    for _ in range(PORT_FILE_REPLACE_RETRIES):
        try:
            tmp.replace(path)
            return
        except PermissionError:
            time.sleep(PORT_FILE_REPLACE_RETRY_SEC)
    tmp.replace(path)


def read_broker_port(timeout: float = 5.0, *, port_file: Path | None = None) -> int | None:
    path = port_file if port_file is not None else _PORT_FILE
    end = time.time() + timeout
    while True:
        try:
            data = json.loads(path.read_text())
            return int(data["port"])
        except (OSError, KeyError, ValueError):
            if time.time() > end:
                return None
            time.sleep(0.1)


def port_file_stamp(port_file: Path) -> tuple[int, bytes] | None:
    try:
        return port_file.stat().st_mtime_ns, port_file.read_bytes()
    except FileNotFoundError:
        return None


def remove_broker_port(*, port_file: Path | None = None):
    path = port_file if port_file is not None else _PORT_FILE
    try:
        path.unlink(missing_ok=True)
    except Exception as e:
        from ..logs import AppLogger

        AppLogger.debug(f"remove_broker_port failed: {e}")

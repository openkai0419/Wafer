from __future__ import annotations
import contextlib
import json
import time
from pathlib import Path
from queue import Empty, Full, Queue

import zmq

from source.utils.paths import resolve_data_path
import threading as _threading
_drop_counter = [0]
_drop_count_lock = _threading.Lock()


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
BROKER_QUEUE_MAX = 1000
NODE_QUEUE_MAX = 200
RECONNECT_FORCE_INTERVAL = 5.0
ZMQ_SNDTIMEO_MS = 800
ZMQ_RCVTIMEO_MS = 800

_PORT_FILE = Path(resolve_data_path('ipc/broker.json'))


def tune_socket(sock):
    for opt, val in ((zmq.SNDTIMEO, ZMQ_SNDTIMEO_MS), (zmq.RCVTIMEO, ZMQ_RCVTIMEO_MS)):
        try:
            sock.setsockopt(opt, val)
        except Exception:
            pass


def close_socket(sock):
    try:
        sock.setsockopt(zmq.LINGER, 0)
    except Exception:
        pass
    try:
        sock.close()
    except Exception:
        pass


def try_put(q: Queue, item):
    try:
        q.put_nowait(item)
    except Full:
        with contextlib.suppress(Empty):
            q.get_nowait()
        try:
            q.put_nowait(item)
        except Full:
            return False
        with _drop_count_lock:
            _drop_counter[0] += 1
            count = _drop_counter[0]
        if count <= 5 or count % 100 == 0:
            from source.utils.logs import AppLogger
            AppLogger.debug(f'zmq queue eviction (total={count})')
        return True
    return True


def drain_queue(q: Queue, sentinel):
    out = []
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


def adaptive_poll(did_work, idle_streak):
    if did_work:
        return 0, POLL_BASE_MS
    idle_streak = min(idle_streak + 1, POLL_MAX_MS)
    return idle_streak, min(POLL_BASE_MS + idle_streak, POLL_MAX_MS)


def write_broker_port(port: int):
    _PORT_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = _PORT_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps({'port': port}))
    tmp.replace(_PORT_FILE)


def read_broker_port(timeout: float = 5.0) -> int | None:
    end = time.time() + timeout
    while True:
        try:
            data = json.loads(_PORT_FILE.read_text())
            return int(data['port'])
        except Exception:
            if time.time() > end:
                return None
            time.sleep(0.1)


def remove_broker_port():
    try:
        _PORT_FILE.unlink(missing_ok=True)
    except Exception:
        pass

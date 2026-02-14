from __future__ import annotations
import contextlib
from queue import Empty, Full, Queue

import zmq

HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
POLL_BASE_MS = 10
POLL_MAX_MS = 50
DEFAULT_PORT = 57556
BROKER_QUEUE_MAX = 1000
NODE_QUEUE_MAX = 200
ZMQ_SNDTIMEO_MS = 800
ZMQ_RCVTIMEO_MS = 800


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
            pass


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

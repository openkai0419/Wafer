# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import threading
import time
import uuid
import collections
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty

import zmq

from ..common.profiling import logger
from .ipc_utils import write_port, read_port, parse_port
from ..constants import APP_FILE_NAME

HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
PRUNE_INTERVAL = 1
DEFAULT_PORT = 57556

BROKER_SEND_QUEUE_MAXSIZE = 1000
NODE_SEND_QUEUE_MAXSIZE = 200

ZMQ_SNDHWM = 100
ZMQ_RCVHWM = 100
ZMQ_SNDTIMEO_MS = 800
ZMQ_RCVTIMEO_MS = 800

MonoTime = time.monotonic
_SEP = b"\x1f"

class Role(str, Enum):
    COMMUNICATOR = "communicator"
    COLLECTOR = "collector"
    VIEWER = "viewer"


def _to_b(x):
    return x if isinstance(x, (bytes, bytearray)) else str(x).encode("utf-8")


def setopts(sock, opts):
    for k, v in opts.items():
        with contextlib.suppress(Exception):
            sock.setsockopt(k, v)

def _tune(sock):
    setopts(
        sock,
        {
            zmq.RCVHWM: ZMQ_RCVHWM,
            zmq.SNDTIMEO: ZMQ_SNDTIMEO_MS,
            zmq.RCVTIMEO: ZMQ_RCVTIMEO_MS,
        },
    )
    setopts(
        sock,
        {
            zmq.TCP_KEEPALIVE: 1,
            zmq.TCP_KEEPALIVE_CNT: 5,
            zmq.TCP_KEEPALIVE_IDLE: 10,
            zmq.TCP_KEEPALIVE_INTVL: 2,
        },
    )


def _close_linger0(sock):
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.LINGER, 0)
    with contextlib.suppress(Exception):
        sock.close()


def _try_put(q, item):
    try:
        q.put_nowait(item)
        return True
    except Exception:
        with contextlib.suppress(Empty):
            q.get_nowait()
        try:
            q.put_nowait(item)
            return True
        except Exception:
            logger.info("queue full: drop message")
            return False


def _force_put(q, item):
    while not _try_put(q, item):
        with contextlib.suppress(Empty):
            q.get_nowait()
        time.sleep(0.001)


def _drain_queue(q, sentinel):
    items, sentinel_seen = [], False
    while True:
        try:
            x = q.get_nowait()
        except Empty:
            break
        if x is sentinel:
            sentinel_seen = True
            break
        items.append(x)
    return items, sentinel_seen


def _adaptive_poll(did_work, idle_streak, base_ms, max_ms):
    if did_work:
        return 0, base_ms
    idle_streak = min(idle_streak + 1, max_ms)
    return idle_streak, min(base_ms + idle_streak, max_ms)


@dataclass(slots=True)
class MessageEnvelope:
    _app_b: bytes
    _target_b: bytes
    _table_b: bytes
    _topic_b: bytes
    _msg_b: bytes
    request_id: str = None
    _app_s: str = None
    _target_s: str = None
    _table_s: str = None
    _topic_s: str = None
    _msg_s: str = None

    @classmethod
    def build(cls, *, APP_NAME=APP_FILE_NAME, targetprocess="ALL", table="", topic="", message=b"", request_id=None):
        msg_b = b"" if message is None else _to_b(message)
        return cls(
            _app_b=_to_b(APP_NAME),
            _target_b=_to_b(targetprocess),
            _table_b=_to_b(table),
            _topic_b=_to_b(topic),
            _msg_b=bytes(msg_b),
            request_id=request_id,
        )

    def to_frames(self):
        return (
            self._app_b,
            self._target_b,
            self._table_b,
            self._topic_b,
            self._msg_b,
            *((self.request_id.encode("utf-8"),) if self.request_id else ()),
        )

    @staticmethod
    def from_frames(frames):
        if len(frames) < 5:
            return None
        rid = frames[5].decode("utf-8", "ignore") if len(frames) > 5 else None
        return MessageEnvelope(
            _app_b=bytes(frames[0]),
            _target_b=bytes(frames[1]),
            _table_b=bytes(frames[2]),
            _topic_b=bytes(frames[3]),
            _msg_b=bytes(frames[4]),
            request_id=rid,
        )

    @property
    def app_name(self):
        if self._app_s is None:
            self._app_s = self._app_b.decode("utf-8", "ignore")
        return self._app_s

    @property
    def targetprocess(self):
        if self._target_s is None:
            self._target_s = self._target_b.decode("utf-8", "ignore")
        return self._target_s

    @property
    def table(self):
        if self._table_s is None:
            self._table_s = self._table_b.decode("utf-8", "ignore")
        return self._table_s

    @property
    def topic(self):
        if self._topic_s is None:
            self._topic_s = self._topic_b.decode("utf-8", "ignore")
        return self._topic_s

    @property
    def message(self):
        if self._msg_s is None:
            self._msg_s = self._msg_b.decode("utf-8", "ignore")
        return self._msg_s

    @property
    def message_bytes(self):
        return self._msg_b


@dataclass(slots=True)
class PeerMeta:
    role_b: bytes
    node_id_b: bytes
    app_name_b: bytes
    last_seen: float = 0.0

    @property
    def role_lower(self):
        return (self.role_b or b"").lower()


class _CoalescingKeyQueue:
    def __init__(self, maxsize):
        self.maxsize = maxsize
        self._dq = collections.deque()
        self._map = {}
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._dq)

    def put(self, key, value):
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old_key = self._dq.popleft()
                self._map.pop(old_key, None)
            self._dq.append(key)
            self._map[key] = value

    def get_nowait(self):
        with self._lock:
            if not self._dq:
                raise Empty
            while self._dq:
                key = self._dq.popleft()
                val = self._map.pop(key, None)
                if val is not None:
                    return key, val
            raise Empty

    def drain_nowait(self):
        out = []
        while True:
            try:
                out.append(self.get_nowait())
            except Empty:
                break
        return out


class ZMQBroker:
    def __init__(self, bind_addr=None):
        self.ctx = zmq.Context.instance()
        self.bind_addr = bind_addr
        self.router = self.ctx.socket(zmq.ROUTER)
        _tune(self.router)
        with contextlib.suppress(Exception):
            self.router.setsockopt(zmq.ROUTER_MANDATORY, 1)
        self._stop = threading.Event()
        self.nodes = {}
        self.active_nodes = {}
        self._index_by_role = {}
        self._index_by_app = {}
        self._direct_q = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._broadcast_q = _CoalescingKeyQueue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()
        self._lock = threading.RLock()
        self._io_thread = None
        self._prune_thread = None
        self._base_poll_timeout_ms = 10
        self._max_poll_timeout_ms = 50

    def _bind(self):
        saved = read_port()
        if self.bind_addr is None:
            if saved:
                try:
                    addr = f"tcp://localhost:{saved}"
                    self.router.bind(addr)
                    write_port(saved)
                    return addr
                except zmq.ZMQError:
                    pass
            try:
                addr = f"tcp://localhost:{DEFAULT_PORT}"
                self.router.bind(addr)
                write_port(DEFAULT_PORT)
                return addr
            except zmq.ZMQError:
                port = self.router.bind_to_random_port("tcp://localhost")
                addr = f"tcp://localhost:{port}"
                write_port(port)
                return addr
        else:
            port = parse_port(self.bind_addr)
            addr = f"tcp://localhost:{port}"
            self.router.bind(addr)
            write_port(port)
            return addr

    def _index_add(self, ident, meta):
        role = meta.role_lower
        app = meta.app_name_b or b""
        self._index_by_role.setdefault(role, set()).add(ident)
        self._index_by_app.setdefault(app, set()).add(ident)

    def _index_remove(self, ident, meta):
        if not meta:
            return
        role = meta.role_lower
        app = meta.app_name_b or b""
        if s := self._index_by_role.get(role):
            s.discard(ident)
        if s := self._index_by_app.get(app):
            s.discard(ident)

    def _prune_loop(self):
        while not self._stop.is_set():
            now = MonoTime()
            with self._lock:
                stale = [k for k, v in self.active_nodes.items() if now - (v.last_seen or 0) > HEARTBEAT_TIMEOUT]
                for ident in stale:
                    meta = self.active_nodes.pop(ident, None)
                    self.nodes.pop(ident, None)
                    self._index_remove(ident, meta)
            time.sleep(PRUNE_INTERVAL)

    def _pick_broadcast_idents(self, app_b, target_b):
        with self._lock:
            if target_b == b"all":
                return list(self._index_by_app.get(app_b, set()))
            by_role = self._index_by_role.get(target_b, set())
            by_app = self._index_by_app.get(app_b, set())
            base, other = (by_role, by_app) if len(by_role) <= len(by_app) else (by_app, by_role)
            return [i for i in base if i in other]

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self.router, zmq.POLLIN)
        poll_timeout_ms = self._base_poll_timeout_ms
        idle_streak = 0
        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_timeout_ms))
            except zmq.ZMQError:
                break
            did_work = False
            if events.get(self.router) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.router.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    if len(frames) >= 2:
                        ident, payloads = bytes(frames[0]), frames[1:]
                        if len(payloads) == 1:
                            self._handle_router_recv_control(ident, bytes(payloads[0]))
                        else:
                            self._handle_router_recv_app(tuple(bytes(f) for f in payloads))
                        did_work = True
            direct_batch, sentinel_seen = _drain_queue(self._direct_q, self._sentinel)
            for ident, frames in direct_batch:
                try:
                    self.router.send_multipart((ident, *frames), copy=False)
                    did_work = True
                except zmq.Again:
                    logger.info("Broker ROUTER send timeout; dropping direct message to %r", ident)
                except zmq.ZMQError as e:
                    logger.info("Broker ROUTER send error to %r: %s", ident, e)
            if sentinel_seen:
                self._stop.set()
                break
            for _key, frames in self._broadcast_q.drain_nowait():
                app_b, target_b = frames[0], (frames[1] or b"ALL").lower()
                for ident in self._pick_broadcast_idents(app_b, target_b):
                    try:
                        self.router.send_multipart((ident, *frames), copy=False)
                        did_work = True
                    except zmq.Again:
                        logger.info("Broker ROUTER send timeout; dropping broadcast to %r", ident)
                    except zmq.ZMQError as e:
                        logger.info("Broker ROUTER send error to %r: %s", ident, e)
            idle_streak, poll_timeout_ms = _adaptive_poll(did_work, idle_streak, self._base_poll_timeout_ms, self._max_poll_timeout_ms)
        _close_linger0(self.router)

    def _handle_router_recv_control(self, ident, payload):
        now = MonoTime()
        text = payload.decode("utf-8", errors="ignore")
        if text.startswith("register:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                return
            role_b = parts[1].encode("utf-8")
            node_id_b = parts[2].encode("utf-8")
            app_name_b = parts[3].encode("utf-8")
            with self._lock:
                if parts[4] == "enable":
                    meta = PeerMeta(role_b, node_id_b, app_name_b, now)
                    self.nodes[ident] = meta
                    self.active_nodes[ident] = meta
                    self._index_add(ident, meta)
                else:
                    self.nodes.pop(ident, None)
                    old = self.active_nodes.pop(ident, None)
                    self._index_remove(ident, old)
            return
        if text.startswith("heartbeat:"):
            parts = text.split(":", 4)
            if len(parts) < 4:
                return
            with self._lock:
                m = self.active_nodes.setdefault(ident, PeerMeta(parts[1].encode("utf-8"), parts[2].encode("utf-8"), parts[3].encode("utf-8")))
                m.role_b, m.node_id_b, m.app_name_b, m.last_seen = (parts[1].encode("utf-8"), parts[2].encode("utf-8"), parts[3].encode("utf-8"), now)
                self._index_add(ident, m)
            return
        if text.startswith("get_count:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                return
            role_and_tail = parts[4] if len(parts) > 4 else ""
            role_str, req_id = role_and_tail, None
            if "," in role_and_tail:
                role_str, tail = role_and_tail.split(",", 1)
                if "request_id:" in tail:
                    req_id = tail.split("request_id:", 1)[1]
            with self._lock:
                counts = {}
                for v in self.active_nodes.values():
                    r = v.role_lower.decode("utf-8", "ignore")
                    counts[r] = counts.get(r, 0) + 1
            counts_str = ",".join(f"{r}:{c}" for r, c in counts.items())
            reply_env = MessageEnvelope.build(APP_NAME=parts[3] if len(parts) > 3 else APP_FILE_NAME, targetprocess="ALL", table="", topic="control.count.reply", message=counts_str, request_id=req_id)
            _force_put(self._direct_q, (ident, reply_env.to_frames()))
            return

    def _handle_router_recv_app(self, frames):
        if len(frames) < 5:
            return
        key = _SEP.join(((frames[1] or b"ALL").lower(), frames[2], frames[3]))
        self._broadcast_q.put(key, frames)

    def start(self):
        addr = self._bind()
        logger.info(f"Broker bound: ROUTER={addr}")
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        self._prune_thread = threading.Thread(target=self._prune_loop, daemon=True)
        self._prune_thread.start()

    def stop(self):
        self._stop.set()
        _force_put(self._direct_q, self._sentinel)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)
        if self._prune_thread:
            self._prune_thread.join(timeout=2.0)


class ZMQNode:
    def __init__(self, role, app_name=APP_FILE_NAME, on_message=None, count="disable"):
        if not isinstance(role, Role):
            raise TypeError("role must be a Role")
        self.role = role
        self.app_name = app_name
        self.on_message = on_message
        self.node_id = f"{role.value}-{uuid.uuid4().hex[:8]}"
        self.count = count
        self.ctx = zmq.Context.instance()
        self._stop = threading.Event()
        self._threads = []
        port = read_port() or DEFAULT_PORT
        self._current_addr = f"tcp://localhost:{port}"
        self.dealer = self.ctx.socket(zmq.DEALER)
        _tune(self.dealer)
        with contextlib.suppress(Exception):
            self.dealer.setsockopt(zmq.IMMEDIATE, 1)
        with contextlib.suppress(Exception):
            self.dealer.setsockopt(zmq.TCP_NODELAY, 1)
        self.dealer.setsockopt(zmq.IDENTITY, self.node_id.encode("utf-8"))
        if self._current_addr:
            with contextlib.suppress(Exception):
                self.dealer.connect(self._current_addr)
        self._out_q = Queue(maxsize=NODE_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()
        self._pending = {}
        self._pending_lock = threading.Lock()
        self._io_thread = None
        self._base_poll_timeout_ms = 10
        self._max_poll_timeout_ms = 50

    def start(self):
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        self._enqueue_control(f"register:{self.role.value}:{self.node_id}:{self.app_name}:{self.count}")
        if self.count == "enable":
            t_hb = threading.Thread(target=self._heartbeat_loop, daemon=True)
            t_hb.start()
            self._threads.append(t_hb)

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self.dealer, zmq.POLLIN)
        poll_timeout_ms = self._base_poll_timeout_ms
        idle_streak = 0
        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_timeout_ms))
            except zmq.ZMQError:
                break
            did_work = False
            if events.get(self.dealer) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.dealer.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    if len(frames) > 1:
                        frames_b = [bytes(f) for f in frames]
                        self._handle_dealer_recv_frames(frames_b)
                        did_work = True
            batch, sentinel_seen = _drain_queue(self._out_q, self._sentinel)
            for data in batch:
                try:
                    if isinstance(data, tuple):
                        self.dealer.send_multipart(list(data), copy=False)
                    else:
                        self.dealer.send(data, copy=False)
                    did_work = True
                except zmq.Again:
                    logger.info("Node %s DEALER send timeout; dropping message", self.node_id)
                except Exception as e:
                    logger.info("Node %s DEALER send error: %s", self.node_id, e)
            if sentinel_seen:
                self._stop.set()
                break
            idle_streak, poll_timeout_ms = _adaptive_poll(did_work, idle_streak, self._base_poll_timeout_ms, self._max_poll_timeout_ms)
        _close_linger0(self.dealer)

    def _enqueue_control(self, payload):
        _force_put(self._out_q, payload.encode("utf-8"))

    def _handle_dealer_recv_frames(self, frames):
        env = MessageEnvelope.from_frames(frames)
        if not env:
            return
        if env.request_id:
            with self._pending_lock:
                tup = self._pending.get(env.request_id)
            if tup:
                expect_topic, q = tup
                if env.topic == expect_topic:
                    _try_put(q, env)
                    return
        if env._app_b != self.app_name.encode("utf-8"):
            return
        tp = (env._target_b or b"ALL").lower()
        if tp not in (b"all", self.role.value.encode("utf-8")):
            return
        if self.on_message:
            with contextlib.suppress(Exception):
                self.on_message(env)

    def _heartbeat_loop(self):
        wire = f"heartbeat:{self.role.value}:{self.node_id}:{self.app_name}"
        while not self._stop.is_set():
            self._enqueue_control(wire)
            time.sleep(HEARTBEAT_INTERVAL)

    def send(self, *, targetprocess="ALL", table="", topic="", message=None):
        env = MessageEnvelope.build(APP_NAME=self.app_name, targetprocess=targetprocess, table=table, topic=topic, message=message)
        _try_put(self._out_q, env.to_frames())

    def request_count(self, role, timeout=5.0):
        role_str = (role.value if isinstance(role, Role) else str(role)).lower()
        env = self.request_control(expect_topic="control.count.reply", payload=f"get_count:{self.role.value}:{self.node_id}:{self.app_name}:{role_str}", timeout=timeout)
        if not env:
            return 0
        kv = dict((k.strip(), v.strip()) for k, v in (pair.split(":", 1) for pair in str(env.message).split(",") if ":" in pair))
        return int(kv.get(role_str, 0) or 0)

    def request_control(self, *, expect_topic, payload, timeout=5.0):
        rid = f"{self.node_id}-{uuid.uuid4().hex[:8]}"
        q = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = (expect_topic, q)
        try:
            self._enqueue_control(f"{payload},request_id:{rid}")
            try:
                return q.get(timeout=timeout)
            except Empty:
                return None
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def get_sub_count(self):
        return self.request_count(Role.VIEWER, 0.5)

    def stop(self):
        self._stop.set()
        _force_put(self._out_q, self._sentinel)
        for t in self._threads:
            t.join(timeout=2.0)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)

# -*- coding: utf-8 -*-
from __future__ import annotations

import contextlib
import threading
import time
import uuid
import errno
import collections
from dataclasses import dataclass
from enum import Enum
from queue import Queue, Empty

import zmq

# ---- minimal deps expected in your project; replace with your logger if needed
from ..common.profiling import logger
from .ipc_utils import write_port, read_port, parse_port
from ..constants import APP_FILE_NAME

# ---- constants (trimmed)
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
POLL_BASE_MS = 10
POLL_MAX_MS = 50
DEFAULT_PORT = 57556

BROKER_SEND_QUEUE_MAXSIZE = 1000
NODE_SEND_QUEUE_MAXSIZE = 200

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


def _tune(sock):
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.SNDTIMEO, ZMQ_SNDTIMEO_MS)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.RCVTIMEO, ZMQ_RCVTIMEO_MS)


def _close_linger0(sock):
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.LINGER, 0)
    with contextlib.suppress(Exception):
        sock.close()


def _try_put(q: Queue, item) -> bool:
    try:
        q.put_nowait(item)
        return True
    except Exception:
        with contextlib.suppress(Empty):
            q.get_nowait()  # drop oldest
        try:
            q.put_nowait(item)
            return True
        except Exception:
            logger.info("queue full: drop message")
            return False


def _drain(q: Queue, sentinel):
    out, seen = [], False
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


def _adaptive_poll(did_work: bool, idle_streak: int, base_ms: int, max_ms: int):
    if did_work:
        return 0, base_ms
    idle_streak = min(idle_streak + 1, max_ms)
    return idle_streak, min(base_ms + idle_streak, max_ms)


# ---- Envelope
@dataclass(slots=True)
class MessageEnvelope:
    _app_b: bytes
    _target_b: bytes
    _table_b: bytes
    _topic_b: bytes
    _msg_b: bytes
    request_id: str | None = None

    _app_s: str | None = None
    _target_s: str | None = None
    _table_s: str | None = None
    _topic_s: str | None = None
    _msg_s: str | None = None

    @classmethod
    def build(
        cls,
        *,
        APP_NAME: str = APP_FILE_NAME,
        targetprocess: str = "ALL",
        table: str = "",
        topic: str = "",
        message: bytes | str | None = b"",
        request_id: str | None = None,
    ):
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
    def app_name(self) -> str:
        if self._app_s is None:
            self._app_s = self._app_b.decode("utf-8", "ignore")
        return self._app_s

    @property
    def targetprocess(self) -> str:
        if self._target_s is None:
            self._target_s = self._target_b.decode("utf-8", "ignore")
        return self._target_s

    @property
    def table(self) -> str:
        if self._table_s is None:
            self._table_s = self._table_b.decode("utf-8", "ignore")
        return self._table_s

    @property
    def topic(self) -> str:
        if self._topic_s is None:
            self._topic_s = self._topic_b.decode("utf-8", "ignore")
        return self._topic_s

    @property
    def message(self) -> str:
        if self._msg_s is None:
            self._msg_s = self._msg_b.decode("utf-8", "ignore")
        return self._msg_s

    @property
    def message_bytes(self) -> bytes:
        return self._msg_b


# ---- Coalescing queue (keyed, keep latest per key; FIFO for keys)
class _CoalescingKeyQueue:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._dq = collections.deque()
        self._map: dict[bytes, tuple] = {}
        self._lock = threading.Lock()

    def put(self, key: bytes, value: tuple):
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old = self._dq.popleft()
                self._map.pop(old, None)
            self._dq.append(key)
            self._map[key] = value

    def drain_nowait(self):
        out = []
        with self._lock:
            while self._dq:
                k = self._dq.popleft()
                v = self._map.pop(k, None)
                if v is not None:
                    out.append((k, v))
        return out


# ---- Broker (lite)
class ZMQBroker:
    def __init__(self, bind_addr: str | None = None):
        self.ctx = zmq.Context.instance()
        self.router = self.ctx.socket(zmq.ROUTER)
        _tune(self.router)
        with contextlib.suppress(Exception):
            self.router.setsockopt(zmq.ROUTER_MANDATORY, 1)

        # bind
        saved = read_port()
        if bind_addr is None:
            port = parse_port(saved) if saved else DEFAULT_PORT
            addr = f"tcp://localhost:{port}"
            try:
                self.router.bind(addr)
                write_port(port)
                self.bind_addr = addr
            except zmq.ZMQError:
                port = self.router.bind_to_random_port("tcp://localhost")
                self.bind_addr = f"tcp://localhost:{port}"
                write_port(port)
        else:
            port = parse_port(bind_addr)
            addr = f"tcp://localhost:{port}"
            self.router.bind(addr)
            write_port(port)
            self.bind_addr = addr

        # state
        self._stop = threading.Event()
        self._direct_q: Queue = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._broadcast_q = _CoalescingKeyQueue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()

        # active peers: ident -> PeerMeta
        self._peers: dict[bytes, tuple[bytes, bytes, float]] = {}
        # indexes
        self._by_role: dict[bytes, set[bytes]] = {}
        self._by_app: dict[bytes, set[bytes]] = {}
        self._lock = threading.RLock()

        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._prune_thread = threading.Thread(target=self._prune_loop, daemon=True)

    # --- indexing helpers
    def _index_add(self, ident: bytes, role_b: bytes, app_b: bytes):
        self._by_role.setdefault(role_b, set()).add(ident)
        self._by_app.setdefault(app_b, set()).add(ident)

    def _index_remove(self, ident: bytes, role_b: bytes, app_b: bytes):
        if role_b in self._by_role:
            self._by_role[role_b].discard(ident)
        if app_b in self._by_app:
            self._by_app[app_b].discard(ident)

    def _prune_loop(self):
        while not self._stop.is_set():
            now = MonoTime()
            with self._lock:
                stale = [i for i, (_, _, ts) in self._peers.items() if now - ts > HEARTBEAT_TIMEOUT]
                for ident in stale:
                    role_b, app_b, _ = self._peers.pop(ident, (b"", b"", 0))
                    self._index_remove(ident, role_b, app_b)
            time.sleep(1)

    def _pick_broadcast_targets(self, app_b: bytes, target_b: bytes) -> list[bytes]:
        with self._lock:
            if target_b == b"all":
                return list(self._by_app.get(app_b, set()))
            by_role = self._by_role.get(target_b, set())
            by_app = self._by_app.get(app_b, set())
            # intersect efficiently
            base, other = (by_role, by_app) if len(by_role) <= len(by_app) else (by_app, by_role)
            return [i for i in base if i in other]

    def _handle_control(self, ident: bytes, payload: bytes):
        text = payload.decode("utf-8", "ignore")
        now = MonoTime()
        if text.startswith("register:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                return
            role_b = parts[1].encode()
            node_id_b = parts[2].encode()  # kept for parity (unused here)
            app_b = parts[3].encode()
            with self._lock:
                if parts[4] == "enable":
                    self._peers[ident] = (role_b, app_b, now)
                    self._index_add(ident, role_b, app_b)
                else:
                    role_b_old, app_b_old, _ = self._peers.pop(ident, (b"", b"", 0))
                    self._index_remove(ident, role_b_old, app_b_old)
            return
        if text.startswith("heartbeat:"):
            parts = text.split(":", 4)
            if len(parts) < 4:
                return
            role_b = parts[1].encode()
            app_b = parts[3].encode()
            with self._lock:
                self._peers[ident] = (role_b, app_b, now)
                self._index_add(ident, role_b, app_b)
            return
        if text.startswith("get_count:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                return
            role_tail = parts[4]
            role_str, req_id = role_tail, None
            if "," in role_tail:
                role_str, tail = role_tail.split(",", 1)
                if "request_id:" in tail:
                    req_id = tail.split("request_id:", 1)[1]
            # count by role among active peers
            with self._lock:
                counts: dict[str, int] = {}
                for role_b, _app_b, _ts in self._peers.values():
                    r = role_b.decode("utf-8", "ignore")
                    counts[r] = counts.get(r, 0) + 1
            counts_str = ",".join(f"{r}:{c}" for r, c in counts.items())
            reply = MessageEnvelope.build(
                APP_NAME=parts[3] if len(parts) > 3 else APP_FILE_NAME,
                targetprocess="ALL",
                topic="control.count.reply",
                message=counts_str,
                request_id=req_id,
            )
            _try_put(self._direct_q, (ident, reply.to_frames()))
            return

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self.router, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS
        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_ms))
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
                            self._handle_control(ident, bytes(payloads[0]))
                        else:
                            # app frames: app, target, table, topic, msg, [rid]
                            f = tuple(bytes(f) for f in payloads)
                            app_b, target_b = f[0], (f[1] or b"ALL").lower()
                            key = _SEP.join((target_b, f[2], f[3]))
                            self._broadcast_q.put(key, f)
                        did_work = True
            # direct sends
            batch, sentinel = _drain(self._direct_q, self._sentinel)
            for ident, frames in batch:
                try:
                    self.router.send_multipart((ident, *frames), copy=False)
                    did_work = True
                except zmq.Again:
                    logger.info("broker: drop direct (timeout)")
                except zmq.ZMQError as e:
                    logger.info("broker: send error %s", e)
            if sentinel:
                self._stop.set()
                break
            # broadcasts (coalesced)
            for _key, frames in self._broadcast_q.drain_nowait():
                app_b, target_b = frames[0], (frames[1] or b"ALL").lower()
                for ident in self._pick_broadcast_targets(app_b, target_b):
                    try:
                        self.router.send_multipart((ident, *frames), copy=False)
                        did_work = True
                    except zmq.Again:
                        logger.info("broker: drop broadcast (timeout)")
                    except zmq.ZMQError as e:
                        if e.errno == errno.EHOSTUNREACH:
                            pass
                        else:
                            logger.info("broker: bcast error %s", e)

            idle_streak, poll_ms = _adaptive_poll(did_work, idle_streak, POLL_BASE_MS, POLL_MAX_MS)
        _close_linger0(self.router)

    def start(self):
        logger.info(f"BrokerLite bound: {self.bind_addr}")
        self._direct_q = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._io_thread.start()
        self._prune_thread.start()

    def stop(self):
        self._stop.set()
        _try_put(self._direct_q, self._sentinel)
        self._io_thread.join(timeout=2.0)
        self._prune_thread.join(timeout=2.0)


# ---- Node (lite)
class ZMQNode:
    def __init__(self, role: Role, app_name: str = APP_FILE_NAME, on_message=None, count: str = "disable"):
        if not isinstance(role, Role):
            raise TypeError("role must be a Role")
        self.role = role
        self.app_name = app_name
        self.on_message = on_message
        self.count = count
        self.node_id = f"{role.value}-{uuid.uuid4().hex[:8]}"

        self.ctx = zmq.Context.instance()
        self.dealer = self.ctx.socket(zmq.DEALER)
        _tune(self.dealer)
        with contextlib.suppress(Exception):
            self.dealer.setsockopt(zmq.IMMEDIATE, 1)
        with contextlib.suppress(Exception):
            self.dealer.setsockopt(zmq.TCP_NODELAY, 1)
        self.dealer.setsockopt(zmq.IDENTITY, self.node_id.encode("utf-8"))

        port = read_port() or DEFAULT_PORT
        self._addr = f"tcp://localhost:{port}"
        with contextlib.suppress(Exception):
            self.dealer.connect(self._addr)

        self._out_q: Queue = Queue(maxsize=NODE_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()

        self._pending: dict[str, tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()

        self._stop = threading.Event()
        self._io_thread: threading.Thread | None = None
        self._hb_thread: threading.Thread | None = None

    def start(self):
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        self._enqueue_control(f"register:{self.role.value}:{self.node_id}:{self.app_name}:{self.count}")
        if self.count == "enable":
            self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
            self._hb_thread.start()

    def _enqueue_control(self, payload: str):
        _try_put(self._out_q, payload.encode("utf-8"))

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self.dealer, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS
        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_ms))
            except zmq.ZMQError:
                break
            did_work = False
            if events.get(self.dealer) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.dealer.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    frames_b = [bytes(f) for f in frames]
                    self._handle_recv(frames_b)
                    did_work = True
            batch, sentinel = _drain(self._out_q, self._sentinel)
            for data in batch:
                try:
                    if isinstance(data, tuple):
                        self.dealer.send_multipart(list(data), copy=False)
                    else:
                        self.dealer.send(data, copy=False)
                    did_work = True
                except zmq.Again:
                    pass
                    #logger.info("node: drop send (timeout)")
                except Exception as e:
                    logger.info("node: send error %s", e)
            if sentinel:
                self._stop.set()
                break
            idle_streak, poll_ms = _adaptive_poll(did_work, idle_streak, POLL_BASE_MS, POLL_MAX_MS)
        _close_linger0(self.dealer)

    def _handle_recv(self, frames: list[bytes]):
        env = MessageEnvelope.from_frames(frames)
        if not env:
            return
        # request-response path
        if env.request_id:
            with self._pending_lock:
                tup = self._pending.get(env.request_id)
            if tup:
                expect_topic, q = tup
                if env.topic == expect_topic:
                    _try_put(q, env)
                    return
        # broadcast path: app and target filter
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

    # --- public send APIs
    def send(self, *, targetprocess: str = "ALL", table: str = "", topic: str = "", message=None):
        env = MessageEnvelope.build(APP_NAME=self.app_name, targetprocess=targetprocess, table=table, topic=topic, message=message)
        _try_put(self._out_q, env.to_frames())

    def request_control(self, *, expect_topic: str, payload: str, timeout: float = 5.0) -> MessageEnvelope | None:
        rid = f"{self.node_id}-{uuid.uuid4().hex[:8]}"
        q: Queue = Queue(maxsize=1)
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

    def request_count(self, role: Role | str, timeout: float = 5.0) -> int:
        role_str = (role.value if isinstance(role, Role) else str(role)).lower()
        env = self.request_control(
            expect_topic="control.count.reply",
            payload=f"get_count:{self.role.value}:{self.node_id}:{self.app_name}:{role_str}",
            timeout=timeout,
        )
        if not env:
            return 0
        kv = dict(
            (k.strip(), v.strip()) for k, v in (
                pair.split(":", 1) for pair in str(env.message).split(",") if ":" in pair
            )
        )
        return int(kv.get(role_str, 0) or 0)

    def get_sub_count(self) -> int:
        return self.request_count(Role.VIEWER, 0.5)

    def stop(self):
        self._stop.set()
        _try_put(self._out_q, self._sentinel)
        if self._hb_thread:
            self._hb_thread.join(timeout=2.0)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)

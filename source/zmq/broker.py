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
from typing import Optional, Callable, List, Tuple, Union, Dict, Literal, Any

import zmq

from ..common.profiling import logger
from .ipc_utils import write_port, read_port, parse_port
from ..constants import APP_FILE_NAME
#from ..common.memprofiling import mem_usage

# ==================== Tunables ====================
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
PRUNE_INTERVAL = 1
DEFAULT_PORT = 57556

BROKER_SEND_QUEUE_MAXSIZE = 100_00
NODE_SEND_QUEUE_MAXSIZE = 10_00

# ---- ZeroMQ tuning defaults ----
ZMQ_SNDHWM = 500
ZMQ_RCVHWM = 500
ZMQ_SNDTIMEO_MS = 1500
ZMQ_RCVTIMEO_MS = 1500

MonoTime = time.monotonic
_SEP = b"\x1f"

# ===== Type aliases =====
Frames = Tuple[bytes, ...]
Ident = bytes

# ==================== Rate-limited logging ====================
class _RateLimiter:
    def __init__(self, rate_per_sec: float, burst: int):
        self.rate = float(rate_per_sec)
        self.capacity = int(burst)
        self.tokens = float(burst)
        self.last = MonoTime()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            now = MonoTime()
            elapsed = now - self.last
            self.last = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            if self.tokens >= 1.0:
                self.tokens -= 1.0
                return True
            return False

_warn_limiter = _RateLimiter(rate_per_sec=5, burst=10)

def warn_limited(msg: str, *args):
    if _warn_limiter.allow():
        logger.warning(msg, *args)

# ==================== Enum ====================
class Role(str, Enum):
    COMMUNICATOR = "communicator"
    COLLECTOR = "collector"
    VIEWER = "viewer"

# ==================== Utils ====================

def _to_b(x: Union[str, bytes, bytearray]) -> bytes:
    return x if isinstance(x, (bytes, bytearray)) else str(x).encode("utf-8")

def setopts(sock, opts: Dict[int, int]):
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


def _try_put(q: Queue, item) -> bool:
    try:
        q.put_nowait(item)
        return True
    except Exception:
        with contextlib.suppress(Empty):
            q.get_nowait()  # drop 1 old (latest wins)
        try:
            q.put_nowait(item)
            return True
        except Exception:
            warn_limited("queue full: drop message")
            return False


def _force_put(q: Queue, item) -> None:
    while not _try_put(q, item):
        with contextlib.suppress(Empty):
            q.get_nowait()
        time.sleep(0.001)


def _drain_queue(q: Queue, sentinel: object):
    """Return (items, sentinel_seen)."""
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

def _adaptive_poll(did_work: bool, idle_streak: int, base_ms: int, max_ms: int):
    if did_work:
        return 0, base_ms
    idle_streak = min(idle_streak + 1, max_ms)
    return idle_streak, min(base_ms + idle_streak, max_ms)

# ==================== Message ====================
@dataclass(slots=True)
class MessageEnvelope:
    """bytes 中心の軽量エンベロープ。decode は必要時のみ行い、結果をキャッシュ。
    フレーム: [APP_NAME, TARGET, TABLE, TOPIC, MESSAGE, (optional) REQUEST_ID]
    """
    _app_b: bytes
    _target_b: bytes
    _table_b: bytes
    _topic_b: bytes
    _msg_b: bytes
    request_id: Optional[str] = None

    _app_s: Optional[str] = None
    _target_s: Optional[str] = None
    _table_s: Optional[str] = None
    _topic_s: Optional[str] = None
    _msg_s: Optional[str] = None

    @classmethod
    def build(
        cls,
        *,
        APP_NAME: Union[str, bytes] = APP_FILE_NAME,
        targetprocess: Union[str, bytes] = "ALL",
        table: Union[str, bytes] = "",
        topic: Union[str, bytes] = "",
        message: Optional[Union[str, bytes]] = b"",
        request_id: Optional[str] = None,
    ) -> "MessageEnvelope":
        msg_b = b"" if message is None else _to_b(message)
        return cls(
            _app_b=_to_b(APP_NAME),
            _target_b=_to_b(targetprocess),
            _table_b=_to_b(table),
            _topic_b=_to_b(topic),
            _msg_b=bytes(msg_b),
            request_id=request_id,
        )

    def to_frames(self) -> Frames:
        return (
            self._app_b,
            self._target_b,
            self._table_b,
            self._topic_b,
            self._msg_b,
            *((self.request_id.encode("utf-8"),) if self.request_id else ())
        )

    @staticmethod
    def from_frames(frames: List[bytes]) -> Optional["MessageEnvelope"]:
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

    # -------- lazy decode properties --------
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

# ==================== Helpers ====================
@dataclass(slots=True)
class PeerMeta:
    role_b: Optional[bytes]
    node_id_b: Optional[bytes]
    app_name_b: Optional[bytes]
    last_seen: float = 0.0

    @property
    def role_lower(self) -> bytes:
        return (self.role_b or b"").lower()

class _CoalescingKeyQueue:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._dq = collections.deque()                 # deque[bytes]
        self._map: Dict[bytes, Frames] = {}            # key -> frames
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._dq)

    def put(self, key: bytes, value: Frames) -> None:
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old_key = self._dq.popleft()
                self._map.pop(old_key, None)
            self._dq.append(key)
            self._map[key] = value

    def get_nowait(self) -> Tuple[bytes, Frames]:
        with self._lock:
            if not self._dq:
                raise Empty
            while self._dq:
                key = self._dq.popleft()
                val = self._map.pop(key, None)
                if val is not None:
                    return key, val
            raise Empty

    def drain_nowait(self) -> List[Tuple[bytes, Frames]]:
        out: List[Tuple[bytes, Frames]] = []
        while True:
            try:
                out.append(self.get_nowait())
            except Empty:
                break
        return out

# ==================== Broker ====================
class ZMQBroker:
    def __init__(self, bind_addr: Optional[str] = None):
        self.ctx = zmq.Context.instance()
        self.bind_addr = bind_addr

        self.router = self.ctx.socket(zmq.ROUTER)
        _tune(self.router)
        with contextlib.suppress(Exception):
            self.router.setsockopt(zmq.ROUTER_MANDATORY, 1)

        self._stop = threading.Event()

        # ident -> PeerMeta
        self.nodes: Dict[Ident, PeerMeta] = {}
        self.active_nodes: Dict[Ident, PeerMeta] = {}

        # broadcast 最適化用インデックス
        self._index_by_role: Dict[bytes, set[Ident]] = {}
        self._index_by_app: Dict[bytes, set[Ident]] = {}

        # キュー
        self._direct_q: "Queue[Tuple[Ident, Frames] | object]" = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._broadcast_q = _CoalescingKeyQueue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)

        self._sentinel = object()
        self._lock = threading.RLock()

        self._io_thread: Optional[threading.Thread] = None
        self._prune_thread: Optional[threading.Thread] = None

        self._base_poll_timeout_ms = 10
        self._max_poll_timeout_ms = 50

    # ---------- bind ----------
    def _bind(self) -> str:
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

    # ---------- index helpers ----------
    def _index_add(self, ident: Ident, meta: PeerMeta):
        role = meta.role_lower
        app = meta.app_name_b or b""
        self._index_by_role.setdefault(role, set()).add(ident)
        self._index_by_app.setdefault(app, set()).add(ident)

    def _index_remove(self, ident: Ident, meta: Optional[PeerMeta]):
        if not meta:
            return
        role = meta.role_lower
        app = meta.app_name_b or b""
        if s := self._index_by_role.get(role):
            s.discard(ident)
        if s := self._index_by_app.get(app):
            s.discard(ident)

    # ---------- prune thread ----------
    def _prune_loop(self):
        while not self._stop.is_set():
            now = MonoTime()
            with self._lock:
                stale = [k for k, v in self.active_nodes.items() if now - (v.last_seen or 0) > HEARTBEAT_TIMEOUT]
                for ident in stale:
                    meta = self.active_nodes.pop(ident, None)
                    # remove from global node map as well
                    self.nodes.pop(ident, None)
                    self._index_remove(ident, meta)
            time.sleep(PRUNE_INTERVAL)

    # ---------- helpers ----------
    def _pick_broadcast_idents(self, app_b: bytes, target_b: bytes) -> List[Ident]:
        with self._lock:
            if target_b == b"all":
                return list(self._index_by_app.get(app_b, set()))
            by_role = self._index_by_role.get(target_b, set())
            by_app = self._index_by_app.get(app_b, set())
            base, other = (by_role, by_app) if len(by_role) <= len(by_app) else (by_app, by_role)
            return [i for i in base if i in other]

    # ---------- I/O loop ----------
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

            # 受信
            if events.get(self.router) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.router.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    if len(frames) >= 2:
                        ident, payloads = bytes(frames[0]), frames[1:]
                        if len(payloads) == 1:  # control
                            self._handle_router_recv_control(ident, bytes(payloads[0]))
                        else:                   # app
                            self._handle_router_recv_app(tuple(bytes(f) for f in payloads))
                        did_work = True

            # 送信：direct
            direct_batch, sentinel_seen = _drain_queue(self._direct_q, self._sentinel)
            for ident, frames in direct_batch:
                try:
                    self.router.send_multipart((ident, *frames), copy=False)
                    did_work = True
                except zmq.Again:
                    warn_limited("Broker ROUTER send timeout; dropping direct message to %r", ident)
                except zmq.ZMQError as e:
                    warn_limited("Broker ROUTER send error to %r: %s", ident, e)
            if sentinel_seen:
                self._stop.set()
                break

            # 送信：broadcast（巨大スナップショット deep copy なし）
            for _key, frames in self._broadcast_q.drain_nowait():
                app_b, target_b = frames[0], (frames[1] or b"ALL").lower()
                for ident in self._pick_broadcast_idents(app_b, target_b):
                    try:
                        self.router.send_multipart((ident, *frames), copy=False)
                        did_work = True
                    except zmq.Again:
                        warn_limited("Broker ROUTER send timeout; dropping broadcast to %r", ident)
                    except zmq.ZMQError as e:
                        warn_limited("Broker ROUTER send error to %r: %s", ident, e)

            # アダプティブポーリング
            idle_streak, poll_timeout_ms = _adaptive_poll(
                did_work, idle_streak, self._base_poll_timeout_ms, self._max_poll_timeout_ms
            )

        _close_linger0(self.router)

    # ---- control handlers ----
    def _handle_router_recv_control(self, ident: Ident, payload: bytes):
        now = MonoTime()
        text = payload.decode("utf-8", errors="ignore")

        if text.startswith("register:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                logger.debug("Malformed register: %s", text)
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
                logger.debug("Malformed heartbeat: %s", text)
                return
            with self._lock:
                m = self.active_nodes.setdefault(
                    ident,
                    PeerMeta(parts[1].encode("utf-8"), parts[2].encode("utf-8"), parts[3].encode("utf-8")),
                )
                m.role_b, m.node_id_b, m.app_name_b, m.last_seen = (
                    parts[1].encode("utf-8"), parts[2].encode("utf-8"), parts[3].encode("utf-8"), now
                )
                self._index_add(ident, m)
            return

        if text.startswith("get_count:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                logger.debug("Malformed get_count: %s", text)
                return
            role_and_tail = parts[4] if len(parts) > 4 else ""
            role_str, req_id = role_and_tail, None
            if "," in role_and_tail:
                role_str, tail = role_and_tail.split(",", 1)
                if "request_id:" in tail:
                    req_id = tail.split("request_id:", 1)[1]

            with self._lock:
                counts: Dict[str, int] = {}
                for v in self.active_nodes.values():
                    r = v.role_lower.decode("utf-8", "ignore")
                    counts[r] = counts.get(r, 0) + 1
            counts_str = ",".join(f"{r}:{c}" for r, c in counts.items())

            reply_env = MessageEnvelope.build(
                APP_NAME=parts[3] if len(parts) > 3 else APP_FILE_NAME,
                targetprocess="ALL",
                table="",
                topic="control.count.reply",
                message=counts_str,
                request_id=req_id,
            )
            _force_put(self._direct_q, (ident, reply_env.to_frames()))
            return

        logger.debug("Unknown control: %s", text)

    def _handle_router_recv_app(self, frames: Frames):
        if len(frames) < 5:
            return
        key = _SEP.join(((frames[1] or b"ALL").lower(), frames[2], frames[3]))
        self._broadcast_q.put(key, frames)

    # ---- lifecycle ----
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

# ==================== Node ====================
class ZMQNode:
    def __init__(
        self,
        role: Role,
        app_name: str = APP_FILE_NAME,
        on_message: Optional[Callable[[MessageEnvelope], None]] = None,
        count: Literal["enable", "disable"] = "disable",
    ):
        if not isinstance(role, Role):
            raise TypeError("role must be a Role")
        self.role = role
        self.app_name = app_name
        self.on_message = on_message
        self.node_id = f"{role.value}-{uuid.uuid4().hex[:8]}"
        self.count = count

        self.ctx = zmq.Context.instance()
        self._stop = threading.Event()
        self._threads: List[threading.Thread] = []

        port = read_port() or DEFAULT_PORT
        self._current_addr: Optional[str] = f"tcp://localhost:{port}"

        # DEALER
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

        # 送信キュー: bytes(制御) または Frames(アプリ)
        self._out_q: "Queue[Union[bytes, Frames, object]]" = Queue(maxsize=NODE_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()

        self._pending: Dict[str, Tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()

        self._io_thread: Optional[threading.Thread] = None

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

            # 受信
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

            # 送信
            batch, sentinel_seen = _drain_queue(self._out_q, self._sentinel)
            for data in batch:
                try:
                    if isinstance(data, tuple):
                        self.dealer.send_multipart(list(data), copy=False)
                    else:
                        self.dealer.send(data, copy=False)
                    did_work = True
                except zmq.Again:
                    warn_limited("Node %s DEALER send timeout; dropping message", self.node_id)
                except Exception as e:
                    warn_limited("Node %s DEALER send error: %s", self.node_id, e)
            if sentinel_seen:
                self._stop.set()
                break

            # アダプティブポーリング
            idle_streak, poll_timeout_ms = _adaptive_poll(
                did_work, idle_streak, self._base_poll_timeout_ms, self._max_poll_timeout_ms
            )

        _close_linger0(self.dealer)

    def _enqueue_control(self, payload: str) -> None:
        _force_put(self._out_q, payload.encode("utf-8"))

    def _handle_dealer_recv_frames(self, frames: List[bytes]):
        env = MessageEnvelope.from_frames(frames)
        if not env:
            return

        # request_id の pending 待ち合わせ（control のみ想定）
        if env.request_id:
            with self._pending_lock:
                tup = self._pending.get(env.request_id)
            if tup:
                expect_topic, q = tup
                if env.topic == expect_topic:
                    _try_put(q, env)
                    return

        # APP_NAME 確認（bytes比較）
        if env._app_b != self.app_name.encode("utf-8"):
            return

        # targetprocess 小文字化（bytes）
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

    # ---- public API ----
    def send(self, *, targetprocess: str = "ALL", table: str = "", topic: str = "", message: Any = None):
        env = MessageEnvelope.build(APP_NAME=self.app_name, targetprocess=targetprocess, table=table, topic=topic, message=message)
        _try_put(self._out_q, env.to_frames())

    def request_count(self, role: Union[Role, str], timeout: float = 5.0) -> int:
        role_str = (role.value if isinstance(role, Role) else str(role)).lower()
        env = self.request_control(
            expect_topic="control.count.reply",
            payload=f"get_count:{self.role.value}:{self.node_id}:{self.app_name}:{role_str}",
            timeout=timeout,
        )
        if not env:
            return 0
        kv = dict(
            (k.strip(), v.strip())
            for k, v in (pair.split(":", 1) for pair in str(env.message).split(",") if ":" in pair)
        )
        return int(kv.get(role_str, 0) or 0)

    def request_control(self, *, expect_topic: str, payload: str, timeout: float = 5.0) -> Optional[MessageEnvelope]:
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

    def get_sub_count(self):
        return self.request_count(Role.VIEWER, 0.5)

    def stop(self):
        self._stop.set()
        _force_put(self._out_q, self._sentinel)
        for t in self._threads:
            t.join(timeout=2.0)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)
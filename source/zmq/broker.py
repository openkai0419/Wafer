# -*- coding: utf-8 -*-
from __future__ import annotations

"""
メモリ増加の主因（大規模スナップショットのコピー／Messageの二重保持）を解消した改訂版。
- Broadcast時の index スナップショット deep copy を廃止（その場参照＋必要最小の list 化のみ）
- MessageEnvelope を bytes 中心に再設計（lazy decode プロパティで必要時のみ文字列化）
- そのほかの最適化（既存最適化は維持）
"""

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

# ==================== Tunables ====================
HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
PRUNE_INTERVAL = 1  # brokerがactive_nodesを整理する周期（秒）
DEFAULT_PORT = 57556

BROKER_SEND_QUEUE_MAXSIZE = 100_000
NODE_SEND_QUEUE_MAXSIZE = 10_000

# ---- ZeroMQ tuning defaults (effective; set before bind/connect) ----
ZMQ_SNDHWM = 50_000
ZMQ_RCVHWM = 50_000
ZMQ_SNDTIMEO_MS = 1500
ZMQ_RCVTIMEO_MS = 1500

MonoTime = time.monotonic
_SEP = b"\x1f"  # coalescing用の区切り（バイト）

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

# ==================== Message ====================
@dataclass(slots=True)
class MessageEnvelope:
    """
    bytes 中心の軽量エンベロープ。decode は必要時のみ行い、かつ結果をキャッシュ。
    フレーム: [APP_NAME, TARGET, TABLE, TOPIC, MESSAGE, (optional) REQUEST_ID]
    """
    _app_b: bytes
    _target_b: bytes
    _table_b: bytes
    _topic_b: bytes
    _msg_b: bytes
    request_id: Optional[str] = None

    # lazy decode cache
    _app_s: Optional[str] = None
    _target_s: Optional[str] = None
    _table_s: Optional[str] = None
    _topic_s: Optional[str] = None
    _msg_s: Optional[str] = None

    # -------- 生成系 --------
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
        def _to_b(x: Union[str, bytes]) -> bytes:
            return x if isinstance(x, (bytes, bytearray)) else str(x).encode("utf-8")
        msg_b = b"" if message is None else (message if isinstance(message, (bytes, bytearray)) else str(message).encode("utf-8"))
        return cls(
            _app_b=_to_b(APP_NAME),
            _target_b=_to_b(targetprocess),
            _table_b=_to_b(table),
            _topic_b=_to_b(topic),
            _msg_b=bytes(msg_b),
            request_id=request_id,
        )

    def to_frames(self) -> Tuple[bytes, ...]:
        if self.request_id:
            return (self._app_b, self._target_b, self._table_b, self._topic_b, self._msg_b, self.request_id.encode("utf-8"))
        return (self._app_b, self._target_b, self._table_b, self._topic_b, self._msg_b)

    # -------- 受信系 --------
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

    # -------- プロパティ（必要時のみdecode） --------
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


def _tune(sock):
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.SNDHWM, ZMQ_SNDHWM)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.RCVHWM, ZMQ_RCVHWM)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.SNDTIMEO, ZMQ_SNDTIMEO_MS)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.RCVTIMEO, ZMQ_RCVTIMEO_MS)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
        sock.setsockopt(zmq.TCP_KEEPALIVE_CNT, 5)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.TCP_KEEPALIVE_INTVL, 2)


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
        try:
            q.get_nowait()  # 古い1件を捨てる（最新優先）
        except Empty:
            pass
        try:
            q.put_nowait(item)
            return True
        except Exception:
            warn_limited("queue full: drop message")
            return False


def _force_put(q: Queue, item) -> None:
    while True:
        if _try_put(q, item):
            return
        try:
            q.get_nowait()
        except Empty:
            pass
        time.sleep(0.001)  # スピン抑制


class _CoalescingKeyQueue:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._dq = collections.deque()           # deque[bytes]
        self._map: Dict[bytes, Tuple[bytes, ...]] = {}   # key -> frames
        self._lock = threading.Lock()

    def __len__(self):
        with self._lock:
            return len(self._dq)

    def put(self, key: bytes, value: Tuple[bytes, ...]) -> None:
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old_key = self._dq.popleft()
                self._map.pop(old_key, None)
            self._dq.append(key)
            self._map[key] = value

    def get_nowait(self) -> Tuple[bytes, Tuple[bytes, ...]]:
        with self._lock:
            if not self._dq:
                raise Empty
            while self._dq:
                key = self._dq.popleft()
                val = self._map.pop(key, None)
                if val is not None:
                    return key, val
            raise Empty

    def drain_nowait(self) -> List[Tuple[bytes, Tuple[bytes, ...]]]:
        out: List[Tuple[bytes, Tuple[bytes, ...]]] = []
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

        # ident -> PeerMeta（bytesベース）
        self.nodes: Dict[bytes, PeerMeta] = {}
        self.active_nodes: Dict[bytes, PeerMeta] = {}

        # 役割別・アプリ別インデックス（broadcast最適化）
        self._index_by_role: Dict[bytes, set[bytes]] = {}
        self._index_by_app: Dict[bytes, set[bytes]] = {}

        # キュー
        self._direct_q: "Queue[Tuple[bytes, Tuple[bytes, ...]] | object]" = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
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
    def _index_add(self, ident: bytes, meta: PeerMeta):
        role = meta.role_lower
        app = meta.app_name_b or b""
        self._index_by_role.setdefault(role, set()).add(ident)
        self._index_by_app.setdefault(app, set()).add(ident)

    def _index_remove(self, ident: bytes, meta: Optional[PeerMeta]):
        if not meta:
            return
        role = meta.role_lower
        app = meta.app_name_b or b""
        s = self._index_by_role.get(role)
        if s:
            s.discard(ident)
        s = self._index_by_app.get(app)
        if s:
            s.discard(ident)

    # ---------- prune thread ----------
    def _prune_loop(self):
        while not self._stop.is_set():
            now = MonoTime()
            with self._lock:
                stale = [k for k, v in self.active_nodes.items() if now - (v.last_seen or 0) > HEARTBEAT_TIMEOUT]
                for ident in stale:
                    meta = self.active_nodes.pop(ident, None)
                    self._index_remove(ident, meta)
            time.sleep(PRUNE_INTERVAL)

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
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        break
                    if len(frames) >= 2:
                        ident_f, payloads = frames[0], frames[1:]
                        ident = bytes(ident_f)
                        if len(payloads) == 1:
                            payload_b = bytes(payloads[0])
                            self._handle_router_recv_control(ident, payload_b)
                        else:
                            payload_bytes = tuple(bytes(f) for f in payloads)
                            self._handle_router_recv_app(payload_bytes)
                        did_work = True

            # 送信：direct
            direct_batch: List[Tuple[bytes, Tuple[bytes, ...]]] = []
            sentinel_seen = False
            while True:
                try:
                    item = self._direct_q.get_nowait()
                except Empty:
                    break
                if item is self._sentinel:
                    sentinel_seen = True
                    break
                direct_batch.append(item)

            if direct_batch:
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

            # 送信：broadcast（★巨大スナップショットの deep copy を廃止）
            bcast_batch = self._broadcast_q.drain_nowait()
            if bcast_batch:
                for _key, frames in bcast_batch:
                    app_b = frames[0]
                    target_b = (frames[1] or b"ALL").lower()

                    with self._lock:
                        if target_b == b"all":
                            idents_set = self._index_by_app.get(app_b, set())
                            idents = list(idents_set)  # 必要最小のshallow copy（送信中の安定性確保）
                        else:
                            by_role = self._index_by_role.get(target_b, set())
                            by_app = self._index_by_app.get(app_b, set())
                            # 積集合だが双方の要素だけを list 化（大規模 deep copy を避ける）
                            # 小さい方を基準にフィルタして list 化
                            base, other = (by_role, by_app) if len(by_role) <= len(by_app) else (by_app, by_role)
                            idents = [i for i in base if i in other]

                    for ident in idents:
                        try:
                            self.router.send_multipart((ident, *frames), copy=False)
                            did_work = True
                        except zmq.Again:
                            warn_limited("Broker ROUTER send timeout; dropping broadcast to %r", ident)
                        except zmq.ZMQError as e:
                            warn_limited("Broker ROUTER send error to %r: %s", ident, e)

            # アダプティブポーリング
            if did_work:
                idle_streak = 0
                poll_timeout_ms = self._base_poll_timeout_ms
            else:
                idle_streak = min(idle_streak + 1, self._max_poll_timeout_ms)
                poll_timeout_ms = min(self._base_poll_timeout_ms + idle_streak, self._max_poll_timeout_ms)

        _close_linger0(self.router)

    # ---- control handlers ----
    def _handle_router_recv_control(self, ident: bytes, payload: bytes):
        now = MonoTime()
        text = payload.decode("utf-8", errors="ignore")

        if text.startswith("register:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                logger.debug("Malformed register: %s", text)
                return
            meta = PeerMeta(parts[1].encode("utf-8"), parts[2].encode("utf-8"), parts[3].encode("utf-8"))
            with self._lock:
                self.nodes[ident] = meta  # 履歴用途（不要なら削除可）
                if parts[4] == "enable":
                    meta.last_seen = now
                    self.active_nodes[ident] = meta
                    self._index_add(ident, meta)
                else:
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
            frames = reply_env.to_frames()
            _force_put(self._direct_q, (ident, frames))
            return

        logger.debug("Unknown control: %s", text)

    def _handle_router_recv_app(self, frames: Tuple[bytes, ...]):
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

        # 送信キュー: bytes(制御) または Tuple[bytes,...](アプリ)
        self._out_q: "Queue[Union[bytes, Tuple[bytes, ...], object]]" = Queue(maxsize=NODE_SEND_QUEUE_MAXSIZE)
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

            # 受信処理
            if events.get(self.dealer) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.dealer.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        break
                    if len(frames) > 1:
                        frames_b = [bytes(f) for f in frames]
                        self._handle_dealer_recv_frames(frames_b)
                        did_work = True

            # 送信（毎ループで必ずキューを消費）
            batch: List[Union[bytes, Tuple[bytes, ...]]] = []
            sentinel_seen = False
            while True:
                try:
                    data = self._out_q.get_nowait()
                except Empty:
                    break
                if data is self._sentinel:
                    sentinel_seen = True
                    break
                batch.append(data)

            if batch:
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
            if did_work:
                idle_streak = 0
                poll_timeout_ms = self._base_poll_timeout_ms
            else:
                idle_streak = min(idle_streak + 1, self._max_poll_timeout_ms)
                poll_timeout_ms = min(self._base_poll_timeout_ms + idle_streak, self._max_poll_timeout_ms)

        _close_linger0(self.dealer)

    def _enqueue_control(self, payload: str) -> None:
        data = payload.encode("utf-8")
        _force_put(self._out_q, data)

    def _handle_dealer_recv_frames(self, frames: List[bytes]):
        env = MessageEnvelope.from_frames(frames)
        if not env:
            return

        # request_id の pending 待ち合わせ処理（controlのみ想定なので低頻度→decode許容）
        if env.request_id:
            with self._pending_lock:
                tup = self._pending.get(env.request_id)
            if tup:
                expect_topic, q = tup
                if env.topic == expect_topic:  # lazy decode property
                    _try_put(q, env)
                    return

        # APP_NAME の確認（bytes比較）
        if env._app_b != self.app_name.encode("utf-8"):
            return

        # targetprocess の小文字化比較（bytes）
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
        frames = env.to_frames()
        _try_put(self._out_q, frames)

    def request_count(self, role: Union[Role, str], timeout: float = 5.0) -> int:
        role_str = role.value if isinstance(role, Role) else str(role)
        role_str = role_str.lower()
        env = self.request_control(
            expect_topic="control.count.reply",
            payload=f"get_count:{self.role.value}:{self.node_id}:{self.app_name}:{role_str}",
            timeout=timeout,
        )
        if not env:
            return 0
        msg = env.message  # lazy decode
        kv = {}
        for pair in str(msg).split(","):
            if ":" in pair:
                k, v = pair.split(":", 1)
                kv[k.strip()] = v.strip()
        return int(kv.get(role_str, 0) or 0)

    def request_control(self, *, expect_topic: str, payload: str, timeout: float = 5.0) -> Optional[MessageEnvelope]:
        rid = f"{self.node_id}-{uuid.uuid4().hex[:8]}"
        payload_with_rid = f"{payload},request_id:{rid}"
        q: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = (expect_topic, q)
        try:
            self._enqueue_control(payload_with_rid)
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

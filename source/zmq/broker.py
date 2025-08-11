# -*- coding: utf-8 -*-

from __future__ import annotations
import uuid
from dataclasses import dataclass
from typing import Optional, Callable, List, Tuple, Union, Dict, Literal, Any
from enum import Enum
import contextlib

import threading
from queue import Queue, Empty
import time
import zmq

from ..common.profiling import logger
from .ipc_utils import write_port, read_port
from ..constants import APP_FILE_NAME

HEARTBEAT_INTERVAL = 5
HEARTBEAT_TIMEOUT = 15
DEFAULT_PORT = 57556
BROKER_SEND_QUEUE_MAXSIZE = 100_000
NODE_SEND_QUEUE_MAXSIZE = 10_000

# ---- ZeroMQ tuning defaults (effective; set before bind/connect) ----
ZMQ_SNDHWM = 100_000
ZMQ_RCVHWM = 100_000
ZMQ_SNDTIMEO_MS = 2000  # send blocks up to this; raises Again on timeout
ZMQ_RCVTIMEO_MS = 2000

MonoTime = time.monotonic

# -------------------- Enum --------------------

class Role(str, Enum):
    COMMUNICATOR = "communicator"
    COLLECTOR = "collector"
    VIEWER = "viewer"

# -------------------- Message --------------------

@dataclass(slots=True)
class MessageEnvelope:
    APP_NAME: str = APP_FILE_NAME
    targetprocess: str = "ALL"
    table: str = ""
    topic: str = ""
    message: Optional[str] = ""
    request_id: Optional[str] = None  # マルチパートの6フレーム目に相当

    def to_frames(self) -> List[bytes]:
        """[APP_NAME, TARGET, TABLE, TOPIC, MESSAGE, (optional) REQUEST_ID]"""
        frames = [
            self.APP_NAME.encode("utf-8"),
            (self.targetprocess or "ALL").encode("utf-8"),
            (self.table or "").encode("utf-8"),
            (self.topic or "").encode("utf-8"),
            ("" if self.message is None else str(self.message)).encode("utf-8"),
        ]
        if self.request_id:
            frames.append(self.request_id.encode("utf-8"))
        return frames

    @staticmethod
    def from_frames(frames: List[bytes]) -> Optional["MessageEnvelope"]:
        """frames: [APP_NAME, TARGET, TABLE, TOPIC, MESSAGE, (optional) REQUEST_ID]"""
        if len(frames) < 5:
            return None
        app = frames[0].decode("utf-8", "ignore")
        target = frames[1].decode("utf-8", "ignore")
        table = frames[2].decode("utf-8", "ignore")
        topic = frames[3].decode("utf-8", "ignore")
        msg = frames[4].decode("utf-8", "ignore")
        rid = frames[5].decode("utf-8", "ignore") if len(frames) > 5 else None
        return MessageEnvelope(APP_NAME=app, targetprocess=target, table=table, topic=topic, message=msg, request_id=rid)

# -------------------- Small helpers --------------------

@dataclass(slots=True)
class PeerMeta:
    role: Optional[str]
    node_id: Optional[str]
    app_name: Optional[str]
    last_seen: float = 0.0

def _tune(sock):
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.SNDHWM, ZMQ_SNDHWM)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.RCVHWM, ZMQ_RCVHWM)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.SNDTIMEO, ZMQ_SNDTIMEO_MS)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.RCVTIMEO, ZMQ_RCVTIMEO_MS)
    # 以下はプラットフォーム依存で失敗することがある
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.TCP_KEEPALIVE, 1)
        sock.setsockopt(zmq.TCP_KEEPALIVE_CNT, 5)
    with contextlib.suppress(Exception):
        sock.setsockopt(zmq.TCP_KEEPALIVE_IDLE, 10)
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
            q.get_nowait()  # 古い1件を捨てる
        except Empty:
            pass
        try:
            q.put_nowait(item)
            return True
        except Exception:
            logger.warning("node out_q full: drop message")
            return False

def _force_put(q: Queue, item) -> None:
    while True:
        if _try_put(q, item):
            return
        try:
            q.get_nowait()
        except Empty:
            pass

def _parse_kv_pairs(s: str) -> Dict[str, str]:
    """message='key:value,key:value' を dict に変換"""
    result: Dict[str, str] = {}
    for pair in s.split(","):
        pair = pair.strip()
        if ":" in pair:
            k, v = pair.split(":", 1)
            result[k.strip()] = v.strip()
    return result

# -------------------- Broker --------------------
class Broker:
    def __init__(self, bind_addr: Optional[str] = None):
        self.ctx = zmq.Context.instance()
        self.bind_addr = bind_addr

        self.router = self.ctx.socket(zmq.ROUTER)
        _tune(self.router)
        with contextlib.suppress(Exception):
            self.router.setsockopt(zmq.ROUTER_MANDATORY, 1)

        self._stop = threading.Event()

        self.nodes: Dict[bytes, PeerMeta] = {}
        self.active_nodes: Dict[bytes, PeerMeta] = {}

        # 送信キューは (ident, frames(List[bytes])) を積む
        self._send_q: "Queue[Tuple[bytes, List[bytes]] | object]" = Queue(maxsize=BROKER_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()
        self._lock = threading.RLock()

        self._io_thread: Optional[threading.Thread] = None
        # ★ wakeup用 inproc は廃止済み（ポーリング駆動）

    def _bind(self) -> str:
        saved = read_port()
        if self.bind_addr is None:
            if saved:
                try:
                    self.router.bind(saved); write_port(saved); return saved
                except zmq.ZMQError:
                    pass
            try:
                addr = f"tcp://localhost:{DEFAULT_PORT}"
                self.router.bind(addr); write_port(addr); return addr
            except zmq.ZMQError:
                port = self.router.bind_to_random_port("tcp://localhost")
                addr = f"tcp://localhost:{port}"
                write_port(addr)
                return addr
        else:
            self.router.bind(self.bind_addr)
            write_port(self.bind_addr)
            return self.bind_addr

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self.router, zmq.POLLIN)

        POLL_TIMEOUT_MS = 10  # ★ 短い周期で回す（wakeup不要）

        while not self._stop.is_set():
            try:
                events = dict(poller.poll(POLL_TIMEOUT_MS))
            except zmq.ZMQError:
                break

            # 受信処理（あるぶんだけNOBLOCKでドレイン）
            if events.get(self.router) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.router.recv_multipart(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        break
                    if len(frames) >= 2:
                        ident, payloads = frames[0], frames[1:]
                        if len(payloads) == 1:
                            self._handle_router_recv_control(ident, payloads[0])
                        else:
                            self._handle_router_recv_app(ident, payloads)

            # 送信（毎ループで必ずキューを消費）
            batch: List[Tuple[bytes, List[bytes]]] = []
            sentinel_seen = False
            while True:
                try:
                    item = self._send_q.get_nowait()
                except Empty:
                    break
                if item is self._sentinel:
                    sentinel_seen = True
                    break
                batch.append(item)

            if batch:
                for ident, frames in batch:
                    try:
                        self.router.send_multipart([ident, *frames])
                    except zmq.Again:
                        logger.warning("Broker ROUTER send timeout; dropping message to %r", ident)
                    except zmq.ZMQError as e:
                        logger.warning("Broker ROUTER send error to %r: %s", ident, e)

            if sentinel_seen:
                self._stop.set()
                break

        _close_linger0(self.router)

    # ---- handlers ----
    def _handle_router_recv_control(self, ident: bytes, payload: bytes):
        now = MonoTime()
        text = payload.decode("utf-8", errors="ignore")

        if text.startswith("register:"):
            parts = text.split(":", 5)
            if len(parts) < 5:
                logger.debug("Malformed register: %s", text); return
            meta = PeerMeta(parts[1], parts[2], parts[3])
            with self._lock:
                self.nodes[ident] = meta
                if parts[4] == "enable":
                    self.active_nodes[ident] = PeerMeta(meta.role, meta.node_id, meta.app_name, last_seen=now)
                else:
                    self.active_nodes.pop(ident, None)
                _ = self._make_counts()  # ついでに期限切れ掃除
            return

        if text.startswith("heartbeat:"):
            parts = text.split(":", 4)
            if len(parts) < 4:
                logger.debug("Malformed heartbeat: %s", text); return
            with self._lock:
                m = self.active_nodes.setdefault(
                    ident, PeerMeta(parts[1], parts[2], parts[3])
                )
                m.role, m.node_id, m.app_name, m.last_seen = parts[1], parts[2], parts[3], now
            return

        if text.startswith("get_count:"):
            # 形式: get_count:{role}:{node_id}:{app}:{role_str}[,request_id:{rid}]
            parts = text.split(":", 5)
            if len(parts) < 5:
                logger.debug("Malformed get_count: %s", text); return
            role_and_tail = parts[4] if len(parts) > 4 else ""
            role_str, req_id = role_and_tail, None
            if "," in role_and_tail:
                role_str, tail = role_and_tail.split(",", 1)
                if "request_id:" in tail:
                    req_id = tail.split("request_id:", 1)[1]

            counts = self._make_counts()
            counts_str = ",".join(f"{r}:{c}" for r, c in counts.items())

            reply_env = MessageEnvelope(
                APP_NAME=parts[3] if len(parts) > 3 else APP_FILE_NAME,
                targetprocess="ALL",
                table="",
                topic="control.count.reply",
                message=counts_str,
                request_id=req_id,
            )
            frames = reply_env.to_frames()
            if not _try_put(self._send_q, (ident, frames)):
                logger.warning("send queue full: drop control.count.reply")
            return

        logger.debug("Unknown control: %s", text)

    def _handle_router_recv_app(self, ident: bytes, frames: List[bytes]):
        # アプリ向けメッセージはフレームで受け取り、そのままルート
        #logger.debug(f"[Broker] APP from {ident!r}: {frames}")
        env = MessageEnvelope.from_frames(frames)
        if env is None:
            logger.debug("Invalid multipart frames")
            return
        self._route_message(env)

    def _make_counts(self) -> Dict[str, int]:
        now = MonoTime()
        with self._lock:
            dead = [k for k, v in self.active_nodes.items() if now - (v.last_seen or 0) > HEARTBEAT_TIMEOUT]
            for k in dead:
                self.active_nodes.pop(k, None)
            counts: Dict[str, int] = {}
            for v in self.active_nodes.values():
                role = (v.role or "").lower()  # ★小文字化
                counts[role] = counts.get(role, 0) + 1
        return counts

    def _route_message(self, env: MessageEnvelope):
        target = (env.targetprocess or "ALL").lower()
        with self._lock:
            nodes_snapshot = list(self.nodes.items())

        frames = env.to_frames()
        for ident, meta in nodes_snapshot:
            if meta.app_name is not None and meta.app_name != env.APP_NAME:
                continue
            if target != "all" and (meta.role or "").lower() != target:
                continue
            if not _try_put(self._send_q, (ident, frames)):
                logger.debug("send queue full: drop message")
        # ★ wakeup不要（ポーリング周期で送信）

    def start(self):
        addr = self._bind()
        logger.info(f"Broker bound: ROUTER={addr}")
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()

    def stop(self):
        self._stop.set()
        _force_put(self._send_q, self._sentinel)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)

# -------------------- Node --------------------
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

        self._current_addr: Optional[str] = read_port() or f"tcp://localhost:{DEFAULT_PORT}"

        # DEALER
        self.dealer = self.ctx.socket(zmq.DEALER)
        _tune(self.dealer)
        self.dealer.setsockopt(zmq.IDENTITY, self.node_id.encode("utf-8"))

        if self._current_addr:
            with contextlib.suppress(Exception):
                self.dealer.connect(self._current_addr)

        # 送信キュー: bytes(制御) または List[bytes](アプリ)
        self._out_q: "Queue[Union[bytes, List[bytes], object]]" = Queue(maxsize=NODE_SEND_QUEUE_MAXSIZE)
        self._sentinel = object()

        self._pending: Dict[str, Tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()

        self._io_thread: Optional[threading.Thread] = None
        # ★ wakeup用 inproc は廃止済み（ポーリング駆動）

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

        POLL_TIMEOUT_MS = 10  # ★ 短い周期で回す（wakeup不要）

        while not self._stop.is_set():
            try:
                events = dict(poller.poll(POLL_TIMEOUT_MS))
            except zmq.ZMQError:
                break

            # 受信処理
            if events.get(self.dealer) == zmq.POLLIN:
                while True:
                    try:
                        frames = self.dealer.recv_multipart(flags=zmq.NOBLOCK)
                    except zmq.Again:
                        break
                    except zmq.ZMQError:
                        break
                    if len(frames) == 1:
                        continue
                    self._handle_dealer_recv_frames(frames)

            # 送信（毎ループで必ずキューを消費）
            batch: List[Union[bytes, List[bytes]]] = []
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
                        if isinstance(data, list):
                            self.dealer.send_multipart(data)
                        else:
                            self.dealer.send(data)
                    except zmq.Again:
                        logger.warning("Node %s DEALER send timeout; dropping message", self.node_id)
                    except Exception as e:
                        logger.warning("Node %s DEALER send error: %s", self.node_id, e)

            if sentinel_seen:
                self._stop.set()
                break

        _close_linger0(self.dealer)

    def _enqueue_control(self, payload: str) -> None:
        data = payload.encode("utf-8")
        if not _try_put(self._out_q, data):
            logger.debug("node out_q full: drop control")

    def _handle_dealer_recv_frames(self, frames: List[bytes]):
        env = MessageEnvelope.from_frames(frames)
        if not env:
            return

        # request_id の pending 待ち合わせ処理
        if env.request_id:
            with self._pending_lock:
                tup = self._pending.get(env.request_id)
            if tup:
                expect_topic, q = tup
                if env.topic == expect_topic:
                    _try_put(q, env)
                    return

        # APP_NAME の確認（任意）
        if env.APP_NAME and env.APP_NAME != self.app_name:
            return

        # ★ targetprocess の小文字化比較
        tp = (env.targetprocess or "ALL").lower()
        if tp not in ("all", self.role.value.lower()):
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
        env = MessageEnvelope(APP_NAME=self.app_name, targetprocess=targetprocess, table=table, topic=topic, message=str(message))
        frames = env.to_frames()
        if not _try_put(self._out_q, frames):
            logger.debug("node out_q full: drop message")

    def request_count(self, role: Union[Role, str], timeout: float = 5.0) -> int:
        role_str = role.value if isinstance(role, Role) else str(role).lower()  # ★小文字化
        env = self.request_control(
            expect_topic="control.count.reply",
            payload=f"get_count:{self.role.value}:{self.node_id}:{self.app_name}:{role_str}",
            timeout=timeout,
        )
        if not env or not isinstance(env.message, str):
            return 0
        kv = _parse_kv_pairs(env.message)
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

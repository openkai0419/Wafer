from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from collections.abc import Callable

import zmq

from ...utils.logs import AppLogger
from .transport import (
    DEFAULT_PORT,
    HEARTBEAT_INTERVAL,
    NODE_QUEUE_MAX,
    NODE_TIMEOUT,
    POLL_BASE_MS,
    RECONNECT_FORCE_INTERVAL,
    Priority,
    adaptive_poll,
    close_socket,
    drain_queue,
    read_broker_port,
    try_put,
    tune_socket,
)
from .message import Message
from .outbox import OutboxStore, scan_all_outbox, remove_outbox_batch_from, cleanup_empty_outbox_files


class Node:
    def __init__(self, role: str, db: str | list[str] = "", *, consumer: bool = False):
        self.role = role
        self.db = db
        self.node_id = f"{role}-{os.getpid()}"
        self.session_id: str = ""
        self._handlers: dict[str, Callable[[Message], bool]] = {}
        self._viewer_id: int | None = None

        self._ctx = zmq.Context.instance()
        self._dealer: zmq.Socket | None = None
        self._current_port: int = 0
        self._last_recv: float = 0.0
        self._last_connect_time: float = 0.0

        self._out_q: Queue = Queue(maxsize=NODE_QUEUE_MAX)
        self._sentinel = object()
        self._pending: dict[str, tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._io_thread: threading.Thread | None = None
        self._registered = threading.Event()
        self._outbox: OutboxStore | None = None
        self._outbox_event = threading.Event()
        self._outbox_thread: threading.Thread | None = None
        if consumer:
            self._handlers["outbox.notify"] = lambda _msg: self._notify_outbox() or True
            self._outbox_thread = threading.Thread(target=self._outbox_worker, daemon=True)

    @property
    def viewer_id(self) -> int | None:
        return self._viewer_id

    @property
    def default_db(self) -> str:
        if isinstance(self.db, list):
            return ""
        return self.db

    def subscribe(self, topic: str, handler: Callable[[Message], bool]) -> Node:
        self._handlers[topic] = handler
        return self

    def unsubscribe(self, topic: str) -> Node:
        self._handlers.pop(topic, None)
        return self

    def start(self, port: int | None = None):
        target_port = port if port is not None else (read_broker_port() or DEFAULT_PORT)
        self._connect(target_port)
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        if self._outbox_thread:
            self._outbox_thread.start()

    def stop(self):
        self._stop.set()
        self._outbox_event.set()
        try_put(self._out_q, self._sentinel)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)
        if self._outbox_thread:
            self._outbox_thread.join(timeout=2.0)
        if self._outbox:
            self._outbox.delete_if_empty()
            self._outbox.close()

    def wait_registered(self, timeout: float = 5.0) -> bool:
        return self._registered.wait(timeout)

    def send(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = "", priority: int = Priority.MID):
        msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, priority=priority)
        try_put(self._out_q, msg.to_frames())

    def send_coalesced(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = ""):
        msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, coalesce=True)
        try_put(self._out_q, msg.to_frames())

    def send_reliable(self, topic: str, payload: Any = None, *, dst: str, db: str = ""):
        if self._outbox is None:
            self._outbox = OutboxStore(self.node_id)
        self._outbox.push(topic, payload, dst, db)
        self.send("outbox.notify", dst=dst, db=db, priority=Priority.HIGH)

    def request(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = "", timeout: float = 5.0) -> Message | None:
        rid = Message.make_request_id(f"{self.node_id}-")
        q: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = (topic, q)
        try:
            msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, rid=rid)
            try_put(self._out_q, msg.to_frames())
            try:
                return q.get(timeout=timeout)
            except Empty:
                return None
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _call_handler(self, msg: Message) -> bool | None:
        handler = self._handlers.get(msg.topic)
        if not handler:
            return None
        try:
            result = handler(msg)
            if result is not True and result is not False:
                AppLogger.warning(f"handler must return bool: {msg.topic}")
                return None
            return result
        except Exception as e:
            AppLogger.warning(f"handler error: {msg.topic}", exc=e)
            return None

    def _notify_outbox(self):
        self._outbox_event.set()

    def _outbox_worker(self):
        while not self._stop.is_set():
            self._outbox_event.wait(timeout=30)
            self._outbox_event.clear()
            if self._stop.is_set():
                break
            self._process_outbox()

    def _process_outbox(self):
        dst_filter = {self.node_id, self.role, "ALL"}
        db_filter = self.default_db or None
        records = scan_all_outbox(dst_filter=dst_filter, db_filter=db_filter)
        if not records:
            return
        done: dict[str, list[int]] = {}
        for rec in records:
            node_id = Path(rec.source_db).stem
            msg = Message.build(rec.topic, rec.payload, src=node_id, dst=rec.dst, db=rec.db)
            if self._call_handler(msg) is True:
                done.setdefault(rec.source_db, []).append(rec.id)
        for db_path, ids in done.items():
            remove_outbox_batch_from(db_path, ids)
        cleanup_empty_outbox_files()

    def _create_socket(self) -> zmq.Socket:
        sock = self._ctx.socket(zmq.DEALER)
        tune_socket(sock)
        try:
            sock.setsockopt(zmq.IMMEDIATE, 1)
        except Exception:
            pass
        try:
            sock.setsockopt(zmq.TCP_NODELAY, 1)
        except Exception:
            pass
        try:
            sock.setsockopt(zmq.RECONNECT_IVL_MAX, 1000)
        except Exception:
            pass
        sock.setsockopt(zmq.IDENTITY, self.node_id.encode("utf-8"))
        return sock

    def _connect(self, port: int):
        if self._dealer:
            close_socket(self._dealer)
        self._dealer = self._create_socket()
        self._dealer.connect(f"tcp://127.0.0.1:{port}")
        self._current_port = port
        self._last_recv = time.monotonic()
        self._last_connect_time = time.monotonic()
        self._registered.clear()

    def _ensure_connection(self):
        if self._registered.is_set():
            if time.monotonic() - self._last_recv < NODE_TIMEOUT:
                return
            AppLogger.warning(f"broker timeout (port={self._current_port}), attempting reconnect")
            self._registered.clear()

        new_port = read_broker_port(timeout=0.3)
        if not new_port:
            return
        if new_port != self._current_port:
            AppLogger.info(f"broker port changed: {self._current_port} -> {new_port}")
            self._connect(new_port)
        elif time.monotonic() - self._last_connect_time > RECONNECT_FORCE_INTERVAL:
            AppLogger.info(f"forcing reconnect on same port {new_port}")
            self._connect(new_port)

    def _send_to_broker(self, topic: str, payload: Any = None):
        msg = Message.build(topic, payload, src=self.node_id, dst="broker")
        try:
            self._dealer.send_multipart(list(msg.to_frames()), copy=False)
        except Exception as e:
            AppLogger.debug(f"send_to_broker failed ({topic}): {e}")

    def _heartbeat_tick(self):
        self._ensure_connection()
        if self._registered.is_set():
            self._send_to_broker("mgmt.heartbeat")
        else:
            self._send_to_broker(
                "mgmt.register",
                {
                    "role": self.role,
                    "db": self.db,
                    "session_id": self.session_id,
                },
            )

    def _handle_received(self, msg: Message):
        if msg.request_id:
            with self._pending_lock:
                pending = self._pending.get(msg.request_id)
            if pending:
                _, q = pending
                try_put(q, msg)
                return

        if msg.topic == "mgmt.registered":
            if isinstance(msg.payload, dict):
                self._viewer_id = msg.payload.get("viewer_id")
            self._registered.set()
            AppLogger.info(f"registered as {self.node_id}, viewer_id={self._viewer_id}")
            return

        if msg.topic == "mgmt.not_registered":
            self._registered.clear()
            return

        self._call_handler(msg)

    def _io_loop(self):
        poller = zmq.Poller()
        registered_dealer = self._dealer
        poller.register(registered_dealer, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS
        next_tick = 0.0

        while not self._stop.is_set():
            now = time.monotonic()
            if now >= next_tick:
                self._heartbeat_tick()
                next_tick = now + HEARTBEAT_INTERVAL
                if self._dealer is not registered_dealer:
                    poller = zmq.Poller()
                    registered_dealer = self._dealer
                    poller.register(registered_dealer, zmq.POLLIN)

            try:
                events = dict(poller.poll(poll_ms))
            except zmq.ZMQError:
                break
            did_work = False

            if events.get(self._dealer) == zmq.POLLIN:
                while True:
                    try:
                        frames = self._dealer.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    msg = Message.from_frames([bytes(f) for f in frames])
                    if msg:
                        self._last_recv = time.monotonic()
                        self._handle_received(msg)
                    did_work = True

            batch, sentinel = drain_queue(self._out_q, self._sentinel)
            for i, frames in enumerate(batch):
                try:
                    self._dealer.send_multipart(list(frames), copy=False)
                    did_work = True
                except zmq.Again:
                    for remaining in batch[i:]:
                        try_put(self._out_q, remaining)
                    break
                except Exception as e:
                    AppLogger.debug(f"node send error: {e}")
            if sentinel:
                break

            idle_streak, poll_ms = adaptive_poll(did_work, idle_streak)

        self._send_to_broker("mgmt.unregister")
        close_socket(self._dealer)

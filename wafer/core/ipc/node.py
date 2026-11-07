from __future__ import annotations
import os
import time
import threading
from pathlib import Path
from queue import Empty, Queue
from typing import Any
from collections.abc import Callable

import zmq

from ..logs import AppLogger
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
from .outbox import OutboxStore, cleanup_dead_outbox_files, read_outbox_of, remove_outbox_batch_from, scan_all_outbox

_OUTBOX_POLL = 30.0


class Node:
    def __init__(self, role: str, db: str | list[str] = "", *, consumer: bool = False, outbox_poll: float | None = _OUTBOX_POLL, broker_lost_timeout: float | None = None):
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
        self._timing_lock = threading.Lock()

        self._out_q: Queue = Queue(maxsize=NODE_QUEUE_MAX)
        self._sentinel = object()
        self._pending: dict[str, tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._io_thread: threading.Thread | None = None
        self._registered = threading.Event()
        self._broker_lost_timeout = broker_lost_timeout
        self._unregistered_since: float | None = None
        self._broker_lost_callback: Callable[[], None] | None = None
        self._register_warned = False
        self._outbox: OutboxStore | None = None
        self._outbox_event = threading.Event()
        self._outbox_poll = outbox_poll
        self._outbox_thread: threading.Thread | None = None
        self._outbox_senders: set[str] = set()
        self._outbox_senders_lock = threading.Lock()
        if consumer:
            self._handlers["outbox.notify"] = lambda msg: self._notify_outbox(msg.source) or True
            self._outbox_thread = threading.Thread(target=self._outbox_worker, daemon=True)

    @property
    def is_registered(self) -> bool:
        return self._registered.is_set()

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

    def on_broker_lost(self, callback: Callable[[], None], timeout: float | None = None):
        self._broker_lost_callback = callback
        if timeout is not None:
            self._broker_lost_timeout = timeout

    def start(self, port: int | None = None):
        if self._broker_lost_timeout is not None:
            self._unregistered_since = time.monotonic()
        target_port = port if port is not None else (read_broker_port() or DEFAULT_PORT)
        self._connect(target_port)
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        if self._outbox_thread:
            self._outbox_thread.start()

    def stop(self):
        self._stop.set()
        self._outbox_event.set()
        try_put(self._out_q, self._sentinel, "node.stop")
        if self._io_thread:
            self._io_thread.join(timeout=2.0)
        if self._outbox_thread and self._outbox_thread.is_alive():
            self._outbox_thread.join(timeout=2.0)
        if self._outbox:
            self._outbox.delete_if_empty()
            self._outbox.close()

    def wait_registered(self, timeout: float = 5.0) -> bool:
        return self._registered.wait(timeout)

    def send(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = "", priority: int = Priority.MID):
        msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, priority=priority)
        try_put(self._out_q, msg.to_frames(), f"node.send:{topic}")

    def enqueue(self, msg: Message):
        try_put(self._out_q, msg.to_frames(), f"node.enqueue:{msg.topic}")

    def send_coalesced(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = ""):
        msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, coalesce=True)
        try_put(self._out_q, msg.to_frames(), f"node.coalesced:{topic}")

    def send_reliable(self, topic: str, payload: Any = None, *, dst: str, db: str = ""):
        if self._outbox is None:
            self._outbox = OutboxStore(self.node_id)
        self._outbox.push(topic, payload, dst, db)
        self.send("outbox.notify", dst=dst, db=db, priority=Priority.HIGH)

    def nudge_undelivered(self, topic: str, *, dst: str, db: str = "") -> bool:
        """Wake the consumer again if an earlier send_reliable of this topic is still in the outbox.

        The notify is a plain send, lost while the consumer is not registered.
        """
        if self._outbox is None or not self._outbox.has_pending(topic, dst):
            return False
        self.send("outbox.notify", dst=dst, db=db, priority=Priority.HIGH)
        return True

    def request(self, topic: str, payload: Any = None, *, dst: str = "ALL", db: str = "", timeout: float = 5.0) -> Message | None:
        rid = Message.make_request_id(f"{self.node_id}-")
        q: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = (topic, q)
        try:
            msg = Message.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, rid=rid)
            try_put(self._out_q, msg.to_frames(), f"node.request:{topic}")
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

    def _notify_outbox(self, sender: str):
        with self._outbox_senders_lock:
            self._outbox_senders.add(sender)
        self._outbox_event.set()

    def _outbox_worker(self):
        last_full_scan = time.monotonic()
        while not self._stop.is_set():
            self._outbox_event.wait(timeout=self._outbox_poll)
            self._outbox_event.clear()
            if self._stop.is_set():
                break
            with self._outbox_senders_lock:
                senders, self._outbox_senders = self._outbox_senders, set()
            if self._outbox_poll is not None and time.monotonic() - last_full_scan >= self._outbox_poll:
                last_full_scan = time.monotonic()
                self._process_outbox()
            elif senders:
                self._process_outbox(senders)

    def _process_outbox(self, senders: set[str] | None = None):
        dst_filter = {self.node_id, self.role, "ALL"}
        db_filter = self.default_db or None
        if senders is None:
            records = scan_all_outbox(dst_filter=dst_filter, db_filter=db_filter)
        else:
            records = read_outbox_of(senders, dst_filter=dst_filter, db_filter=db_filter)
        done: dict[str, list[int]] = {}
        for rec in records:
            node_id = Path(rec.source_db).stem
            msg = Message.build(rec.topic, rec.payload, src=node_id, dst=rec.dst, db=rec.db)
            if self._call_handler(msg) is True:
                done.setdefault(rec.source_db, []).append(rec.id)
        for db_path, ids in done.items():
            remove_outbox_batch_from(db_path, ids)
        if senders is None:
            cleanup_dead_outbox_files()

    def _create_socket(self) -> zmq.Socket:
        sock = self._ctx.socket(zmq.DEALER)
        tune_socket(sock)
        try:
            sock.setsockopt(zmq.IMMEDIATE, 1)
        except (zmq.ZMQError, AttributeError):
            pass
        try:
            sock.setsockopt(zmq.TCP_NODELAY, 1)
        except (zmq.ZMQError, AttributeError):
            pass
        try:
            sock.setsockopt(zmq.RECONNECT_IVL_MAX, 1000)
        except (zmq.ZMQError, AttributeError):
            pass
        sock.setsockopt(zmq.IDENTITY, self.node_id.encode("utf-8"))
        return sock

    def _connect(self, port: int):
        if self._dealer:
            close_socket(self._dealer)
        self._dealer = self._create_socket()
        self._dealer.connect(f"tcp://127.0.0.1:{port}")
        self._current_port = port
        with self._timing_lock:
            self._last_recv = time.monotonic()
            self._last_connect_time = time.monotonic()
        self._registered.clear()

    def _drain_inbound(self) -> bool:
        did_work = False
        while True:
            try:
                frames = self._dealer.recv_multipart(flags=zmq.NOBLOCK, copy=False)
            except (zmq.Again, zmq.ZMQError):
                return did_work
            msg = Message.from_frames([bytes(f) for f in frames])
            if msg:
                with self._timing_lock:
                    self._last_recv = time.monotonic()
                self._handle_received(msg)
            did_work = True

    def _ensure_connection(self):
        # A plugin holding the GIL (a model load) stops this thread while messages wait in the socket.
        # Read them first: they prove the broker is alive, and reconnecting would destroy them unread.
        self._drain_inbound()
        if self._registered.is_set():
            with self._timing_lock:
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
        else:
            with self._timing_lock:
                should_reconnect = time.monotonic() - self._last_connect_time > RECONNECT_FORCE_INTERVAL
            if should_reconnect:
                AppLogger.info(f"forcing reconnect on same port {new_port}")
                self._connect(new_port)

    def _send_to_broker(self, topic: str, payload: Any = None) -> bool:
        msg = Message.build(topic, payload, src=self.node_id, dst="broker")
        try:
            self._dealer.send_multipart(list(msg.to_frames()), copy=False)
            return True
        except Exception as e:
            AppLogger.debug(f"send_to_broker failed ({topic}): {e}")
            return False

    def re_register(self, session_id: str):
        self.session_id = session_id
        self._registered.clear()
        self._send_to_broker(
            "mgmt.register",
            {
                "role": self.role,
                "db": self.db,
                "session_id": self.session_id,
            },
        )

    def _heartbeat_tick(self):
        self._ensure_connection()
        if self._registered.is_set():
            self._send_to_broker("mgmt.heartbeat")
        else:
            ok = self._send_to_broker(
                "mgmt.register",
                {
                    "role": self.role,
                    "db": self.db,
                    "session_id": self.session_id,
                },
            )
            if not ok and not self._register_warned:
                AppLogger.warning(f"broker unreachable, retrying registration (node={self.node_id})")
                self._register_warned = True

    def _handle_received(self, msg: Message):
        if msg.request_id:
            with self._pending_lock:
                pending = self._pending.get(msg.request_id)
            if pending:
                _, q = pending
                try_put(q, msg, f"node.reply:{msg.topic}")
                return

        if msg.topic == "mgmt.registered":
            if isinstance(msg.payload, dict):
                self._viewer_id = msg.payload.get("viewer_id")
            self._registered.set()
            self._unregistered_since = None
            self._register_warned = False
            AppLogger.info(f"registered as {self.node_id}, viewer_id={self._viewer_id}")
            return

        if msg.topic == "mgmt.not_registered":
            self._registered.clear()
            return

        self._call_handler(msg)

    def _check_broker_lost(self, now: float) -> bool:
        if self._broker_lost_timeout is None:
            return False
        if self._registered.is_set():
            self._unregistered_since = None
            return False
        if self._unregistered_since is None:
            self._unregistered_since = now
            return False
        if now - self._unregistered_since <= self._broker_lost_timeout:
            return False
        AppLogger.warning(f"broker unreachable for {self._broker_lost_timeout}s, shutting down node {self.node_id}")
        self._stop.set()
        if self._broker_lost_callback:
            try:
                self._broker_lost_callback()
            except Exception as e:
                AppLogger.warning("broker_lost callback failed", exc=e)
        return True

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
                if self._check_broker_lost(now):
                    break

            try:
                events = dict(poller.poll(poll_ms))
            except zmq.ZMQError as e:
                AppLogger.warning(f"node _io_loop poll error, exiting: {e}")
                break
            did_work = False

            if events.get(self._dealer) == zmq.POLLIN:
                did_work = self._drain_inbound()

            batch, sentinel = drain_queue(self._out_q, self._sentinel)
            for i, frames in enumerate(batch):
                try:
                    self._dealer.send_multipart(list(frames), copy=False)
                    did_work = True
                except zmq.Again:
                    for remaining in batch[i:]:
                        try_put(self._out_q, remaining, "node.resend")
                    break
                except Exception as e:
                    AppLogger.debug(f"node send error: {e}")
            if sentinel:
                break

            idle_streak, poll_ms = adaptive_poll(did_work, idle_streak)

        self._send_to_broker("mgmt.unregister")
        close_socket(self._dealer)

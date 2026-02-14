from __future__ import annotations
import threading
import uuid
from queue import Empty, Queue
from typing import Any, Callable

import zmq

from ..common.profiling import logger
from ._core import (
    DEFAULT_PORT, HEARTBEAT_INTERVAL, NODE_QUEUE_MAX, POLL_BASE_MS,
    adaptive_poll, close_socket, drain_queue, try_put, tune_socket,
)
from .ipc_utils import read_broker_port
from .message import Msg


class Node:

    def __init__(self, role: str, db: str | list[str] = ''):
        self.role = role
        self.db = db
        self.node_id = f'{role}-{uuid.uuid4().hex[:8]}'
        self._handlers: dict[str, Callable[[Msg], None]] = {}
        self._viewer_id: int | None = None

        self._ctx = zmq.Context.instance()
        self._dealer = self._ctx.socket(zmq.DEALER)
        tune_socket(self._dealer)
        try:
            self._dealer.setsockopt(zmq.IMMEDIATE, 1)
        except Exception:
            pass
        try:
            self._dealer.setsockopt(zmq.TCP_NODELAY, 1)
        except Exception:
            pass
        self._dealer.setsockopt(zmq.IDENTITY, self.node_id.encode('utf-8'))

        self._out_q: Queue = Queue(maxsize=NODE_QUEUE_MAX)
        self._sentinel = object()
        self._pending: dict[str, tuple[str, Queue]] = {}
        self._pending_lock = threading.Lock()
        self._stop = threading.Event()
        self._io_thread: threading.Thread | None = None
        self._hb_thread: threading.Thread | None = None
        self._registered = threading.Event()

    @property
    def viewer_id(self) -> int | None:
        return self._viewer_id

    @property
    def default_db(self) -> str:
        if isinstance(self.db, list):
            return ''
        return self.db

    def on(self, topic: str, handler: Callable[[Msg], None]) -> Node:
        self._handlers[topic] = handler
        return self

    def off(self, topic: str) -> Node:
        self._handlers.pop(topic, None)
        return self

    def connect(self, port: int):
        self._dealer.connect(f'tcp://127.0.0.1:{port}')

    def start(self, port: int | None = None):
        if port is not None:
            self.connect(port)
        else:
            self.connect(read_broker_port() or DEFAULT_PORT)
        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._io_thread.start()
        self._send_register()
        self._hb_thread = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._hb_thread.start()

    def stop(self):
        self._stop.set()
        try_put(self._out_q, self._sentinel)
        if self._hb_thread:
            self._hb_thread.join(timeout=2.0)
        if self._io_thread:
            self._io_thread.join(timeout=2.0)
        close_socket(self._dealer)

    def wait_registered(self, timeout: float = 5.0) -> bool:
        return self._registered.wait(timeout)

    def send(self, topic: str, payload: Any = None, *, dst: str = 'ALL', db: str = ''):
        msg = Msg.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db)
        try_put(self._out_q, msg.to_frames())

    def notify(self, topic: str, payload: Any = None):
        self.send(topic, payload, dst='viewer')

    def request(self, topic: str, payload: Any = None, *, dst: str = 'ALL', db: str = '', timeout: float = 5.0) -> Msg | None:
        rid = Msg.make_rid(f'{self.node_id}-')
        q: Queue = Queue(maxsize=1)
        with self._pending_lock:
            self._pending[rid] = (topic, q)
        try:
            msg = Msg.build(topic, payload, src=self.node_id, dst=dst, db=db or self.default_db, rid=rid)
            try_put(self._out_q, msg.to_frames())
            try:
                return q.get(timeout=timeout)
            except Empty:
                return None
        finally:
            with self._pending_lock:
                self._pending.pop(rid, None)

    def _send_register(self):
        msg = Msg.build(
            'mgmt.register',
            {'role': self.role, 'db': self.db},
            src=self.node_id,
            dst='broker',
        )
        try_put(self._out_q, msg.to_frames())

    def _heartbeat_loop(self):
        while not self._stop.is_set():
            msg = Msg.build('mgmt.heartbeat', src=self.node_id)
            try_put(self._out_q, msg.to_frames())
            self._stop.wait(HEARTBEAT_INTERVAL)

    def _dispatch(self, msg: Msg):
        if msg.rid:
            with self._pending_lock:
                pending = self._pending.get(msg.rid)
            if pending:
                _, q = pending
                try_put(q, msg)
                return

        if msg.topic == 'mgmt.registered':
            if isinstance(msg.payload, dict):
                self._viewer_id = msg.payload.get('viewer_id')
            self._registered.set()
            logger.info(f'registered as {self.node_id}, viewer_id={self._viewer_id}')
            return

        handler = self._handlers.get(msg.topic)
        if handler:
            try:
                handler(msg)
            except Exception:
                logger.exception('handler error: %s', msg.topic)

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self._dealer, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS

        while not self._stop.is_set():
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
                    msg = Msg.from_frames([bytes(f) for f in frames])
                    if msg:
                        self._dispatch(msg)
                    did_work = True

            batch, sentinel = drain_queue(self._out_q, self._sentinel)
            for frames in batch:
                try:
                    if isinstance(frames, tuple):
                        self._dealer.send_multipart(list(frames), copy=False)
                    else:
                        self._dealer.send(frames, copy=False)
                    did_work = True
                except zmq.Again:
                    try_put(self._out_q, frames)
                    break
                except Exception as e:
                    logger.debug('node send error: %s', e)
            if sentinel:
                break

            idle_streak, poll_ms = adaptive_poll(did_work, idle_streak)

        close_socket(self._dealer)

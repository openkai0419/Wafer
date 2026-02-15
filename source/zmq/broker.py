from __future__ import annotations
import collections
import threading
import time
from queue import Queue

import zmq

from ..common.logs import AppLogger
from ._core import (
    BROKER_QUEUE_MAX, DEFAULT_PORT, HEARTBEAT_TIMEOUT, POLL_BASE_MS, QoS,
    adaptive_poll, close_socket, drain_queue, try_put, tune_socket,
)
from .ipc_utils import remove_broker_port, write_broker_port
from .message import Msg


class _PeerInfo:
    __slots__ = ('role', 'db_set', 'node_id', 'last_seen')

    def __init__(self, role: str, db_set: set[str], node_id: str):
        self.role = role
        self.db_set = db_set
        self.node_id = node_id
        self.last_seen = time.monotonic()


class _CoalescingQueue:

    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._dq: collections.deque = collections.deque()
        self._map: dict = {}
        self._lock = threading.Lock()

    def put(self, key, value):
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old = self._dq.popleft()
                self._map.pop(old, None)
            self._dq.append(key)
            self._map[key] = value

    def drain(self) -> list[tuple]:
        with self._lock:
            out = []
            while self._dq:
                k = self._dq.popleft()
                v = self._map.pop(k, None)
                if v is not None:
                    out.append((k, v))
            return out


class Broker:

    def __init__(self, port: int | None = None):
        self._ctx = zmq.Context.instance()
        self._router = self._ctx.socket(zmq.ROUTER)
        tune_socket(self._router)
        try:
            self._router.setsockopt(zmq.ROUTER_MANDATORY, 1)
        except Exception:
            pass

        bind_port = port or DEFAULT_PORT
        try:
            self._router.bind(f'tcp://127.0.0.1:{bind_port}')
            self.port = bind_port
        except zmq.ZMQError:
            self.port = self._router.bind_to_random_port('tcp://127.0.0.1')

        self._stop = threading.Event()
        self._direct_q: Queue = Queue(maxsize=BROKER_QUEUE_MAX)
        self._high_q: Queue = Queue(maxsize=BROKER_QUEUE_MAX)
        self._mid_q: Queue = Queue(maxsize=BROKER_QUEUE_MAX)
        self._low_q: Queue = Queue(maxsize=BROKER_QUEUE_MAX)
        self._broadcast_q = _CoalescingQueue(maxsize=BROKER_QUEUE_MAX)
        self._sentinel = object()

        self._peers: dict[bytes, _PeerInfo] = {}
        self._by_role: dict[str, set[bytes]] = {}
        self._by_node_id: dict[str, bytes] = {}
        self._lock = threading.RLock()
        self._viewer_counter = 0

        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._prune_thread = threading.Thread(target=self._prune_loop, daemon=True)

    def start(self):
        AppLogger.info(f'Broker bound: tcp://127.0.0.1:{self.port}')
        write_broker_port(self.port)
        self._io_thread.start()
        self._prune_thread.start()

    def stop(self):
        AppLogger.info('Broker stopping')
        self._stop.set()
        try_put(self._direct_q, self._sentinel)
        self._io_thread.join(timeout=2.0)
        self._prune_thread.join(timeout=2.0)
        close_socket(self._router)
        remove_broker_port()

    def inject(self, msg: Msg):
        targets = self._resolve_targets(msg, sender_ident=None)
        frames = msg.to_frames()
        for ident in targets:
            try_put(self._direct_q, (ident, frames))

    def get_counts(self) -> dict[str, int]:
        with self._lock:
            return {role: len(idents) for role, idents in self._by_role.items() if idents}

    def _add_peer(self, ident: bytes, role: str, db_set: set[str], node_id: str) -> bool:
        with self._lock:
            old = self._peers.get(ident)
            is_new = not old or old.role != role
            if old:
                self._by_role.get(old.role, set()).discard(ident)
                self._by_node_id.pop(old.node_id, None)
            peer = _PeerInfo(role, db_set, node_id)
            self._peers[ident] = peer
            self._by_role.setdefault(role, set()).add(ident)
            self._by_node_id[node_id] = ident
            AppLogger.info(f'peer added: {node_id} role={role} db={db_set}')
            return is_new

    def _remove_peer(self, ident: bytes):
        with self._lock:
            peer = self._peers.pop(ident, None)
            if not peer:
                return
            AppLogger.info(f'peer removed: {peer.node_id}')
            self._by_role.get(peer.role, set()).discard(ident)
            self._by_node_id.pop(peer.node_id, None)

    def _touch_peer(self, ident: bytes):
        with self._lock:
            peer = self._peers.get(ident)
            if peer:
                peer.last_seen = time.monotonic()

    def _resolve_targets(self, msg: Msg, sender_ident: bytes | None) -> list[bytes]:
        with self._lock:
            if msg.dst in self._by_node_id:
                ident = self._by_node_id[msg.dst]
                return [ident] if ident != sender_ident else []

            if msg.dst == 'ALL':
                candidates = set(self._peers.keys())
            elif msg.dst in self._by_role:
                candidates = set(self._by_role[msg.dst])
            else:
                return []

            if sender_ident:
                candidates.discard(sender_ident)

            if msg.db:
                candidates = {i for i in candidates if not self._peers[i].db_set or msg.db in self._peers[i].db_set}

            return list(candidates)

    def _handle_msg(self, ident: bytes, msg: Msg):
        topic = msg.topic

        if topic == 'mgmt.register':
            payload = msg.payload if isinstance(msg.payload, dict) else {}
            role = payload.get('role', '')
            db_raw = payload.get('db', '')
            node_id = msg.src
            if isinstance(db_raw, list):
                db_set = set(db_raw)
            elif db_raw:
                db_set = {db_raw}
            else:
                db_set = set()
            is_new = self._add_peer(ident, role, db_set, node_id)
            reply_payload = {'status': 'ok', 'node_id': node_id}
            if role == 'viewer':
                if is_new:
                    self._viewer_counter += 1
                reply_payload['viewer_id'] = self._viewer_counter
            reply = msg.reply(reply_payload, topic='mgmt.registered')
            try_put(self._direct_q, (ident, reply.to_frames()))
            AppLogger.info(f'registered: {node_id} role={role} db={db_set}')
            return

        if topic == 'mgmt.heartbeat':
            self._touch_peer(ident)
            return

        if topic == 'mgmt.get_count':
            counts = self.get_counts()
            reply = msg.reply(counts, topic='mgmt.count_reply')
            try_put(self._direct_q, (ident, reply.to_frames()))
            return

        exclude = ident if topic != 'dev.log' else None
        targets = self._resolve_targets(msg, sender_ident=exclude)
        if not targets:
            return

        frames = msg.to_frames()

        if msg.rid:
            for t in targets:
                try_put(self._direct_q, (t, frames))
            return

        qos = msg.qos
        if qos == QoS.LATEST:
            key = (msg.topic, msg.dst, msg.db)
            self._broadcast_q.put(key, (targets, frames))
        elif qos == QoS.HIGH:
            for t in targets:
                try_put(self._high_q, (t, frames))
        elif qos == QoS.LOW:
            for t in targets:
                try_put(self._low_q, (t, frames))
        else:
            for t in targets:
                try_put(self._mid_q, (t, frames))

    def _send_direct(self, items, did_work):
        for ident, frames in items:
            try:
                self._router.send_multipart([ident, *frames], copy=False)
                did_work = True
            except zmq.Again:
                AppLogger.debug('broker: drop direct (timeout)')
            except zmq.ZMQError as e:
                if e.errno != zmq.EHOSTUNREACH:
                    AppLogger.debug(f'broker: send error {e}')
        return did_work

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self._router, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS

        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_ms))
            except zmq.ZMQError:
                break
            did_work = False

            if events.get(self._router) == zmq.POLLIN:
                while True:
                    try:
                        frames = self._router.recv_multipart(flags=zmq.NOBLOCK, copy=False)
                    except (zmq.Again, zmq.ZMQError):
                        break
                    if len(frames) < 3:
                        continue
                    ident = bytes(frames[0])
                    msg = Msg.from_frames([bytes(f) for f in frames[1:]])
                    if msg:
                        self._handle_msg(ident, msg)
                    did_work = True

            batch, sentinel = drain_queue(self._direct_q, self._sentinel)
            did_work = self._send_direct(batch, did_work)
            if sentinel:
                break

            for q in (self._high_q, self._mid_q):
                items, _ = drain_queue(q, self._sentinel)
                did_work = self._send_direct(items, did_work)

            for _key, (targets, frames) in self._broadcast_q.drain():
                for t in targets:
                    try:
                        self._router.send_multipart([t, *frames], copy=False)
                        did_work = True
                    except zmq.Again:
                        pass
                    except zmq.ZMQError as e:
                        if e.errno != zmq.EHOSTUNREACH:
                            AppLogger.debug(f'broker: bcast error {e}')

            low_items, _ = drain_queue(self._low_q, self._sentinel)
            did_work = self._send_direct(low_items, did_work)

            idle_streak, poll_ms = adaptive_poll(did_work, idle_streak)

        close_socket(self._router)

    def _prune_loop(self):
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                stale = [i for i, p in self._peers.items() if now - p.last_seen > HEARTBEAT_TIMEOUT]
            for ident in stale:
                peer = self._peers.get(ident)
                if peer:
                    AppLogger.info(f'pruning stale peer: {peer.node_id}')
                self._remove_peer(ident)
            time.sleep(1)

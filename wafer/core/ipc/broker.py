from __future__ import annotations
import collections
import threading
import time
from queue import Queue
from typing import Any

import zmq

from ...utils.logs import AppLogger
from .transport import (
    BROKER_QUEUE_MAX,
    DEFAULT_PORT,
    HEARTBEAT_TIMEOUT,
    POLL_BASE_MS,
    Priority,
    adaptive_poll,
    close_socket,
    drain_queue,
    remove_broker_port,
    try_put,
    tune_socket,
    write_broker_port,
)
from .message import Message


class _PeerInfo:
    __slots__ = ("db_set", "last_seen", "node_id", "role", "session_id")

    def __init__(self, role: str, db_set: set[str], node_id: str, session_id: str = ""):
        self.role = role
        self.db_set = db_set
        self.node_id = node_id
        self.session_id = session_id
        self.last_seen = time.monotonic()


_CoalesceKey = tuple[str, str, str]
_CoalesceValue = tuple[list[bytes], tuple[bytes, bytes]]


class _CoalescingQueue:
    def __init__(self, maxsize: int):
        self.maxsize = maxsize
        self._dq: collections.deque[_CoalesceKey] = collections.deque()
        self._map: dict[_CoalesceKey, _CoalesceValue] = {}
        self._lock = threading.Lock()

    def put(self, key: _CoalesceKey, value: _CoalesceValue) -> None:
        with self._lock:
            if key in self._map:
                self._map[key] = value
                return
            if len(self._dq) >= self.maxsize:
                old = self._dq.popleft()
                self._map.pop(old, None)
            self._dq.append(key)
            self._map[key] = value

    def drain(self) -> list[tuple[_CoalesceKey, _CoalesceValue]]:
        with self._lock:
            out: list[tuple[_CoalesceKey, _CoalesceValue]] = []
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
        except (zmq.ZMQError, AttributeError):
            pass

        bind_port = port or DEFAULT_PORT
        try:
            self._router.bind(f"tcp://127.0.0.1:{bind_port}")
            self.port = bind_port
        except zmq.ZMQError:
            self.port = self._router.bind_to_random_port("tcp://127.0.0.1")

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
        self._viewer_ids: dict[bytes, int] = {}
        self._restore_debounce: threading.Timer | None = None
        self._restore_debounce_sec: float = 1.0
        self._profile_store_factory: Any = None

        self._io_thread = threading.Thread(target=self._io_loop, daemon=True)
        self._prune_thread = threading.Thread(target=self._reaper_loop, daemon=True)

    def start(self):
        AppLogger.info(f"Broker bound: tcp://127.0.0.1:{self.port}")
        write_broker_port(self.port)
        self._io_thread.start()
        self._prune_thread.start()

    def stop(self):
        AppLogger.info("Broker stopping")
        self._cancel_restore_debounce()
        self._stop.set()
        try_put(self._direct_q, self._sentinel)
        self._io_thread.join(timeout=2.0)
        self._prune_thread.join(timeout=2.0)
        close_socket(self._router)
        remove_broker_port()

    def dispatch(self, msg: Message):
        targets = self._resolve_targets(msg, sender_ident=None)
        frames = msg.to_frames()
        for ident in targets:
            try_put(self._direct_q, (ident, frames))

    def peer_counts(self) -> dict[str, int]:
        with self._lock:
            return {role: len(idents) for role, idents in self._by_role.items() if idents}

    def _register_peer(self, ident: bytes, role: str, db_set: set[str], node_id: str, session_id: str = "") -> int | None:
        with self._lock:
            old = self._peers.get(ident)
            old_session_id = old.session_id if old else ""
            if old:
                self._by_role.get(old.role, set()).discard(ident)
                self._by_node_id.pop(old.node_id, None)
                if old.role != role:
                    self._viewer_ids.pop(ident, None)
            peer = _PeerInfo(role, db_set, node_id, session_id)
            self._peers[ident] = peer
            self._by_role.setdefault(role, set()).add(ident)
            self._by_node_id[node_id] = ident
            viewer_id = None
            if role == "viewer":
                if ident in self._viewer_ids:
                    viewer_id = self._viewer_ids[ident]
                else:
                    used = set(self._viewer_ids.values())
                    vid = 1
                    while vid in used:
                        vid += 1
                    self._viewer_ids[ident] = vid
                    viewer_id = vid
                if old_session_id and old_session_id != session_id:
                    self._sync_active_profiles()
                else:
                    self._on_viewer_connected(session_id)
            AppLogger.info(f"peer added: {node_id} role={role} db={db_set} session={session_id}")
            return viewer_id

    def _unregister_peer(self, ident: bytes):
        with self._lock:
            peer = self._peers.pop(ident, None)
            if not peer:
                return
            AppLogger.info(f"peer removed: {peer.node_id}")
            self._by_role.get(peer.role, set()).discard(ident)
            self._by_node_id.pop(peer.node_id, None)
            self._viewer_ids.pop(ident, None)
            if peer.role == "viewer":
                self._on_viewer_disconnected()

    def _refresh_peer(self, ident: bytes):
        with self._lock:
            peer = self._peers.get(ident)
            if peer:
                peer.last_seen = time.monotonic()

    def _resolve_targets(self, msg: Message, sender_ident: bytes | None) -> list[bytes]:
        with self._lock:
            if msg.destination in self._by_node_id:
                ident = self._by_node_id[msg.destination]
                return [ident] if ident != sender_ident else []

            if msg.destination == "ALL":
                candidates = set(self._peers.keys())
            elif msg.destination in self._by_role:
                candidates = set(self._by_role[msg.destination])
            else:
                return []

            if sender_ident:
                candidates.discard(sender_ident)

            if msg.db:
                candidates = {i for i in candidates if not self._peers[i].db_set or msg.db in self._peers[i].db_set}

            return list(candidates)

    def _route_msg(self, ident: bytes, msg: Message):
        topic = msg.topic

        if topic == "mgmt.register":
            payload = msg.payload if isinstance(msg.payload, dict) else {}
            role = payload.get("role", "")
            db_raw = payload.get("db", "")
            session_id = payload.get("session_id", "")
            node_id = msg.source
            if isinstance(db_raw, list):
                db_set = set(db_raw)
            elif db_raw:
                db_set = {db_raw}
            else:
                db_set = set()
            viewer_id = self._register_peer(ident, role, db_set, node_id, session_id)
            reply_payload = {"status": "ok", "node_id": node_id}
            if viewer_id is not None:
                reply_payload["viewer_id"] = viewer_id
            reply = msg.reply(reply_payload, topic="mgmt.registered")
            try_put(self._direct_q, (ident, reply.to_frames()))
            AppLogger.info(f"registered: {node_id} role={role} db={db_set}")
            return

        if topic == "mgmt.unregister":
            self._unregister_peer(ident)
            return

        if topic == "mgmt.heartbeat":
            with self._lock:
                known = ident in self._peers
            if not known:
                reply = msg.reply(None, topic="mgmt.not_registered")
                try_put(self._direct_q, (ident, reply.to_frames()))
                return
            self._refresh_peer(ident)
            pong = msg.reply(None, topic="mgmt.pong")
            try_put(self._direct_q, (ident, pong.to_frames()))
            return

        if topic == "mgmt.get_count":
            counts = self.peer_counts()
            reply = msg.reply(counts, topic="mgmt.count_reply")
            try_put(self._direct_q, (ident, reply.to_frames()))
            return

        exclude = ident if topic != "dev.log" else None
        targets = self._resolve_targets(msg, sender_ident=exclude)
        if not targets:
            return

        frames = msg.to_frames()

        if msg.request_id:
            for t in targets:
                try_put(self._direct_q, (t, frames))
            return

        if msg.coalesce:
            key = (msg.topic, msg.destination, msg.db)
            self._broadcast_q.put(key, (targets, frames))
        elif msg.priority == Priority.HIGH:
            for t in targets:
                try_put(self._high_q, (t, frames))
        elif msg.priority == Priority.LOW:
            for t in targets:
                try_put(self._low_q, (t, frames))
        else:
            for t in targets:
                try_put(self._mid_q, (t, frames))

    def _deliver_batch(self, items, did_work):
        for ident, frames in items:
            try:
                self._router.send_multipart([ident, *frames], copy=False)
                did_work = True
            except zmq.Again:
                AppLogger.debug("broker: drop direct (timeout)")
            except zmq.ZMQError as e:
                if e.errno != zmq.EHOSTUNREACH:
                    AppLogger.debug(f"broker: send error {e}")
        return did_work

    def _io_loop(self):
        poller = zmq.Poller()
        poller.register(self._router, zmq.POLLIN)
        idle_streak, poll_ms = 0, POLL_BASE_MS

        while not self._stop.is_set():
            try:
                events = dict(poller.poll(poll_ms))
            except zmq.ZMQError as e:
                AppLogger.warning(f"broker _io_loop poll error, exiting: {e}")
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
                    msg = Message.from_frames([bytes(f) for f in frames[1:]])
                    if msg:
                        self._route_msg(ident, msg)
                    did_work = True

            batch, sentinel = drain_queue(self._direct_q, self._sentinel)
            did_work = self._deliver_batch(batch, did_work)
            if sentinel:
                break

            for q in (self._high_q, self._mid_q):
                items, _ = drain_queue(q, self._sentinel)
                did_work = self._deliver_batch(items, did_work)

            for _key, (targets, frames) in self._broadcast_q.drain():
                for t in targets:
                    try:
                        self._router.send_multipart([t, *frames], copy=False)
                        did_work = True
                    except zmq.Again:
                        pass
                    except zmq.ZMQError as e:
                        if e.errno != zmq.EHOSTUNREACH:
                            AppLogger.debug(f"broker: bcast error {e}")

            low_items, _ = drain_queue(self._low_q, self._sentinel)
            did_work = self._deliver_batch(low_items, did_work)

            idle_streak, poll_ms = adaptive_poll(did_work, idle_streak)

    def _reaper_loop(self):
        while not self._stop.is_set():
            now = time.monotonic()
            with self._lock:
                stale = [(ident, peer.node_id) for ident, peer in self._peers.items() if now - peer.last_seen > HEARTBEAT_TIMEOUT]
            for ident, node_id in stale:
                AppLogger.info(f"pruning stale peer: {node_id}")
                self._unregister_peer(ident)
            self._stop.wait(1)

    def set_profile_store_factory(self, factory):
        self._profile_store_factory = factory

    def _get_profile_store(self):
        if self._profile_store_factory:
            return self._profile_store_factory()
        from ..profile import ProfileStore

        return ProfileStore.instance()

    def active_viewer_profile_ids(self) -> list[str]:
        with self._lock:
            viewer_idents = self._by_role.get("viewer", set())
            return [self._peers[i].session_id for i in viewer_idents if i in self._peers and self._peers[i].session_id]

    def _on_viewer_connected(self, session_id: str):
        if not session_id:
            return
        try:
            store = self._get_profile_store()
            restore = store.get_restore_profile_ids()
            if session_id not in restore:
                restore.append(session_id)
                store.set_restore_profile_ids(restore)
            active = store.get_active_profile_ids()
            if session_id not in active:
                active.append(session_id)
                store.set_active_profile_ids(active)
        except Exception as e:
            AppLogger.warning(f"_on_viewer_connected failed: {e}", exc=e)

    def _on_viewer_disconnected(self):
        self._cancel_restore_debounce()
        self._restore_debounce = threading.Timer(self._restore_debounce_sec, self._debounce_fire)
        self._restore_debounce.daemon = True
        self._restore_debounce.start()

    def _cancel_restore_debounce(self):
        if self._restore_debounce is not None:
            self._restore_debounce.cancel()
            self._restore_debounce = None

    def _debounce_fire(self):
        try:
            active = self.active_viewer_profile_ids()
            store = self._get_profile_store()
            store.set_active_profile_ids(active)
            if active:
                store.set_restore_profile_ids(list(active))
        except Exception as e:
            AppLogger.warning(f"_debounce_fire failed: {e}", exc=e)

    def _sync_active_profiles(self):
        try:
            active = self.active_viewer_profile_ids()
            store = self._get_profile_store()
            store.set_active_profile_ids(active)
            store.set_restore_profile_ids(list(active))
        except Exception as e:
            AppLogger.warning(f"_sync_active_profiles failed: {e}", exc=e)

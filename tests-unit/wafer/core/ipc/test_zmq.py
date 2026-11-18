import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest
import zmq

from wafer.core.common.profile import current_profile
from wafer.core.ipc import transport
from wafer.core.ipc.transport import Priority, close_socket
from wafer.core.logs import AppLogger
from wafer.core.ipc.broker import Broker, _CoalescingQueue, _PeerInfo
from wafer.core.ipc.message import Message
from wafer.core.ipc.node import Node
from wafer.core.store.workspace import WindowSlot, WorkspaceStore


FAST_NODE_TIMEOUT = 1.0
FAST_BROKER_LOST_TIMEOUT = 1.0


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


@pytest.fixture
def fast_heartbeat(monkeypatch):
    monkeypatch.setattr("wafer.core.ipc.node.HEARTBEAT_INTERVAL", FAST_NODE_TIMEOUT / 5)
    monkeypatch.setattr("wafer.core.ipc.node.NODE_TIMEOUT", FAST_NODE_TIMEOUT)
    monkeypatch.setattr("wafer.core.ipc.node.RECONNECT_FORCE_INTERVAL", FAST_NODE_TIMEOUT)
    monkeypatch.setattr("wafer.core.ipc.transport.ZMQ_SNDTIMEO_MS", 100)


class TestMessage:
    def test_roundtrip(self):
        msg = Message.build("db.update", {"count": 42}, src="idx-1", dst="viewer", db="photos")
        frames = msg.to_frames()
        assert len(frames) == 2
        restored = Message.from_frames(frames)
        assert restored.topic == "db.update"
        assert restored.source == "idx-1"
        assert restored.destination == "viewer"
        assert restored.db == "photos"
        assert restored.payload == {"count": 42}
        assert restored.request_id is None
        assert restored.priority == Priority.MID

    def test_roundtrip_with_request_id(self):
        rid = Message.make_request_id("test-")
        msg = Message.build("query", "data", rid=rid)
        restored = Message.from_frames(msg.to_frames())
        assert restored.request_id == rid

    def test_roundtrip_with_qos(self):
        for pri_val in (Priority.HIGH, Priority.MID, Priority.LOW):
            msg = Message.build("test", "data", priority=pri_val)
            restored = Message.from_frames(msg.to_frames())
            assert restored.priority == pri_val
            assert restored.coalesce is False
        coalesce_msg = Message.build("test", "data", coalesce=True)
        restored = Message.from_frames(coalesce_msg.to_frames())
        assert restored.coalesce is True

    def test_reply(self):
        original = Message.build("request", "hello", src="a", dst="b", db="db1", rid="r1")
        reply = original.reply({"ok": True}, topic="response")
        assert reply.topic == "response"
        assert reply.source == "b"
        assert reply.destination == "a"
        assert reply.db == "db1"
        assert reply.request_id == "r1"
        assert reply.payload == {"ok": True}

    def test_from_frames_invalid(self):
        assert Message.from_frames([b"only_one"]) is None
        assert Message.from_frames([]) is None

    def test_payload_types(self):
        for value in [42, 3.14, True, None, [1, 2], {"a": "b"}, "text"]:
            msg = Message.build("test", value)
            restored = Message.from_frames(msg.to_frames())
            assert restored.payload == value


class TestCoalescingQueue:
    def test_put_and_drain(self):
        q = _CoalescingQueue(10)
        q.put("a", 1)
        q.put("b", 2)
        q.put("a", 3)
        result = q.drain()
        assert result == [("a", 3), ("b", 2)]

    def test_maxsize(self):
        q = _CoalescingQueue(2)
        q.put("a", 1)
        q.put("b", 2)
        q.put("c", 3)
        result = q.drain()
        keys = [k for k, _ in result]
        assert "a" not in keys
        assert "b" in keys
        assert "c" in keys

    def test_drain_empty(self):
        q = _CoalescingQueue(10)
        assert q.drain() == []


class TestBrokerNode:
    def test_register_and_counts(self):
        broker = Broker()
        broker.start()
        try:
            node = Node("viewer", db="photos")
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert node.viewer_id == 1
            assert _wait_until(lambda: broker.peer_counts().get("viewer", 0) >= 1)
        finally:
            node.stop()
            broker.stop()

    def test_broadcast_to_viewers(self, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        try:
            idx = Node("indexer", db="photos")
            idx.start(broker.port)
            idx.wait_registered(timeout=3.0)

            v = Node("viewer")
            v.subscribe("db.update", lambda msg: received.append(msg) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            idx.send("db.update", {"count": 10}, dst="viewer")
            flush_ipc(idx, v)
            assert len(received) >= 1
            assert received[0].topic == "db.update"
            assert received[0].payload == {"count": 10}
        finally:
            v.stop()
            idx.stop()
            broker.stop()

    def test_on_handler(self, flush_ipc):
        broker = Broker()
        broker.start()
        results = []
        try:
            node = Node("indexer", db="photos")
            node.subscribe("work.assigned", lambda msg: results.append(msg.payload) or True)
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            broker.dispatch(Message.build("work.assigned", "task1", dst="indexer"))
            assert _wait_until(lambda: results)
            flush_ipc(node)
            assert results == ["task1"]
        finally:
            node.stop()
            broker.stop()

    def test_request_reply(self):
        broker = Broker()
        broker.start()
        try:
            v1 = Node("viewer", db="photos")
            v1.start(broker.port)
            v1.wait_registered(timeout=3.0)

            idx = Node("indexer", db="photos")
            idx.start(broker.port)
            idx.wait_registered(timeout=3.0)

            reply = v1.request("mgmt.get_count", timeout=3.0)
            assert reply is not None
            assert reply.payload.get("viewer", 0) == 1
            assert reply.payload.get("indexer", 0) == 1
        finally:
            idx.stop()
            v1.stop()
            broker.stop()

    def test_inject(self, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        try:
            v = Node("viewer")
            v.subscribe("sys.notify", lambda msg: received.append(msg) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            broker.dispatch(Message.build("sys.notify", True, dst="viewer"))
            assert _wait_until(lambda: received)
            flush_ipc(v)
            assert len(received) >= 1
            assert received[0].payload == True
        finally:
            v.stop()
            broker.stop()

    def test_db_filter(self, flush_ipc):
        broker = Broker()
        broker.start()
        v_msgs = []
        c_msgs = []
        try:
            idx_ill = Node("indexer", db="illustrations")
            idx_ill.start(broker.port)
            idx_ill.wait_registered(timeout=3.0)

            v = Node("viewer", db="photos")
            v.subscribe("db.progress", lambda m: v_msgs.append(m) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            c_all = Node("tray", db=["photos", "illustrations"])
            c_all.subscribe("db.progress", lambda m: c_msgs.append(m) or True)
            c_all.start(broker.port)
            c_all.wait_registered(timeout=3.0)

            idx_ill.send("db.progress", 50)
            flush_ipc(idx_ill, v, c_all)

            assert len(c_msgs) >= 1
            assert len(v_msgs) == 0
        finally:
            c_all.stop()
            v.stop()
            idx_ill.stop()
            broker.stop()

    def test_sender_exclusion(self, flush_ipc):
        broker = Broker()
        broker.start()
        own_msgs = []
        try:
            node = Node("indexer", db="photos")
            node.subscribe("broadcast", lambda m: own_msgs.append(m) or True)
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            node.send("broadcast", "hello")
            flush_ipc(node, node)
            assert len(own_msgs) == 0
        finally:
            node.stop()
            broker.stop()


class TestQoSRouting:
    def test_latest_coalesces(self, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node("indexer", db="photos")
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node("viewer")
            viewer.subscribe("progress", lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(10):
                sender.send_coalesced("progress", i, dst="viewer", db="photos")
            flush_ipc(sender, viewer)

            assert len(received) >= 1
            assert received[-1] >= 5
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_ordered_all_delivered(self, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node("indexer", db="photos")
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node("viewer")
            viewer.subscribe("update", lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(5):
                sender.send("update", i, dst="viewer", priority=Priority.HIGH)
            flush_ipc(sender, viewer)

            assert received == [0, 1, 2, 3, 4]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_low_priority(self, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        try:
            sender = Node("indexer", db="photos")
            sender.start(broker.port)
            sender.wait_registered(timeout=3.0)

            viewer = Node("viewer")
            viewer.subscribe("dev.log", lambda m: received.append(m.payload) or True)
            viewer.start(broker.port)
            viewer.wait_registered(timeout=3.0)

            for i in range(3):
                sender.send("dev.log", {"n": i}, dst="viewer", priority=Priority.LOW)
            flush_ipc(sender, viewer)

            assert len(received) == 3
            assert [r["n"] for r in received] == [0, 1, 2]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()


@pytest.mark.usefixtures("fast_heartbeat")
class TestReconnection:
    def test_node_reconnects_after_broker_restart(self, flush_ipc):
        broker1 = Broker()
        broker1.start()
        received = []
        try:
            node = Node("viewer")
            node.subscribe("ping", lambda m: received.append(m.payload) or True)
            node.start(broker1.port)
            assert node.wait_registered(timeout=3.0)

            sender1 = Node("indexer", db="photos")
            sender1.start(broker1.port)
            sender1.wait_registered(timeout=3.0)
            sender1.send("ping", "before", dst="viewer")
            flush_ipc(sender1, node)
            assert "before" in received
        finally:
            sender1.stop()
            broker1.stop()

        with patch("wafer.core.ipc.node.read_broker_port") as mock_read:
            broker2 = Broker()
            broker2.start()
            mock_read.return_value = broker2.port
            try:
                assert _wait_until(lambda: broker2.peer_counts().get("viewer", 0) == 1, timeout=10.0)
                assert node.wait_registered(timeout=5.0)

                sender2 = Node("indexer", db="photos")
                sender2.start(broker2.port)
                sender2.wait_registered(timeout=3.0)
                sender2.send("ping", "after", dst="viewer")
                flush_ipc(sender2, node)
                assert "after" in received
            finally:
                sender2.stop()
                node.stop()
                broker2.stop()

    def test_node_reconnects_to_new_port(self, flush_ipc):
        broker1 = Broker()
        broker1.start()
        received = []
        try:
            node = Node("viewer")
            node.subscribe("data", lambda m: received.append(m.payload) or True)
            node.start(broker1.port)
            assert node.wait_registered(timeout=3.0)
            old_port = node._current_port
        finally:
            broker1.stop()

        with patch("wafer.core.ipc.node.read_broker_port") as mock_read:
            broker2 = Broker()
            broker2.start()
            mock_read.return_value = broker2.port
            try:
                assert _wait_until(
                    lambda: node._current_port == broker2.port and broker2.peer_counts().get("viewer", 0) == 1,
                    timeout=10.0,
                )
                assert node.wait_registered(timeout=5.0)
                assert node._current_port == broker2.port

                sender = Node("indexer", db="photos")
                sender.start(broker2.port)
                sender.wait_registered(timeout=3.0)
                sender.send("data", "new_broker", dst="viewer")
                flush_ipc(sender, node)
                assert "new_broker" in received
            finally:
                sender.stop()
                node.stop()
                broker2.stop()

    def test_a_failed_heartbeat_does_not_stop_the_node(self):
        broker = Broker()
        broker.start()
        try:
            with patch("wafer.core.ipc.node.read_broker_port", side_effect=[PermissionError("locked")] + [broker.port] * 1000):
                node = Node("viewer")
                node.start(broker.port)
                assert node.wait_registered(timeout=5.0)
                assert node._io_thread.is_alive()
        finally:
            node.stop()
            broker.stop()

    def test_node_stays_connected_while_broker_alive(self):
        broker = Broker()
        broker.start()
        try:
            node = Node("viewer")
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            port_at_start = node._current_port
            connected_at = node._last_connect_time

            assert not _wait_until(
                lambda: not node.is_registered or node._last_connect_time != connected_at,
                timeout=2 * FAST_NODE_TIMEOUT,
            )
            assert node._registered.is_set()
            assert node._current_port == port_at_start
        finally:
            node.stop()
            broker.stop()


class TestStalledNode:
    """A plugin holding the GIL (a model load) stops the IO thread right after its poll returned empty."""

    def _registered_without_io_thread(self, broker, handler):
        node = Node("stalled")
        node.subscribe("work", handler)
        node._connect(broker.port)
        node._send_to_broker("mgmt.register", node._register_payload())
        assert node._dealer.poll(3000)
        node._handle_received(Message.from_frames([bytes(f) for f in node._dealer.recv_multipart()]))
        assert node.is_registered
        return node

    def _stall_past_the_timeouts(self, node):
        long_ago = time.monotonic() - 100.0
        node._last_recv = long_ago
        node._last_connect_time = long_ago

    def test_message_waiting_in_the_socket_survives_the_stall(self):
        broker = Broker()
        broker.start()
        received = []
        sender = Node("sender")
        node = None
        try:
            sender.start(broker.port)
            assert sender.wait_registered(timeout=3.0)
            node = self._registered_without_io_thread(broker, lambda msg: received.append(msg.payload) or True)
            dealer = node._dealer

            sender.send("work", {"n": 1}, dst="stalled")
            assert dealer.poll(3000)
            self._stall_past_the_timeouts(node)
            node._ensure_connection()

            assert received == [{"n": 1}]
            assert node._dealer is dealer
            assert node.is_registered
        finally:
            if node:
                node._dealer.close(linger=0)
            sender.stop()
            broker.stop()

    def test_message_waiting_when_the_broker_says_not_registered_survives_the_reconnect(self):
        broker = Broker()
        broker.start()
        received = []
        sender = Node("sender")
        node = None
        try:
            sender.start(broker.port)
            assert sender.wait_registered(timeout=3.0)
            node = self._registered_without_io_thread(broker, lambda msg: received.append(msg.payload) or True)

            sender.send("work", {"n": 1}, dst="stalled")
            assert node._dealer.poll(3000)
            node._registered.clear()
            self._stall_past_the_timeouts(node)
            node._ensure_connection()

            assert received == [{"n": 1}]
        finally:
            if node:
                node._dealer.close(linger=0)
            sender.stop()
            broker.stop()


class TestUndeliveredReliable:
    @pytest.fixture(autouse=True)
    def _isolated_outbox(self, tmp_path, monkeypatch):
        outbox_dir = tmp_path / "outbox"
        outbox_dir.mkdir()
        monkeypatch.setattr("wafer.core.ipc.outbox._OUTBOX_DIR", str(outbox_dir))

    def test_nothing_is_undelivered_before_any_reliable_send(self):
        node = Node("sender")
        assert node.nudge_undelivered("work", dst="late") is False

    def test_message_reaches_a_consumer_that_registers_later_without_polling(self):
        broker = Broker()
        broker.start()
        received = []
        sender = Node("sender")
        consumer = Node("late", consumer=True, outbox_poll=None)
        consumer.subscribe("work", lambda msg: received.append(msg.payload) or True)
        try:
            sender.start(broker.port)
            assert sender.wait_registered(timeout=3.0)
            sender.send_reliable("work", {"n": 1}, dst="late")
            assert sender.nudge_undelivered("work", dst="late") is True
            assert sender.nudge_undelivered("other", dst="late") is False
            assert sender.nudge_undelivered("work", dst="someone-else") is False

            consumer.start(broker.port)
            assert consumer.wait_registered(timeout=3.0)

            def delivered():
                return not sender.nudge_undelivered("work", dst="late")

            assert _wait_until(delivered, timeout=5.0)
            assert received == [{"n": 1}]
        finally:
            consumer.stop()
            sender.stop()
            broker.stop()

    def test_message_stays_undelivered_while_nobody_handles_it(self):
        broker = Broker()
        broker.start()
        consumer = Node("late", consumer=True, outbox_poll=None)
        sender = Node("sender")
        try:
            sender.start(broker.port)
            consumer.start(broker.port)
            assert sender.wait_registered(timeout=3.0)
            assert consumer.wait_registered(timeout=3.0)
            handled = threading.Event()
            consumer.subscribe("work", lambda msg: handled.set() or False)

            sender.send_reliable("work", {"n": 1}, dst="late")

            assert handled.wait(timeout=3.0)
            assert sender.nudge_undelivered("work", dst="late") is True
        finally:
            consumer.stop()
            sender.stop()
            broker.stop()


class TestProfileTracking:
    def _make_broker(self, tmp_path, slot_ids=()):
        from wafer.core.store.workspace import WorkspaceStore, WindowSlot

        store_path = str(tmp_path / "workspace.json")
        store = WorkspaceStore(path=store_path)
        for sid in slot_ids:
            store.save_slot(WindowSlot(slot_id=sid))
        broker = Broker()
        broker._restore_debounce_sec = 0.2
        broker.set_workspace_store_factory(lambda: WorkspaceStore(path=store_path))
        return broker, store

    def test_profile_id_in_peer_info(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        broker.start()
        try:
            node = Node("viewer")
            node.session_id = "anon-1"
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert _wait_until(lambda: broker.active_viewer_slot_ids() == ["anon-1"])
        finally:
            node.stop()
            broker.stop()

    def test_viewer_connect_updates_restore_and_active(self, tmp_path):
        broker, store = self._make_broker(tmp_path, slot_ids=["anon-1"])
        broker.start()
        try:
            node = Node("viewer")
            node.session_id = "anon-1"
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert _wait_until(lambda: "anon-1" in store.get_restore_slot_ids() and "anon-1" in store.get_active_slot_ids())
        finally:
            node.stop()
            broker.stop()

    def test_debounce_single_close_updates_restore(self, tmp_path):
        broker, store = self._make_broker(tmp_path, slot_ids=["anon-1", "anon-2"])
        broker.start()
        try:
            n1 = Node("viewer")
            n1.session_id = "anon-1"
            n1.start(broker.port)
            n1.wait_registered(timeout=3.0)

            n2 = Node("viewer")
            n2.node_id = "viewer-2"
            n2.session_id = "anon-2"
            n2.start(broker.port)
            n2.wait_registered(timeout=3.0)
            assert _wait_until(lambda: {"anon-1", "anon-2"} <= set(store.get_active_slot_ids()))

            n1.stop()
            assert _wait_until(
                lambda: "anon-2" in store.get_restore_slot_ids() and "anon-1" not in store.get_restore_slot_ids(),
                timeout=3.0,
            )
        finally:
            n2.stop()
            broker.stop()

    def test_debounce_all_close_preserves_restore(self, tmp_path):
        broker, store = self._make_broker(tmp_path, slot_ids=["anon-1", "anon-2"])
        broker.start()
        try:
            n1 = Node("viewer")
            n1.session_id = "anon-1"
            n1.start(broker.port)
            n1.wait_registered(timeout=3.0)

            n2 = Node("viewer")
            n2.node_id = "viewer-2"
            n2.session_id = "anon-2"
            n2.start(broker.port)
            n2.wait_registered(timeout=3.0)
            assert _wait_until(lambda: {"anon-1", "anon-2"} <= set(store.get_active_slot_ids()))

            n1.stop()
            n2.stop()
            assert _wait_until(lambda: store.get_active_slot_ids() == [], timeout=broker._restore_debounce_sec + 3.0)

            restore = store.get_restore_slot_ids()
            assert "anon-1" in restore
            assert "anon-2" in restore
        finally:
            broker.stop()

    def test_node_session_id_sent_in_registration(self):
        broker = Broker()
        broker.start()
        try:
            node = Node("viewer")
            node.session_id = "Work"
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert _wait_until(lambda: "Work" in broker.active_viewer_slot_ids())
        finally:
            node.stop()
            broker.stop()

    def test_unregister_sent_on_stop(self):
        broker = Broker()
        broker.start()
        try:
            with patch("wafer.core.ipc.node.read_broker_port", return_value=broker.port):
                node = Node("viewer")
                node.start(broker.port)
                assert node.wait_registered(timeout=3.0)
                assert broker.peer_counts().get("viewer", 0) >= 1

                node.stop()
            assert _wait_until(lambda: broker.peer_counts().get("viewer", 0) == 0, timeout=1.5)
        finally:
            broker.stop()

    def test_stop_cancels_pending_restore_debounce(self):
        calls = []
        broker = Broker()
        broker._restore_debounce_sec = 0.2
        broker.set_workspace_store_factory(
            lambda: SimpleNamespace(
                set_active_slot_ids=lambda ids: calls.append(("active", list(ids))),
                set_restore_slot_ids=lambda ids: calls.append(("restore", list(ids))),
            )
        )
        broker.start()
        try:
            broker._on_restorable_peer_disconnected()
            pending = broker._restore_debounce
            assert pending is not None
            broker.stop()
            pending.join(timeout=broker._restore_debounce_sec + 2.0)
            assert not pending.is_alive()
            assert calls == []
        finally:
            if not broker._stop.is_set():
                broker.stop()


class TestRestoreWebUI:
    def _make_broker(self, tmp_path, *, restore_webui=False):
        store_path = str(tmp_path / "workspace.json")
        store = WorkspaceStore(path=store_path)
        store.set_restore_webui(restore_webui)
        broker = Broker()
        broker._restore_debounce_sec = 0.05
        broker.set_workspace_store_factory(lambda: WorkspaceStore(path=store_path))
        broker.start()
        return broker, store

    def _join(self, broker, role, session_id=""):
        node = Node(role)
        node.node_id = f"{role}-{session_id or 'plain'}"
        node.session_id = session_id
        node.start(broker.port)
        assert node.wait_registered(timeout=3.0)
        return node

    def _leave(self, broker, node, role, remaining=0):
        node.stop()
        assert _wait_until(lambda: broker.peer_counts().get(role, 0) == remaining, timeout=6.0)
        pending = broker._restore_debounce
        if pending is not None:
            pending.join(timeout=2.0)

    def test_connecting_records_the_webui(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        node = self._join(broker, "webui", "webui")
        try:
            assert _wait_until(store.get_restore_webui)
        finally:
            node.stop()
            broker.stop()

    def test_a_headless_webui_is_never_recorded(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        viewer = self._join(broker, "viewer", "s1")
        headless = self._join(broker, "webui")
        try:
            assert store.get_restore_webui() is False
            assert broker.is_webui_connected() is False
        finally:
            viewer.stop()
            headless.stop()
            broker.stop()

    def test_a_closing_headless_webui_keeps_the_record(self, tmp_path):
        broker, store = self._make_broker(tmp_path, restore_webui=True)
        viewer = self._join(broker, "viewer", "s1")
        headless = self._join(broker, "webui")
        try:
            self._leave(broker, headless, "webui")
            assert store.get_restore_webui() is True
        finally:
            viewer.stop()
            broker.stop()

    def test_closing_the_webui_before_the_viewer_forgets_it(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        viewer = self._join(broker, "viewer", "s1")
        webui = self._join(broker, "webui", "webui")
        try:
            assert _wait_until(store.get_restore_webui)
            self._leave(broker, webui, "webui")
            assert store.get_restore_webui() is False
            self._leave(broker, viewer, "viewer")
            assert store.get_restore_webui() is False
        finally:
            broker.stop()

    def test_closing_the_viewer_before_the_webui_remembers_both(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        store.save_slot(WindowSlot(slot_id="s1"))
        viewer = self._join(broker, "viewer", "s1")
        webui = self._join(broker, "webui", "webui")
        try:
            assert _wait_until(store.get_restore_webui)
            self._leave(broker, viewer, "viewer")
            assert store.get_restore_webui() is True
            self._leave(broker, webui, "webui")
            assert store.get_restore_webui() is True
            assert store.get_restore_slot_ids() == ["s1"]
        finally:
            broker.stop()

    def test_closing_a_lone_webui_remembers_it(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        webui = self._join(broker, "webui", "webui")
        try:
            assert _wait_until(store.get_restore_webui)
            self._leave(broker, webui, "webui")
            assert store.get_restore_webui() is True
        finally:
            broker.stop()

    def test_closing_a_lone_viewer_leaves_a_forgotten_webui_forgotten(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        viewer = self._join(broker, "viewer", "s1")
        try:
            self._leave(broker, viewer, "viewer")
            assert store.get_restore_webui() is False
        finally:
            broker.stop()

    def test_shutting_everything_down_keeps_the_record_whatever_closes_first(self, tmp_path):
        broker, store = self._make_broker(tmp_path)
        viewer = self._join(broker, "viewer", "s1")
        webui = self._join(broker, "webui", "webui")
        try:
            assert _wait_until(store.get_restore_webui)
            broker.keep_restore_webui()
            self._leave(broker, webui, "webui")
            assert store.get_restore_webui() is True
        finally:
            viewer.stop()
            broker.stop()


@pytest.mark.usefixtures("fast_heartbeat")
class TestBrokerLostTimeout:
    def test_fires_when_broker_unreachable(self):
        fired = threading.Event()
        node = Node("indexer", db="photos", broker_lost_timeout=FAST_BROKER_LOST_TIMEOUT)
        node.on_broker_lost(fired.set)
        node.start(port=59999)
        try:
            start = time.monotonic()
            assert fired.wait(node._broker_lost_timeout + 6.0)
            assert time.monotonic() - start >= node._broker_lost_timeout
            assert node._stop.is_set()
        finally:
            node.stop()

    def test_not_fires_when_broker_alive(self):
        broker = Broker()
        broker.start()
        fired = threading.Event()
        try:
            node = Node("indexer", db="photos", broker_lost_timeout=FAST_BROKER_LOST_TIMEOUT)
            node.on_broker_lost(fired.set)
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            assert not fired.wait(node._broker_lost_timeout + 1.0)
            assert not node._stop.is_set()
        finally:
            node.stop()
            broker.stop()

    def test_fires_after_broker_shutdown(self):
        broker = Broker()
        broker.start()
        fired = threading.Event()
        try:
            node = Node("indexer", db="photos", broker_lost_timeout=FAST_BROKER_LOST_TIMEOUT)
            node.on_broker_lost(fired.set)
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            broker.stop()
            assert fired.wait(12.0)
            assert node._stop.is_set()
        finally:
            node.stop()

    def test_disabled_by_default(self):
        node = Node("viewer", db="photos")
        assert node._broker_lost_timeout is None
        node.start(port=59999)
        try:
            assert not node._stop.wait(2.0)
        finally:
            node.stop()


DEBUG_PROFILE = "debug-x"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def caplog_applogger(monkeypatch):
    logged = SimpleNamespace(warnings=[], infos=[])
    monkeypatch.setattr(AppLogger, "warning", lambda text, exc=None: logged.warnings.append(text))
    monkeypatch.setattr(AppLogger, "info", lambda text: logged.infos.append(text))
    return logged


@pytest.fixture
def short_port_wait(monkeypatch):
    real_read = transport.read_broker_port
    monkeypatch.setattr("wafer.core.ipc.node.read_broker_port", lambda timeout=5.0, *, port_file=None: real_read(min(timeout, 0.2), port_file=port_file))


@pytest.fixture
def running_as_debug_profile(monkeypatch):
    monkeypatch.setattr(sys, "argv", [sys.argv[0], "--profile", DEBUG_PROFILE])
    current_profile.cache_clear()
    yield
    current_profile.cache_clear()


@pytest.fixture
def raw_dealer():
    sockets = []

    def connect(port: int, ident: str = "probe-1") -> zmq.Socket:
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.IDENTITY, ident.encode())
        sock.connect(f"tcp://127.0.0.1:{port}")
        sockets.append(sock)
        return sock

    yield connect
    for sock in sockets:
        sock.close(linger=0)


def _exchange(sock: zmq.Socket, msg: Message) -> Message:
    sock.send_multipart(list(msg.to_frames()))
    assert sock.poll(3000)
    return Message.from_frames(sock.recv_multipart())


def _register(sock: zmq.Socket, **identity) -> Message:
    return _exchange(sock, Message.build("mgmt.register", {"role": "probe", "db": "", "session_id": "", **identity}, src="probe-1", dst="broker"))


def _count_ticks(node: Node) -> list:
    ticks = []
    real_tick = node._heartbeat_tick

    def tick():
        real_tick()
        ticks.append(time.monotonic())

    node._heartbeat_tick = tick
    return ticks


def _worst_random_draw(monkeypatch):
    real_bind = zmq.Socket.bind_to_random_port

    def draw(sock, addr, min_port=49152, max_port=65536, max_tries=100):
        if min_port <= transport.DEFAULT_PORT < max_port:
            return transport.DEFAULT_PORT
        return real_bind(sock, addr, min_port, max_port, max_tries)

    monkeypatch.setattr(zmq.Socket, "bind_to_random_port", draw)


class _FakeBroker:
    def __init__(self, registered_payload: dict):
        self._payload = registered_payload
        self._sock = zmq.Context.instance().socket(zmq.ROUTER)
        self.port = self._sock.bind_to_random_port("tcp://127.0.0.1")
        self.topics: list[str] = []
        self.idents: list[bytes] = []
        self._outgoing: list[tuple[bytes, Message]] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    @property
    def registers(self) -> int:
        with self._lock:
            return self.topics.count("mgmt.register")

    def send_to(self, ident: bytes, msg: Message):
        with self._lock:
            self._outgoing.append((ident, msg))

    def _run(self):
        while not self._stop.is_set():
            if self._sock.poll(20):
                frames = self._sock.recv_multipart()
                msg = Message.from_frames(frames[1:])
                with self._lock:
                    self.topics.append(msg.topic)
                    self.idents.append(frames[0])
                if msg.topic == "mgmt.register":
                    self._sock.send_multipart([frames[0], *msg.reply(self._payload, topic="mgmt.registered").to_frames()])
            with self._lock:
                outgoing, self._outgoing = self._outgoing, []
            for ident, msg in outgoing:
                self._sock.send_multipart([ident, *msg.to_frames()])

    def close(self):
        self._stop.set()
        self._thread.join(timeout=2.0)
        self._sock.close(linger=0)


class TestPortFile:
    def test_current_profile_uses_the_module_port_file(self, tmp_path, monkeypatch):
        replaced = tmp_path / "elsewhere" / "broker.json"
        monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", replaced)
        assert transport.port_file_for(None) == replaced

    def test_other_profile_uses_its_data_root(self, tmp_path):
        assert transport.port_file_for(DEBUG_PROFILE) == tmp_path / "profiles" / DEBUG_PROFILE / "ipc" / "broker.json"

    def test_read_and_write_an_explicit_port_file(self, tmp_path):
        port_file = tmp_path / "other" / "broker.json"
        transport.write_broker_port(12345, port_file=port_file)
        assert transport.read_broker_port(0.1, port_file=port_file) == 12345
        assert transport.read_broker_port(0.1) is None


class TestBrokerIdentity:
    @pytest.mark.parametrize(("profile", "expected"), [(None, ""), (DEBUG_PROFILE, DEBUG_PROFILE)])
    def test_registered_reply_carries_app_and_profile(self, profile, expected, raw_dealer):
        broker = Broker(profile=profile)
        broker.start()
        try:
            reply = _register(raw_dealer(broker.port), app="wafer", profile=expected)
            assert reply.topic == "mgmt.registered"
            assert reply.payload["app"] == "wafer"
            assert reply.payload["profile"] == expected
            assert broker.peer_counts() == {"probe": 1}
        finally:
            broker.stop()

    @pytest.mark.parametrize("identity", [{"app": "wafer", "profile": DEBUG_PROFILE}, {"app": "other", "profile": ""}, {}], ids=["other-profile", "other-app", "no-identity"])
    def test_broker_refuses_a_register_that_is_not_its_own(self, identity, raw_dealer, caplog_applogger):
        broker = Broker()
        broker.start()
        try:
            sock = raw_dealer(broker.port)
            for _ in range(2):
                reply = _register(sock, **identity)
                assert reply.topic == "mgmt.rejected"
                assert reply.payload["app"] == "wafer"
                assert reply.payload["profile"] == ""
            assert broker.peer_counts() == {}
            assert len([text for text in caplog_applogger.warnings if "probe-1" in text]) == 1
        finally:
            broker.stop()

    def test_broker_drops_messages_from_senders_that_are_not_registered(self, raw_dealer, flush_ipc):
        broker = Broker()
        broker.start()
        received = []
        viewer = Node("viewer")
        viewer.subscribe("ping", lambda m: received.append(m.payload) or True)
        try:
            viewer.start(broker.port)
            assert viewer.wait_registered(3.0)
            sock = raw_dealer(broker.port)
            reply = _exchange(sock, Message.build("ping", "stranger", src="probe-1", dst="viewer", rid="rid-1"))
            assert reply.topic == "mgmt.not_registered"
            assert reply.request_id is None
            flush_ipc(viewer)
            assert received == []
        finally:
            viewer.stop()
            broker.stop()

    def test_profiled_broker_never_binds_default_port(self, monkeypatch):
        _worst_random_draw(monkeypatch)
        requested = _free_port()
        broker = Broker(port=requested, profile=DEBUG_PROFILE)
        try:
            assert broker.port not in (requested, transport.DEFAULT_PORT)
        finally:
            close_socket(broker._router)

    def test_fallback_port_is_never_the_default_port(self, monkeypatch):
        _worst_random_draw(monkeypatch)
        with socket.socket() as held:
            held.bind(("127.0.0.1", 0))
            held.listen()
            requested = held.getsockname()[1]
            broker = Broker(port=requested, profile=None)
            try:
                assert broker.port not in (requested, transport.DEFAULT_PORT)
            finally:
                close_socket(broker._router)

    def test_profiled_broker_announces_on_its_own_port_file(self):
        broker = Broker(profile=DEBUG_PROFILE)
        broker.start()
        try:
            assert transport.read_broker_port(1.0, port_file=transport.port_file_for(DEBUG_PROFILE)) == broker.port
            assert transport.read_broker_port(0.1) is None
        finally:
            broker.stop()
        assert not transport.port_file_for(DEBUG_PROFILE).exists()


@pytest.mark.usefixtures("fast_heartbeat")
class TestNodeJoinsOnlyItsOwnBroker:
    def test_node_registers_with_same_profile(self):
        broker = Broker(profile=DEBUG_PROFILE)
        broker.start()
        node = Node("probe", profile=DEBUG_PROFILE)
        try:
            node.start()
            assert node.wait_registered(3.0)
        finally:
            node.stop()
            broker.stop()

    def test_node_leaves_a_broker_of_another_profile_until_its_port_file_names_its_own(self, monkeypatch, caplog_applogger):
        foreign = Broker(profile=DEBUG_PROFILE)
        foreign.start()
        monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", transport.port_file_for(DEBUG_PROFILE))
        node = Node("probe", profile=None)
        ticks = _count_ticks(node)
        own = None
        try:
            node.start()
            assert node._current_port == foreign.port
            assert _wait_until(lambda: node._dealer is None and node._current_port == 0)
            seen = len(ticks)
            assert _wait_until(lambda: len(ticks) >= seen + 3)
            assert not node.is_registered
            assert foreign.peer_counts() == {}
            assert len([text for text in caplog_applogger.warnings if text.startswith("refused ")]) == 1
            assert len([text for text in caplog_applogger.warnings if node.node_id in text and "disconnected" in text]) == 1

            own = Broker(profile=None)
            own.start()
            assert node.wait_registered(5.0)
            assert node._current_port == own.port
        finally:
            node.stop()
            foreign.stop()
            if own:
                own.stop()

    def test_node_stays_away_from_a_rejected_broker_until_the_port_file_is_rewritten(self):
        fake = _FakeBroker({"status": "ok", "node_id": "probe"})
        transport.write_broker_port(fake.port)
        received = []
        node = Node("probe")
        node.subscribe("ping", lambda m: received.append(m.payload) or True)
        ticks = _count_ticks(node)
        try:
            node.start()
            assert _wait_until(lambda: fake.registers == 1 and node._dealer is None)
            fake.send_to(fake.idents[0], Message.build("ping", "from the foreign broker", src="foreign", dst="probe"))
            node.send("work", "must stay here")
            seen = len(ticks)
            assert _wait_until(lambda: len(ticks) >= seen + 3)
            assert fake.registers == 1
            assert received == []

            transport.write_broker_port(fake.port)
            assert _wait_until(lambda: fake.registers == 2)
            assert _wait_until(lambda: node._dealer is None)
            seen = len(ticks)
            assert _wait_until(lambda: len(ticks) >= seen + 3)
            assert "work" not in fake.topics
            assert received == []
        finally:
            node.stop()
            fake.close()

    def test_node_follows_the_current_profile_when_omitted(self, running_as_debug_profile):
        broker = Broker()
        broker.start()
        same = Node("probe")
        plain = Node("plain", profile=None)
        try:
            assert broker.port != transport.DEFAULT_PORT
            same.start()
            plain.start(broker.port)
            assert same.wait_registered(3.0)
            assert not plain.wait_registered(1.0)
        finally:
            same.stop()
            plain.stop()
            broker.stop()

    @pytest.mark.usefixtures("short_port_wait")
    def test_node_without_port_file_does_not_connect(self):
        node = Node("probe")
        try:
            node.start()
            assert node._current_port == 0
            assert node._dealer is None
            assert not node.wait_registered(0.5)
            assert node._current_port == 0
        finally:
            node.stop()

    @pytest.mark.usefixtures("short_port_wait")
    def test_node_connects_once_the_port_is_announced(self):
        node = Node("probe")
        node.start()
        broker = Broker()
        try:
            broker.start()
            assert node.wait_registered(5.0)
            assert node._current_port == broker.port
        finally:
            node.stop()
            broker.stop()

    def test_node_warns_once_for_foreign_port(self, caplog_applogger):
        listener = socket.socket()
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(0.2)
        accepted = []
        stop = threading.Event()

        def accept_loop():
            while not stop.is_set():
                try:
                    accepted.append(listener.accept()[0])
                except TimeoutError:
                    continue

        acceptor = threading.Thread(target=accept_loop, daemon=True)
        acceptor.start()
        transport.write_broker_port(listener.getsockname()[1])
        node = Node("probe")
        try:
            node.start()
            assert _wait_until(lambda: len(accepted) >= 3, timeout=10.0)
            assert not node.is_registered
            assert len(caplog_applogger.warnings) == 1
        finally:
            node.stop()
            stop.set()
            acceptor.join(timeout=2.0)
            for conn in accepted:
                conn.close()
            listener.close()

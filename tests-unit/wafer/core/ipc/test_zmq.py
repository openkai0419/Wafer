import py_compile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

from wafer.core.ipc.transport import NODE_TIMEOUT, Priority
from wafer.core.ipc.broker import Broker, _CoalescingQueue, _PeerInfo
from wafer.core.ipc.message import Message
from wafer.core.ipc.node import Node


def _wait_until(predicate, timeout=5.0, interval=0.05):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return predicate()


def test_compile():
    py_compile.compile("wafer/core/ipc/message.py")
    py_compile.compile("wafer/core/ipc/broker.py")
    py_compile.compile("wafer/core/ipc/node.py")
    py_compile.compile("wafer/core/ipc/transport.py")
    py_compile.compile("wafer/core/ipc/outbox.py")


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
            time.sleep(0.3)
            counts = broker.peer_counts()
            assert counts.get("viewer", 0) >= 1
        finally:
            node.stop()
            broker.stop()

    def test_broadcast_to_viewers(self):
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
            time.sleep(0.5)
            assert len(received) >= 1
            assert received[0].topic == "db.update"
            assert received[0].payload == {"count": 10}
        finally:
            v.stop()
            idx.stop()
            broker.stop()

    def test_on_handler(self):
        broker = Broker()
        broker.start()
        results = []
        try:
            node = Node("indexer", db="photos")
            node.subscribe("work.assigned", lambda msg: results.append(msg.payload) or True)
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            broker.dispatch(Message.build("work.assigned", "task1", dst="indexer"))
            time.sleep(0.5)
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

    def test_inject(self):
        broker = Broker()
        broker.start()
        received = []
        try:
            v = Node("viewer")
            v.subscribe("sys.notify", lambda msg: received.append(msg) or True)
            v.start(broker.port)
            v.wait_registered(timeout=3.0)

            broker.dispatch(Message.build("sys.notify", True, dst="viewer"))
            time.sleep(0.5)
            assert len(received) >= 1
            assert received[0].payload == True
        finally:
            v.stop()
            broker.stop()

    def test_db_filter(self):
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
            time.sleep(0.5)

            assert len(c_msgs) >= 1
            assert len(v_msgs) == 0
        finally:
            c_all.stop()
            v.stop()
            idx_ill.stop()
            broker.stop()

    def test_sender_exclusion(self):
        broker = Broker()
        broker.start()
        own_msgs = []
        try:
            node = Node("indexer", db="photos")
            node.subscribe("broadcast", lambda m: own_msgs.append(m) or True)
            node.start(broker.port)
            node.wait_registered(timeout=3.0)

            node.send("broadcast", "hello")
            time.sleep(0.5)
            assert len(own_msgs) == 0
        finally:
            node.stop()
            broker.stop()


class TestQoSRouting:
    def test_latest_coalesces(self):
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
            time.sleep(0.5)

            assert len(received) >= 1
            assert received[-1] >= 5
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_ordered_all_delivered(self):
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
            time.sleep(0.5)

            assert received == [0, 1, 2, 3, 4]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()

    def test_send_low_priority(self):
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
            time.sleep(0.5)

            assert len(received) == 3
            assert [r["n"] for r in received] == [0, 1, 2]
        finally:
            viewer.stop()
            sender.stop()
            broker.stop()


class TestReconnection:
    def test_node_reconnects_after_broker_restart(self):
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
            time.sleep(0.5)
            assert "before" in received
        finally:
            sender1.stop()
            broker1.stop()

        with patch("wafer.core.ipc.node.read_broker_port") as mock_read:
            broker2 = Broker()
            broker2.start()
            mock_read.return_value = broker2.port
            try:
                time.sleep(NODE_TIMEOUT + 2)
                assert node.wait_registered(timeout=5.0)

                sender2 = Node("indexer", db="photos")
                sender2.start(broker2.port)
                sender2.wait_registered(timeout=3.0)
                sender2.send("ping", "after", dst="viewer")
                time.sleep(0.5)
                assert "after" in received
            finally:
                sender2.stop()
                node.stop()
                broker2.stop()

    def test_node_reconnects_to_new_port(self):
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
                time.sleep(NODE_TIMEOUT + 2)
                assert node.wait_registered(timeout=5.0)
                assert node._current_port == broker2.port

                sender = Node("indexer", db="photos")
                sender.start(broker2.port)
                sender.wait_registered(timeout=3.0)
                sender.send("data", "new_broker", dst="viewer")
                time.sleep(0.5)
                assert "new_broker" in received
            finally:
                sender.stop()
                node.stop()
                broker2.stop()

    def test_node_stays_connected_while_broker_alive(self):
        broker = Broker()
        broker.start()
        try:
            node = Node("viewer")
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            port_at_start = node._current_port

            time.sleep(3)
            assert node._registered.is_set()
            assert node._current_port == port_at_start
        finally:
            node.stop()
            broker.stop()


class TestProfileTracking:
    def _make_broker(self, tmp_path, slot_ids=()):
        from wafer.core.workspace import WorkspaceStore, WindowSlot

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
            time.sleep(0.3)
            assert broker.active_viewer_slot_ids() == ["anon-1"]
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
            time.sleep(0.3)
            assert "anon-1" in store.get_restore_slot_ids()
            assert "anon-1" in store.get_active_slot_ids()
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
            time.sleep(0.3)

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
            time.sleep(0.3)

            n1.stop()
            n2.stop()
            time.sleep(broker._restore_debounce_sec + 0.5)

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
            time.sleep(0.3)
            sids = broker.active_viewer_slot_ids()
            assert "Work" in sids
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
            time.sleep(1.5)
            assert broker.peer_counts().get("viewer", 0) == 0
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
            broker._on_viewer_disconnected()
            broker.stop()
            time.sleep(broker._restore_debounce_sec + 0.2)
            assert calls == []
        finally:
            if not broker._stop.is_set():
                broker.stop()


class TestBrokerLostTimeout:
    def test_fires_when_broker_unreachable(self):
        fired = threading.Event()
        node = Node("indexer", db="photos", broker_lost_timeout=3)
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
            node = Node("indexer", db="photos", broker_lost_timeout=3)
            node.on_broker_lost(fired.set)
            node.start(broker.port)
            assert node.wait_registered(timeout=3.0)
            time.sleep(4.0)
            assert not fired.is_set()
            assert not node._stop.is_set()
        finally:
            node.stop()
            broker.stop()

    def test_fires_after_broker_shutdown(self):
        broker = Broker()
        broker.start()
        fired = threading.Event()
        try:
            node = Node("indexer", db="photos", broker_lost_timeout=3)
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
            time.sleep(2.0)
            assert not node._stop.is_set()
        finally:
            node.stop()


class TestProfileReRegister:
    def _make_broker(self, tmp_path, slot_ids=()):
        from wafer.core.workspace import WorkspaceStore, WindowSlot

        store_path = str(tmp_path / "workspace.json")
        store = WorkspaceStore(path=store_path)
        for sid in slot_ids:
            store.save_slot(WindowSlot(slot_id=sid))
        broker = Broker()
        broker._restore_debounce_sec = 0.2
        broker.set_workspace_store_factory(lambda: WorkspaceStore(path=store_path))
        return broker, store

    def test_re_register_updates_profile_id(self, tmp_path):
        broker, store = self._make_broker(tmp_path, slot_ids=["p1", "p2"])
        broker.start()
        try:
            node = Node("viewer")
            node.session_id = "p1"
            node.start(broker.port)
            assert node.wait_registered(timeout=5.0)
            time.sleep(0.5)
            assert "p1" in broker.active_viewer_slot_ids()

            node.re_register("p2")
            assert node.wait_registered(timeout=5.0)
            time.sleep(0.5)
            active = broker.active_viewer_slot_ids()
            assert "p2" in active
            assert "p1" not in active
        finally:
            node.stop()
            broker.stop()

    def test_re_register_syncs_active_and_restore(self, tmp_path):
        broker, store = self._make_broker(tmp_path, slot_ids=["p1", "p2"])
        broker.start()
        try:
            node = Node("viewer")
            node.session_id = "p1"
            node.start(broker.port)
            assert node.wait_registered(timeout=5.0)
            time.sleep(0.5)
            assert "p1" in store.get_active_slot_ids()

            node.re_register("p2")
            assert node.wait_registered(timeout=5.0)
            time.sleep(0.5)
            assert "p2" in store.get_active_slot_ids()
            assert "p2" in store.get_restore_slot_ids()
        finally:
            node.stop()
            broker.stop()

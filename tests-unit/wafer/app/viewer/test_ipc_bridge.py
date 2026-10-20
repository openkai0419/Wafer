import pytest
from unittest.mock import MagicMock, patch


class _FakeMsg:
    def __init__(self, topic="", payload="", db="", source=""):
        self.topic = topic
        self.payload = payload
        self.db = db
        self.source = source
        self.request_id = ""


@pytest.fixture
def mock_node():
    node = MagicMock()
    node.subscribe.return_value = node
    node.session_id = ""
    return node


@pytest.fixture
def bridge(qtbot, mock_node):
    with patch("wafer.app.viewer.ipc_bridge.AppLogger"):
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

        b = ViewerIpcBridge(mock_node)
        yield b
        ViewerIpcBridge._instance = None


class TestStart:
    def test_start_sets_instance_and_starts_node(self, mock_node, bridge):
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

        bridge.start()
        assert ViewerIpcBridge.instance() is bridge
        mock_node.start.assert_called_once()

    def test_stop_clears_instance(self, mock_node, bridge):
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge

        bridge.start()
        bridge.stop()
        assert ViewerIpcBridge.instance() is None
        mock_node.stop.assert_called_once()


class TestIpcHandlers:
    def test_bridge_emits_slot_renamed(self, qtbot, bridge, mock_node):
        topics = [c.args[0] for c in mock_node.subscribe.call_args_list]
        assert "slot.renamed" in topics
        received = []
        bridge.slot_renamed.connect(lambda sid, name: received.append((sid, name)))
        with qtbot.waitSignal(bridge.slot_renamed, timeout=1000):
            bridge._on_slot_renamed(_FakeMsg(topic="slot.renamed", payload={"slot_id": "s2", "name": "New"}))
        assert received == [("s2", "New")]

    def test_slot_renamed_ignores_malformed_payload(self, bridge):
        received = []
        bridge.slot_renamed.connect(lambda sid, name: received.append((sid, name)))
        assert bridge._on_slot_renamed(_FakeMsg(topic="slot.renamed", payload="oops")) is True
        assert bridge._on_slot_renamed(_FakeMsg(topic="slot.renamed", payload={"name": "x"})) is True
        assert received == []

    def test_on_progress_emits_only_valid_payload(self, qtbot, bridge):
        received = []
        bridge.progress_updated.connect(lambda db, v: received.append((db, v)))
        assert bridge._on_progress(_FakeMsg(topic="progress", payload="abc", db="mydb")) is True
        with qtbot.waitSignal(bridge.progress_updated, timeout=1000):
            bridge._on_progress(_FakeMsg(topic="progress", payload="50", db="mydb"))
        assert received == [("mydb", 50)]

    def test_bridge_replies_only_for_own_slot(self, qtbot, bridge, mock_node):
        from wafer.core.ipc.message import Message

        topics = [c.args[0] for c in mock_node.subscribe.call_args_list]
        assert "slot.open_path" in topics
        mock_node.session_id = "s1"
        received = []
        bridge.open_path_requested.connect(lambda path, db: received.append((path, db)))

        def request(slot_id):
            payload = {"slot_id": slot_id, "path": "C:/a.png", "database_name": "db"}
            return Message.build("slot.open_path", payload, src="launcher-9", dst="viewer", rid="r1")

        assert bridge._on_slot_open_path(request("s2")) is True
        mock_node.enqueue.assert_not_called()

        with qtbot.waitSignal(bridge.open_path_requested, timeout=1000):
            assert bridge._on_slot_open_path(request("s1")) is True
        reply = mock_node.enqueue.call_args.args[0]
        assert (reply.request_id, reply.destination, reply.payload) == ("r1", "launcher-9", {"ok": True})
        assert received == [("C:/a.png", "db")]

    def test_open_path_ignores_malformed_payload(self, bridge, mock_node):
        from wafer.core.ipc.message import Message

        mock_node.session_id = "s1"
        received = []
        bridge.open_path_requested.connect(lambda path, db: received.append((path, db)))
        for payload in ("oops", {"slot_id": "s1"}, {"slot_id": "s1", "path": 3}):
            assert bridge._on_slot_open_path(Message.build("slot.open_path", payload, rid="r")) is True
        mock_node.enqueue.assert_not_called()
        assert received == []

    def test_open_path_round_trip_through_the_broker(self, qtbot, tmp_path, monkeypatch):
        from wafer.app.viewer.ipc_bridge import ViewerIpcBridge
        from wafer.core.ipc.broker import Broker
        from wafer.core.ipc.node import Node

        monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", tmp_path / "broker.json")
        broker = Broker()
        broker.start()
        viewer = Node("viewer")
        viewer.session_id = "s1"
        bridge = ViewerIpcBridge(viewer)
        launcher = Node("launcher")
        received = []
        bridge.open_path_requested.connect(lambda path, db: received.append((path, db)))
        try:
            viewer.start(broker.port)
            launcher.start(broker.port)
            assert viewer.wait_registered(3.0) and launcher.wait_registered(3.0)

            payload = {"slot_id": "s2", "path": "C:/a.png", "database_name": ""}
            assert launcher.request("slot.open_path", payload, dst="viewer", timeout=0.3) is None

            payload["slot_id"] = "s1"
            reply = launcher.request("slot.open_path", payload, dst="viewer", timeout=3.0)
            assert reply is not None and reply.payload == {"ok": True}
            qtbot.waitUntil(lambda: received == [("C:/a.png", "")], timeout=1000)
        finally:
            launcher.stop()
            viewer.stop()
            broker.stop()

    def test_on_dev_log_emits_only_dict_payload(self, qtbot, bridge):
        received = []
        bridge.remote_log_received.connect(lambda *a: received.append(a))
        assert bridge._on_dev_log(_FakeMsg(topic="dev.log", payload="notadict")) is True
        with qtbot.waitSignal(bridge.remote_log_received, timeout=1000):
            bridge._on_dev_log(_FakeMsg(topic="dev.log", payload={"level": "error", "text": "boom"}, source="node1", db="db1"))
        assert received == [("error", "boom", "node1", "db1")]

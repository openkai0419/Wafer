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
    def test_on_progress_emits_only_valid_payload(self, qtbot, bridge):
        received = []
        bridge.progress_updated.connect(lambda db, v: received.append((db, v)))
        assert bridge._on_progress(_FakeMsg(topic="progress", payload="abc", db="mydb")) is True
        with qtbot.waitSignal(bridge.progress_updated, timeout=1000):
            bridge._on_progress(_FakeMsg(topic="progress", payload="50", db="mydb"))
        assert received == [("mydb", 50)]

    def test_on_dev_log_emits_only_dict_payload(self, qtbot, bridge):
        received = []
        bridge.remote_log_received.connect(lambda *a: received.append(a))
        assert bridge._on_dev_log(_FakeMsg(topic="dev.log", payload="notadict")) is True
        with qtbot.waitSignal(bridge.remote_log_received, timeout=1000):
            bridge._on_dev_log(_FakeMsg(topic="dev.log", payload={"level": "error", "text": "boom"}, source="node1", db="db1"))
        assert received == [("error", "boom", "node1", "db1")]

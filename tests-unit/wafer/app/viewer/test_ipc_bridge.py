import pytest
from unittest.mock import MagicMock, patch
from PySide6 import QtCore


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


class TestSubscription:
    def test_subscribes_all_topics(self, mock_node, bridge):
        topics = {call.args[0] for call in mock_node.subscribe.call_args_list}
        expected = {
            "update", "folderchanged", "progress", "maximum",
            "show_toggle", "slot.close",
            "slot.restart", "slot.shutdown", "app.shutdown", "db.created", "db.deleted", "dev.log",
            "tags.updated", "settings.changed",
        }
        assert topics == expected


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


class TestSignalEmission:
    def test_db_content_updated(self, qtbot, bridge):
        received = []
        bridge.db_content_updated.connect(received.append)
        bridge._emit_db_content_updated("testdb")
        assert received == ["testdb"]

    def test_folder_changed(self, qtbot, bridge):
        received = []
        bridge.folder_changed.connect(received.append)
        bridge._emit_folder_changed("testdb")
        assert received == ["testdb"]

    def test_progress_updated(self, qtbot, bridge):
        received = []
        bridge.progress_updated.connect(lambda db, v: received.append((db, v)))
        bridge._emit_progress_updated("db1", 42)
        assert received == [("db1", 42)]

    def test_progress_maximum(self, qtbot, bridge):
        received = []
        bridge.progress_maximum.connect(lambda db, v: received.append((db, v)))
        bridge._emit_progress_maximum("db1", 100)
        assert received == [("db1", 100)]

    def test_show_toggled(self, qtbot, bridge):
        received = []
        bridge.show_toggled.connect(lambda db, v: received.append((db, v)))
        bridge._emit_show_toggled("db1", True)
        assert received == [("db1", True)]

    def test_session_closed(self, qtbot, bridge):
        received = []
        bridge.slot_closed.connect(received.append)
        bridge._emit_slot_closed("sess1")
        assert received == ["sess1"]

    def test_session_restarted(self, qtbot, bridge):
        received = []
        bridge.slot_restarted.connect(received.append)
        bridge._emit_slot_restarted("sess1")
        assert received == ["sess1"]

    def test_db_created(self, qtbot, bridge):
        received = []
        bridge.db_created.connect(received.append)
        bridge._emit_db_created("newdb")
        assert received == ["newdb"]

    def test_db_deleted(self, qtbot, bridge):
        received = []
        bridge.db_deleted.connect(received.append)
        bridge._emit_db_deleted("olddb")
        assert received == ["olddb"]

    def test_remote_log(self, qtbot, bridge):
        received = []
        bridge.remote_log_received.connect(lambda *a: received.append(a))
        bridge._emit_remote_log("warning", "test msg", "collector-exif", "db1")
        assert received == [("warning", "test msg", "collector-exif", "db1")]


class TestIpcHandlers:
    def test_on_update_extracts_db(self, bridge):
        msg = _FakeMsg(topic="update", db="mydb")
        result = bridge._on_update(msg)
        assert result is True

    def test_on_progress_extracts_payload(self, bridge):
        msg = _FakeMsg(topic="progress", payload="50", db="mydb")
        result = bridge._on_progress(msg)
        assert result is True

    def test_on_progress_invalid_payload(self, bridge):
        msg = _FakeMsg(topic="progress", payload="abc", db="mydb")
        result = bridge._on_progress(msg)
        assert result is True

    def test_on_maximum_extracts_payload(self, bridge):
        msg = _FakeMsg(topic="maximum", payload="200", db="mydb")
        result = bridge._on_maximum(msg)
        assert result is True

    def test_on_show_toggle(self, bridge):
        msg = _FakeMsg(topic="show_toggle", payload=True, db="db1")
        result = bridge._on_show_toggle(msg)
        assert result is True

    def test_on_db_created(self, bridge):
        msg = _FakeMsg(topic="db.created", payload="newdb")
        result = bridge._on_db_created(msg)
        assert result is True

    def test_on_db_deleted(self, bridge):
        msg = _FakeMsg(topic="db.deleted", payload="olddb")
        result = bridge._on_db_deleted(msg)
        assert result is True

    def test_on_dev_log_dict_payload(self, bridge):
        msg = _FakeMsg(topic="dev.log", payload={"level": "error", "text": "boom"}, source="node1", db="db1")
        result = bridge._on_dev_log(msg)
        assert result is True

    def test_on_dev_log_non_dict_payload(self, bridge):
        msg = _FakeMsg(topic="dev.log", payload="notadict")
        result = bridge._on_dev_log(msg)
        assert result is True

    def test_on_update_empty_db(self, bridge):
        msg = _FakeMsg(topic="update", db="")
        result = bridge._on_update(msg)
        assert result is True


class TestNodeProperty:
    def test_node_returns_wrapped_node(self, mock_node, bridge):
        assert bridge.node is mock_node

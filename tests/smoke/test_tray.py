import time

import pytest
from PySide6 import QtGui

from wafer.core.ipc.node import Node
from wafer.core.ipc.message import Message


def _poll_until(predicate, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.05)
    return predicate()


@pytest.fixture(autouse=True, scope="module")
def _configure_command_store(tmp_path_factory):
    from wafer.core.commands.command.state import CommandOptionStore

    prev = CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path
    CommandOptionStore._instance = None
    CommandOptionStore._initialized = False
    CommandOptionStore._default_path = None
    CommandOptionStore.configure(tmp_path_factory.mktemp("smoke_tray") / "cmd.json")
    from wafer.plugin.loader import get_command_registry

    get_command_registry().activate("tray")
    yield
    CommandOptionStore._instance, CommandOptionStore._initialized, CommandOptionStore._default_path = prev


class TestSmokeTray:
    def test_tray_boots_with_broker(self, qtbot):
        from wafer.app.tray.main_tray import TrayApp

        icon = QtGui.QIcon()
        tray = TrayApp(icon)
        try:
            assert tray.broker is not None
            assert tray.broker.port > 0
            assert tray._node is not None
            assert tray._node.wait_registered(timeout=5.0)
            counts = tray.broker.peer_counts()
            assert counts.get("tray", 0) >= 1
        finally:
            tray.on_quit()

    def test_tray_accepts_external_node(self, qtbot):
        from wafer.app.tray.main_tray import TrayApp

        icon = QtGui.QIcon()
        tray = TrayApp(icon)
        received = {}

        def handler(msg):
            received["msg"] = msg
            return True

        try:
            test_node = Node("viewer")
            test_node.subscribe("test.echo", handler)
            test_node.start(port=tray.broker.port)
            try:
                assert test_node.wait_registered(timeout=5.0)
                assert _poll_until(lambda: tray.broker.peer_counts().get("viewer", 0) >= 1)
                msg = Message.build("test.echo", {"data": "hello"}, dst="viewer")
                tray.broker.dispatch(msg)
                assert _poll_until(lambda: "msg" in received, timeout=5.0)
                assert received["msg"].payload["data"] == "hello"
            finally:
                test_node.stop()
        finally:
            tray.on_quit()

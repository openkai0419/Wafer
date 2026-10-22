import socket
import threading
import time
from types import SimpleNamespace

import pytest

from wafer.app.viewer.workspace_launch import OpenRequest, deliver_open_request
from wafer.core.ipc.broker import Broker
from wafer.core.ipc.node import Node
from wafer.core.ipc.transport import write_broker_port

SLOT_ID = "slot-handover"
TRAY_STARTUP_SECONDS = 1.0


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _start_viewer(port: int, received: list) -> Node:
    viewer = Node("viewer")
    viewer.session_id = SLOT_ID

    def on_open_path(msg):
        if msg.payload.get("slot_id") != SLOT_ID:
            return True
        received.append(msg.payload["path"])
        viewer.enqueue(msg.reply({"ok": True}))
        return True

    viewer.subscribe("slot.open_path", on_open_path)
    viewer.start(port)
    assert viewer.wait_registered(timeout=5.0)
    return viewer


def _crash(broker: Broker) -> None:
    broker.stop()
    write_broker_port(broker.port)


@pytest.mark.parametrize("same_port", [True, False], ids=["same-port", "new-port"])
def test_open_path_reaches_the_open_workspace_after_the_tray_restarts(same_port):
    received: list[str] = []
    first = Broker(port=_free_port())
    first.start()
    viewer = _start_viewer(first.port, received)
    _crash(first)

    outcome = {}
    launcher = threading.Thread(
        target=lambda: outcome.setdefault("ok", deliver_open_request(SimpleNamespace(slot_id=SLOT_ID), OpenRequest("C:/a.png", ""))),
        daemon=True,
    )
    started = time.monotonic()
    launcher.start()
    time.sleep(TRAY_STARTUP_SECONDS)
    second = Broker(port=first.port if same_port else _free_port())
    second.start()
    try:
        launcher.join(timeout=30)
        assert outcome.get("ok") is True, f"launcher gave up after {time.monotonic() - started:.1f}s"
        assert received == ["C:/a.png"]
    finally:
        viewer.stop()
        second.stop()

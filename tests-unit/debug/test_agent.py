import os
import sys
import threading
import time

import pytest
from PySide6 import QtCore, QtWidgets

import wafer.core.common.paths as paths
from debug.agent import AGENT_ROLE, CALL_TOPIC, DebugAgent, attach
from wafer.core.common.profile import current_profile
from wafer.core.ipc.broker import Broker
from wafer.core.ipc.message import Message
from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger

DEBUG_PROFILE = "debug-t"


@pytest.fixture
def agent(qtbot):
    agent = DebugAgent("viewer", Node(AGENT_ROLE, profile=None))
    yield agent
    agent.deleteLater()


def test_run_command_unknown_id(agent):
    reply = agent.call("run_command", {"id": "no.such", "args": {}})
    assert reply["ok"] is False
    assert "no.such" in reply["error"]


def test_ping_names_the_process(agent):
    reply = agent.call("ping", {})
    assert reply == {"ok": True, "result": {"pid": os.getpid(), "role": "viewer", "profile": current_profile(), "focused_at": reply["result"]["focused_at"]}, "error": ""}


def test_ping_and_idle_report_when_a_window_of_the_process_last_had_focus(agent, qtbot):
    window = QtWidgets.QWidget()
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    try:
        before = time.monotonic()
        QtWidgets.QApplication.instance().focusWindowChanged.emit(window.windowHandle())
        after = time.monotonic()
        focused_at = agent.call("ping", {})["result"]["focused_at"]
        assert before <= focused_at <= after
        QtWidgets.QApplication.instance().focusWindowChanged.emit(None)
        assert agent.call("ping", {})["result"]["focused_at"] == focused_at
        assert agent.call("idle", {})["result"]["focused_at"] == focused_at
    finally:
        window.close()


def test_unknown_op_is_an_error(agent):
    reply = agent.call("no_such_op", {})
    assert reply["ok"] is False and "no_such_op" in reply["error"]


def test_failing_op_reports_and_logs_the_exception(agent, monkeypatch):
    warnings = []
    monkeypatch.setattr(AppLogger, "warning", lambda text, exc=None: warnings.append((text, exc)))
    reply = agent.call("screenshot", {"target": "no-such-widget"})
    assert reply == {"ok": False, "result": None, "error": reply["error"]}
    assert reply["error"].startswith("LookupError: ") and "no-such-widget" in reply["error"]
    assert len(warnings) == 1 and isinstance(warnings[0][1], LookupError)


def test_bad_arguments_are_an_error(agent, monkeypatch):
    monkeypatch.setattr(AppLogger, "warning", lambda text, exc=None: None)
    reply = agent.call("modal_click", {"label": "OK"})
    assert reply["ok"] is False and reply["error"].startswith("TypeError: ")


def test_screenshot_result_is_png_bytes(agent, qtbot):
    window = QtWidgets.QWidget()
    window.resize(200, 100)
    qtbot.addWidget(window)
    window.show()
    qtbot.waitExposed(window)
    try:
        reply = agent.call("screenshot", {"target": None, "max_side": 50})
    finally:
        window.close()
    assert reply["ok"] is True and reply["result"][:8] == b"\x89PNG\r\n\x1a\n"


def test_failed_hand_over_still_replies(agent, monkeypatch):
    def refuse(*args):
        raise ValueError("no GUI thread")

    warnings = []
    replies = []
    monkeypatch.setattr(QtCore.QMetaObject, "invokeMethod", refuse)
    monkeypatch.setattr(AppLogger, "warning", lambda text, exc=None: warnings.append(exc))
    monkeypatch.setattr(agent.node, "enqueue", replies.append)
    request = Message.build(CALL_TOPIC, {"op": "ping", "args": {}}, src="debug-1", dst=agent.node.node_id, rid="r1")
    assert agent._on_call(request) is True
    assert len(replies) == 1 and replies[0].request_id == "r1"
    assert replies[0].payload == {"ok": False, "result": None, "error": "ValueError: no GUI thread"}
    assert isinstance(warnings[0], ValueError)


def test_idle_reports_modal_and_main_thread_latency(agent):
    reply = agent.call("idle", {})
    assert reply["ok"] is True
    assert reply["result"]["modal"] is False
    assert reply["result"]["main_thread_ms"] >= 0.0


class _FakePlatformDirs:
    base = ""

    def __init__(self, appname=None):
        self.user_data_dir = _FakePlatformDirs.base
        self.user_config_dir = _FakePlatformDirs.base


@pytest.fixture
def agent_with_broker(qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(_FakePlatformDirs, "base", str(tmp_path / "appdata"))
    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    monkeypatch.setattr("wafer.core.ipc.transport._PORT_FILE", tmp_path / "ipc" / "broker.json")
    monkeypatch.setattr(sys, "argv", [sys.argv[0], "--profile", DEBUG_PROFILE])
    current_profile.cache_clear()
    broker = Broker(profile=DEBUG_PROFILE)
    broker.start()
    agent = attach("viewer")
    client = Node("debug")
    client.start()
    try:
        yield agent, client
    finally:
        client.stop()
        agent.stop()
        agent.setParent(None)
        agent.deleteLater()
        broker.stop()
        current_profile.cache_clear()


def _request_in_background(client: Node, payload: dict) -> dict:
    box = {}

    def run():
        box["reply"] = client.request(CALL_TOPIC, payload, dst=f"{AGENT_ROLE}-{os.getpid()}", timeout=5.0)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return box


def test_agent_replies_over_ipc(qtbot, agent_with_broker):
    agent, client = agent_with_broker
    assert agent.node.node_id == f"debug_agent-{os.getpid()}"
    assert agent.node.wait_registered(5.0) and client.wait_registered(5.0)
    box = _request_in_background(client, {"op": "ping", "args": {}})
    qtbot.waitUntil(lambda: "reply" in box, timeout=6000)
    result = box["reply"].payload["result"]
    assert box["reply"].payload == {"ok": True, "result": {"pid": os.getpid(), "role": "viewer", "profile": DEBUG_PROFILE, "focused_at": result["focused_at"]}, "error": ""}


def test_agent_measures_main_thread_latency_over_ipc(qtbot, agent_with_broker):
    agent, client = agent_with_broker
    assert agent.node.wait_registered(5.0) and client.wait_registered(5.0)
    box = _request_in_background(client, {"op": "idle", "args": {}})
    qtbot.waitUntil(lambda: "reply" in box, timeout=6000)
    result = box["reply"].payload["result"]
    assert result["modal"] is False and result["main_thread_ms"] >= 0.0


def test_agent_answers_a_malformed_payload(qtbot, agent_with_broker, monkeypatch):
    monkeypatch.setattr(AppLogger, "warning", lambda text, exc=None: None)
    agent, client = agent_with_broker
    assert agent.node.wait_registered(5.0) and client.wait_registered(5.0)
    box = _request_in_background(client, "ping")
    qtbot.waitUntil(lambda: "reply" in box, timeout=6000)
    assert box["reply"].payload["ok"] is False

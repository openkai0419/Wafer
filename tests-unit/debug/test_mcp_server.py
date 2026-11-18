import asyncio
import json
import os
import sqlite3
import time
from pathlib import Path

import pytest

import wafer.core.common.paths as paths
from debug import mcp_server, profile_setup
from debug.mcp_server import NO_RUNNING_MESSAGE, DebugError, DebugSession, build_server
from wafer.core.common.paths import profile_data_root
from wafer.core.ipc.message import Message
from wafer.core.platform.process import AppProcess

PROFILE = "debug-task"


class _FakePlatformDirs:
    base = ""

    def __init__(self, appname=None):
        self.user_data_dir = _FakePlatformDirs.base
        self.user_config_dir = _FakePlatformDirs.base


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    base = tmp_path / "appdata"
    base.mkdir()
    monkeypatch.setattr(_FakePlatformDirs, "base", str(base))
    monkeypatch.setattr(paths, "PlatformDirs", _FakePlatformDirs)
    return base


class FakeProcess:
    def __init__(self, pid: int, *args: str, profile: str = PROFILE):
        self.pid = pid
        self._cmdline = ["python.exe", "main.py", *args, "--profile", profile]

    def cmdline(self) -> list[str]:
        return list(self._cmdline)


class FakeNode:
    instances: list["FakeNode"] = []
    handler = None

    def __init__(self, role, profile=None):
        self.role = role
        self.profile = profile
        self.started = False
        self.stopped = False
        self.requests: list[tuple[str, dict, str, float]] = []
        FakeNode.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def wait_registered(self, timeout=5.0):
        return True

    def request(self, topic, payload=None, *, dst="ALL", db="", timeout=5.0):
        self.requests.append((topic, payload, dst, timeout))
        reply = FakeNode.handler(payload["op"], payload["args"], dst)
        if reply is None:
            return None
        return Message.build(topic, reply, src=dst, dst="debug-1")


def ok(result):
    return {"ok": True, "result": result, "error": ""}


@pytest.fixture
def processes(monkeypatch):
    procs: list[FakeProcess] = []
    monkeypatch.setattr(AppProcess, "list_profile_processes", classmethod(lambda cls, profile: [p for p in procs if p.cmdline()[-1] == profile]))
    return procs


@pytest.fixture
def node(monkeypatch):
    FakeNode.instances = []
    FakeNode.handler = staticmethod(lambda op, args, dst: ok({"op": op, "args": args, "dst": dst}))
    monkeypatch.setattr(mcp_server, "Node", FakeNode)
    monkeypatch.setattr(mcp_server, "POLL_SECONDS", 0.01)
    return FakeNode


def call_tool(server, name, args=None):
    result = asyncio.run(server.call_tool(name, args or {}))
    assert not result.is_error, result.content
    return result.content


def tool_text(server, name, args=None) -> str:
    blocks = call_tool(server, name, args)
    assert len(blocks) == 1
    return blocks[0].text


def running_session(processes) -> DebugSession:
    processes.extend([FakeProcess(10, "--tray"), FakeProcess(20), FakeProcess(30, "--indexer", "sample"), FakeProcess(40), FakeProcess(50, "--webui")])
    session = DebugSession()
    session.profile = PROFILE
    return session


def test_tools_without_running_profile_return_launch_hint(app_data, processes, node):
    session = DebugSession()
    server = build_server(session)
    calls = {
        "stop": {},
        "status": {},
        "screenshot": {},
        "get_state": {},
        "widget_tree": {},
        "get_property": {"name": "grid", "prop": "count"},
        "tail_log": {},
        "list_commands": {},
        "run_command": {"id": "file.open"},
        "modal_state": {},
        "modal_input": {"field": "name", "value": "x"},
        "modal_click": {"text": "OK"},
        "click": {"widget": "ok"},
        "type_text": {"widget": "search", "text": "cat"},
        "key": {"sequence": "Ctrl+A"},
        "wait_idle": {"timeout": 0.1},
    }
    for name, args in calls.items():
        assert tool_text(server, name, args) == NO_RUNNING_MESSAGE, name

    session.profile = PROFILE
    for name, args in calls.items():
        if name == "tail_log":
            continue
        assert tool_text(server, name, args) == NO_RUNNING_MESSAGE, name
    assert node.instances == []


def test_launch_rejects_non_checkout(tmp_path, app_data, processes, node, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("must not be called for a non-checkout")

    for name in ("stop_profile", "ensure_profile", "launch_process"):
        monkeypatch.setattr(profile_setup, name, forbidden)
    session = DebugSession()
    server = build_server(session)

    text = tool_text(server, "launch", {"checkout": str(tmp_path / "elsewhere")})

    assert "Not a Wafer checkout" in text
    assert session.profile is None


def test_target_defaults_to_first_viewer(app_data, processes, node):
    session = running_session(processes)

    assert session.call("get_state", {}, None, 5.0)["dst"] == "debug_agent-20"
    assert session.call("get_state", {}, "tray:10", 5.0)["dst"] == "debug_agent-10"
    assert session.call("get_state", {}, "viewer:40", 5.0)["dst"] == "debug_agent-40"
    assert session.call("get_state", {}, "webui:50", 5.0)["dst"] == "debug_agent-50"
    for bad in ("viewer:30", "viewer:99", "tray:20", "indexer:30", "40", "viewer:x"):
        with pytest.raises(DebugError):
            session.call("get_state", {}, bad, 5.0)
    assert [n.profile for n in node.instances] == [PROFILE]
    assert node.instances[0].requests[0][:2] == ("debug.call", {"op": "get_state", "args": {}})


def test_call_timeout_message(app_data, processes, node):
    session = running_session(processes)
    node.handler = staticmethod(lambda op, args, dst: None)

    with pytest.raises(DebugError) as excinfo:
        session.call("get_state", {}, None, 2.5)
    assert str(excinfo.value) == "The debug Wafer did not answer within 2.5s."

    text = tool_text(build_server(session), "get_state")
    assert text == f"The debug Wafer did not answer within {mcp_server.CALL_TIMEOUT}s."


def test_agent_error_is_returned_as_text(app_data, processes, node):
    session = running_session(processes)
    node.handler = staticmethod(lambda op, args, dst: {"ok": False, "result": None, "error": "LookupError: click target 'ok' is blocked by modal 'Rename'"})

    text = tool_text(build_server(session), "click", {"widget": "ok"})

    assert "is blocked by modal 'Rename'" in text
    assert node.instances[0].requests[0][1] == {"op": "click", "args": {"target": "ok"}}


def test_tools_map_arguments_to_agent_ops(app_data, processes, node):
    session = running_session(processes)
    server = build_server(session)
    calls = [
        ("get_property", {"name": "grid", "prop": "count", "target": "viewer:40"}, "debug_agent-40", {"op": "get_property", "args": {"name": "grid", "prop": "count"}}),
        ("widget_tree", {"root": "panel", "depth": 2}, "debug_agent-20", {"op": "widget_tree", "args": {"root": "panel", "depth": 2}}),
        ("list_commands", {"filter": "file"}, "debug_agent-20", {"op": "list_commands", "args": {"filter": "file"}}),
        ("modal_input", {"field": "name", "value": "x"}, "debug_agent-20", {"op": "modal_input", "args": {"field": "name", "value": "x"}}),
        ("modal_click", {"text": "OK"}, "debug_agent-20", {"op": "modal_click", "args": {"text": "OK"}}),
        ("type_text", {"widget": "search", "text": "cat"}, "debug_agent-20", {"op": "type_text", "args": {"target": "search", "text": "cat"}}),
        ("key", {"sequence": "Ctrl+A", "target": "tray:10"}, "debug_agent-10", {"op": "key", "args": {"target": None, "sequence": "Ctrl+A"}}),
    ]
    for name, args, dst, payload in calls:
        before = len(node.instances[0].requests) if node.instances else 0
        result = json.loads(tool_text(server, name, args))
        assert result["dst"] == dst, name
        assert node.instances[0].requests[before][1] == payload, name


def test_screenshot_returns_png_image(app_data, processes, node):
    session = running_session(processes)
    png = b"\x89PNG\r\n\x1a\nfake"
    node.handler = staticmethod(lambda op, args, dst: ok(png))

    blocks = call_tool(build_server(session), "screenshot", {"widget": "grid", "max_side": 800})

    assert blocks[0].type == "image"
    assert blocks[0].mime_type == "image/png"
    assert node.instances[0].requests[0][1] == {"op": "screenshot", "args": {"target": "grid", "max_side": 800}}


def test_run_command_reports_modal_title(app_data, processes, node, monkeypatch):
    monkeypatch.setattr(mcp_server, "MODAL_WAIT_SECONDS", 0.05)
    session = running_session(processes)
    modal_answers = iter([None, None, {"title": "Rename", "fields": []}])

    def handler(op, args, dst):
        if op == "run_command":
            return ok({"started": True})
        return ok(next(modal_answers))

    node.handler = staticmethod(handler)
    assert session.run_command("file.rename", {"name": "a"}, None) == {"started": True, "modal": "Rename"}
    assert node.instances[0].requests[0][1] == {"op": "run_command", "args": {"id": "file.rename", "args": {"name": "a"}}}

    node.handler = staticmethod(lambda op, args, dst: ok({"started": True}) if op == "run_command" else ok(None))
    started = time.monotonic()
    assert session.run_command("view.refresh", None, None) == {"started": True, "modal": None}
    assert time.monotonic() - started >= mcp_server.MODAL_WAIT_SECONDS


def make_sample_db(profile: str, statuses: list[str], sources: int) -> Path:
    db_path = profile_data_root(profile) / "data" / "sample.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sources (id INTEGER PRIMARY KEY)")
    conn.execute("CREATE TABLE collection_status (source INTEGER, collector TEXT, status TEXT)")
    conn.executemany("INSERT INTO sources (id) VALUES (?)", [(i,) for i in range(sources)])
    conn.executemany("INSERT INTO collection_status VALUES (?, 'meta', ?)", list(enumerate(statuses)))
    conn.commit()
    conn.close()
    return db_path


def test_status_reports_processes_webui_and_index(app_data, processes, node):
    session = running_session(processes)
    temp = profile_data_root(PROFILE) / ".temp"
    temp.mkdir(parents=True)
    (temp / "webui.json").write_text(json.dumps({"url": "http://127.0.0.1:61234/"}), encoding="utf-8")
    make_sample_db(PROFILE, ["done", "pending", "dispatched", "done"], 4)

    status = session.status()

    assert status["profile"] == PROFILE
    assert status["processes"] == [
        {"pid": 10, "role": "tray", "target": "tray:10"},
        {"pid": 20, "role": "viewer", "target": "viewer:20"},
        {"pid": 30, "role": "worker", "target": None},
        {"pid": 40, "role": "viewer", "target": "viewer:40"},
        {"pid": 50, "role": "webui", "target": "webui:50"},
    ]
    assert status["webui_url"] == "http://127.0.0.1:61234/"
    assert status["index"] == {"sources": 4, "pending": 2}


def test_status_without_webui_or_db(app_data, processes, node):
    processes.append(FakeProcess(20))
    session = DebugSession()
    session.profile = PROFILE

    status = session.status()

    assert status["webui_url"] == ""
    assert status["index"] == {"sources": 0, "pending": 0}


def test_wait_idle_returns_when_main_thread_is_fast_and_index_settled(app_data, processes, node):
    session = running_session(processes)
    make_sample_db(PROFILE, ["done", "done"], 2)
    timings = iter([500.0, 20.0, 900.0, 10.0, 15.0])
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": True, "main_thread_ms": next(timings)}))

    result = session.wait_idle(5.0, None)

    assert result["idle"] is True
    assert result["modal"] is True
    assert [r[1]["op"] for r in node.instances[0].requests] == ["idle"] * 5


def test_wait_idle_timeout_says_what_is_busy(app_data, processes, node):
    session = running_session(processes)
    make_sample_db(PROFILE, ["pending", "done"], 2)
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 5.0}))

    with pytest.raises(DebugError) as excinfo:
        session.wait_idle(0.2, None)
    assert "1 collection task pending" in str(excinfo.value)

    (profile_data_root(PROFILE) / "data" / "sample.db").unlink()
    make_sample_db(PROFILE, ["done"], 1)
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 450.0}))
    with pytest.raises(DebugError) as excinfo:
        session.wait_idle(0.2, None)
    assert "main thread answered in 450 ms" in str(excinfo.value)


def test_tail_log_reads_newest_log_with_level_filter(app_data, processes, node):
    session = DebugSession()
    session.profile = PROFILE
    log_dir = profile_data_root(PROFILE) / ".log"
    log_dir.mkdir(parents=True)
    old = log_dir / "tray_10.log"
    old.write_text("2026-11-19 10:00:00,000 ERROR old\n", encoding="utf-8")
    new = log_dir / "viewer_20.log"
    new.write_text(
        "2026-11-19 10:00:01,000 INFO opened\n"
        "2026-11-19 10:00:02,000 WARNING slow\n"
        "2026-11-19 10:00:03,000 ERROR broke\n"
        "Traceback (most recent call last):\n"
        "  ValueError: x\n"
        "2026-11-19 10:00:04,000 DEBUG detail\n",
        encoding="utf-8",
    )
    os.utime(old, (1, 1))

    assert session.tail_log(2, "") == "  ValueError: x\n2026-11-19 10:00:04,000 DEBUG detail"
    assert session.tail_log(100, "warning").splitlines() == [
        "2026-11-19 10:00:02,000 WARNING slow",
        "2026-11-19 10:00:03,000 ERROR broke",
        "Traceback (most recent call last):",
        "  ValueError: x",
    ]
    with pytest.raises(DebugError):
        session.tail_log(10, "loud")


def test_launch_stops_running_profile_prepares_and_waits_for_viewer(tmp_path, app_data, processes, node, monkeypatch):
    checkout = tmp_path / "Repo" / ".claude" / "worktrees" / "task"
    calls = []
    monkeypatch.setattr(profile_setup, "profile_name_for", lambda path: calls.append(("name", Path(path))) or PROFILE)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile: calls.append(("stop", profile)))

    def ensure(path, *, fresh, on_progress):
        on_progress("Creating debug-task from sample template abc")
        calls.append(("ensure", Path(path), fresh))
        return PROFILE

    def launch(path, profile):
        calls.append(("launch", Path(path), profile))
        processes.extend([FakeProcess(10, "--tray"), FakeProcess(20)])
        return 20

    monkeypatch.setattr(profile_setup, "ensure_profile", ensure)
    monkeypatch.setattr(profile_setup, "launch_process", launch)
    node.handler = staticmethod(lambda op, args, dst: ok({"pid": 20, "role": "viewer", "profile": PROFILE}))
    session = DebugSession()
    old_node = FakeNode("debug", profile="debug-other")
    session.profile = "debug-other"
    session._node = old_node
    progress = []

    result = session.launch(str(checkout), fresh=True, on_progress=progress.append)

    assert calls == [("name", checkout), ("stop", PROFILE), ("ensure", checkout, True), ("launch", checkout, PROFILE)]
    assert old_node.stopped
    assert session.profile == PROFILE
    assert result["profile"] == PROFILE
    assert result["pid"] == 20
    assert result["progress"] == ["Creating debug-task from sample template abc"]
    assert [p["target"] for p in result["processes"]] == ["tray:10", "viewer:20"]
    assert progress == ["Creating debug-task from sample template abc"]
    assert node.instances[-1].profile == PROFILE
    assert node.instances[-1].requests[-1][1:3] == ({"op": "ping", "args": {}}, "debug_agent-20")


def test_launch_reports_exit_before_viewer_answers(tmp_path, app_data, processes, node, monkeypatch):
    monkeypatch.setattr(profile_setup, "profile_name_for", lambda path: PROFILE)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile: None)
    monkeypatch.setattr(profile_setup, "ensure_profile", lambda path, *, fresh, on_progress: PROFILE)
    monkeypatch.setattr(profile_setup, "launch_process", lambda path, profile: 20)
    session = DebugSession()

    text = tool_text(build_server(session), "launch", {"checkout": str(tmp_path)})

    assert "exited before its Viewer answered" in text


def test_stop_stops_node_and_profile(app_data, processes, node, monkeypatch):
    session = running_session(processes)
    session.call("get_state", {}, None, 5.0)
    stopped = []
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile: stopped.append((profile, node.instances[0].stopped)))

    assert session.stop() == {"stopped": PROFILE}
    assert stopped == [(PROFILE, True)]
    session.close()


def test_rebuild_template_uses_launched_checkout(tmp_path, app_data, processes, node, monkeypatch):
    built = []

    def rebuild(path, *, on_progress):
        on_progress("Sample template abc built")
        built.append(Path(path))
        return tmp_path / "template"

    monkeypatch.setattr(profile_setup, "rebuild_template", rebuild)
    session = DebugSession()
    server = build_server(session)

    assert "launch(checkout=...)" in tool_text(server, "rebuild_template")
    result = json.loads(tool_text(server, "rebuild_template", {"checkout": str(tmp_path / "a")}))
    assert result == {"template": str(tmp_path / "template"), "progress": ["Sample template abc built"]}
    session.checkout = tmp_path / "b"
    tool_text(server, "rebuild_template")
    assert built == [tmp_path / "a", tmp_path / "b"]

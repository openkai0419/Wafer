import asyncio
import json
import os
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import wafer.core.common.paths as paths
from debug import mcp_server, profile_setup
from debug.mcp_server import NO_RUNNING_MESSAGE, DebugError, DebugSession, build_server
from wafer.core.common.paths import normalize_path, profile_data_root, resolve_data_path
from wafer.core.common.profile import TOOLS_PROFILE, current_profile
from wafer.core.logs import AppLogger
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
    ping_handler = None

    def __init__(self, role, profile=None):
        self.role = role
        self.profile = profile
        self.started = False
        self.stopped = False
        self.requests: list[tuple[str, dict, str, float]] = []
        self.pings: list[tuple[str, dict, str, float]] = []
        FakeNode.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def wait_registered(self, timeout=5.0):
        return True

    def request(self, topic, payload=None, *, dst="ALL", db="", timeout=5.0):
        is_ping = payload["op"] == "ping"
        (self.pings if is_ping else self.requests).append((topic, payload, dst, timeout))
        reply = (FakeNode.ping_handler if is_ping else FakeNode.handler)(payload["op"], payload["args"], dst)
        if reply is None:
            return None
        return Message.build(topic, reply, src=dst, dst="debug-1")


class FakeClock:
    def __init__(self):
        self.now = 0.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(mcp_server, "time", fake)
    return fake


def make_checkout(path: Path) -> Path:
    (path / "wafer").mkdir(parents=True)
    (path / "main.py").write_text("", encoding="utf-8")
    return path


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
    FakeNode.ping_handler = staticmethod(lambda op, args, dst: ok({"pid": int(dst.rsplit("-", 1)[1]), "role": "viewer", "profile": PROFILE, "focused_at": None}))
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
        "get_property": {"widget": "grid", "prop": "count"},
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


def focus_handler(focused: dict[int, float | None], silent: tuple[int, ...] = ()):
    def handler(op, args, dst):
        pid = int(dst.rsplit("-", 1)[1])
        return None if pid in silent else ok({"pid": pid, "role": "viewer", "profile": PROFILE, "focused_at": focused[pid]})

    return staticmethod(handler)


@pytest.mark.parametrize(
    ("focused", "silent", "expected"),
    [
        ({20: 5.0, 40: 9.0}, (), 40),
        ({20: 9.0, 40: 5.0}, (), 20),
        ({20: None, 40: 1.0}, (), 40),
        ({20: 7.0, 40: 7.0}, (), 20),
        ({20: None, 40: None}, (), 20),
        ({20: 5.0, 40: 9.0}, (40,), 20),
    ],
    ids=["latest-wins", "latest-wins-lower-pid", "focused-beats-never", "tie-lowest-pid", "none-lowest-pid", "silent-viewer-counts-as-never"],
)
def test_default_target_is_the_viewer_that_last_had_focus(app_data, processes, node, focused, silent, expected):
    session = running_session(processes)
    node.ping_handler = focus_handler(focused, silent)

    assert session.call("get_state", {}, None, 5.0)["dst"] == f"debug_agent-{expected}"
    assert sorted(p[2] for p in node.instances[0].pings) == ["debug_agent-20", "debug_agent-40"]


def test_a_single_viewer_is_the_default_target_without_asking_for_focus(app_data, processes, node):
    processes.extend([FakeProcess(10, "--tray"), FakeProcess(20)])
    session = DebugSession()
    session.profile = PROFILE

    assert session.call("get_state", {}, None, 5.0)["dst"] == "debug_agent-20"
    assert node.instances[0].pings == []


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
        ("get_property", {"widget": "grid", "prop": "count", "target": "viewer:40"}, "debug_agent-40", {"op": "get_property", "args": {"name": "grid", "prop": "count"}}),
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


def test_run_command_reports_modal_title(app_data, processes, node, clock):
    session = running_session(processes)
    modal_answers = iter([None, None, {"title": "Rename", "fields": []}])

    def handler(op, args, dst):
        if op == "run_command":
            return ok({"started": True})
        return ok(next(modal_answers))

    node.handler = staticmethod(handler)
    assert session.run_command("file.rename", {"name": "a"}, None) == {"started": True, "modal": "Rename"}
    assert node.instances[0].requests[0][1] == {"op": "run_command", "args": {"id": "file.rename", "args": {"name": "a"}}}

    assert [r[1]["op"] for r in node.instances[0].requests] == ["run_command", "modal_state", "modal_state", "modal_state"]

    node.handler = staticmethod(lambda op, args, dst: ok({"started": True}) if op == "run_command" else ok(None))
    started = clock.now
    assert session.run_command("view.refresh", None, None) == {"started": True, "modal": None}
    assert clock.now - started >= mcp_server.MODAL_WAIT_SECONDS


def make_sample_db(profile: str, statuses: list[str], sources: int) -> Path:
    db_path = profile_data_root(profile) / "data" / "sample.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE sources (source TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE collection_status (source TEXT, collector TEXT, status TEXT, PRIMARY KEY(source, collector))")
    conn.executemany("INSERT INTO sources (source) VALUES (?)", [(f"s{i}",) for i in range(sources)])
    conn.executemany("INSERT INTO collection_status VALUES (?, 'meta', ?)", [(f"s{i}", status) for i, status in enumerate(statuses)])
    conn.commit()
    conn.close()
    return db_path


@pytest.fixture
def sample_scope(tmp_path, monkeypatch, app_data):
    def make(files: int) -> None:
        sample = tmp_path / "sample"
        sample.mkdir()
        for i in range(files):
            (sample / f"{i}.png").write_bytes(b"x")
        monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(sample))
        profile_setup.sample_db_setup(profile_data_root(PROFILE))

    return make


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


def test_wait_idle_returns_when_main_thread_is_fast_and_index_settled(app_data, processes, node, sample_scope):
    sample_scope(2)
    session = running_session(processes)
    make_sample_db(PROFILE, ["done", "done"], 2)
    timings = iter([500.0, 20.0, 900.0, 10.0, 15.0])
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": True, "main_thread_ms": next(timings)}))

    result = session.wait_idle(5.0, None)

    assert result["idle"] is True
    assert result["modal"] is True
    assert [r[1]["op"] for r in node.instances[0].requests] == ["idle"] * 5


def test_wait_idle_timeout_says_what_is_busy(app_data, processes, node, sample_scope):
    sample_scope(2)
    session = running_session(processes)
    make_sample_db(PROFILE, ["pending", "done"], 2)
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 5.0}))

    with pytest.raises(DebugError) as excinfo:
        session.wait_idle(0.2, None)
    assert "1 collection task pending" in str(excinfo.value)

    (profile_data_root(PROFILE) / "data" / "sample.db").unlink()
    make_sample_db(PROFILE, ["done", "done"], 2)
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 450.0}))
    with pytest.raises(DebugError) as excinfo:
        session.wait_idle(0.2, None)
    assert "main thread answered in 450 ms" in str(excinfo.value)


@pytest.mark.parametrize(
    ("statuses", "sources", "reason"),
    [
        ([], 0, "the sample DB has no collected sources yet"),
        (["done"], 1, "1 of 3 sources indexed"),
        (["done", "done"], 3, "1 source without collection rows"),
    ],
)
def test_wait_idle_waits_for_the_whole_sample_like_the_template(app_data, processes, node, clock, sample_scope, statuses, sources, reason):
    sample_scope(3)
    session = running_session(processes)
    make_sample_db(PROFILE, statuses, sources)
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 5.0}))

    with pytest.raises(DebugError) as excinfo:
        session.wait_idle(2.0, None)
    assert reason in str(excinfo.value)


def test_wait_idle_reports_a_missing_sample_instead_of_idle(tmp_path, app_data, processes, node, clock, sample_scope, monkeypatch):
    sample_scope(1)
    session = running_session(processes)
    make_sample_db(PROFILE, [], 0)
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(tmp_path / "gone"))
    node.handler = staticmethod(lambda op, args, dst: ok({"modal": False, "main_thread_ms": 5.0}))

    text = tool_text(build_server(session), "wait_idle", {"timeout": 2})

    assert "idle" not in text.split(":")[0]
    assert str(tmp_path / "gone") in text
    assert "worktree.py repair" in text


def test_wait_idle_needs_a_running_profile_before_reading_any_index(app_data, processes, node, monkeypatch):
    session = DebugSession()
    monkeypatch.setattr(profile_setup, "sample_scope_count", lambda profile: pytest.fail("read the index without a running profile"))

    with pytest.raises(DebugError, match="No debug Wafer is running"):
        session.wait_idle(1.0, None)


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
    assert node.instances[-1].pings[-1][1:3] == ({"op": "ping", "args": {}}, "debug_agent-20")


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

    first = make_checkout(tmp_path / "Repo")
    second = make_checkout(first / ".claude" / "worktrees" / "b")
    monkeypatch.setattr(profile_setup, "get_app_root_dir", lambda: first)
    assert "launch(checkout=...)" in tool_text(server, "rebuild_template")
    result = json.loads(tool_text(server, "rebuild_template", {"checkout": str(first)}))
    assert result == {"template": str(tmp_path / "template"), "progress": ["Sample template abc built"]}
    session.checkout = second
    tool_text(server, "rebuild_template")
    assert built == [first, second]

    assert "Not a Wafer checkout" in tool_text(server, "rebuild_template", {"checkout": str(tmp_path / "elsewhere")})
    assert built == [first, second]


def test_wait_idle_keeps_polling_when_the_agent_does_not_answer(app_data, processes, node, clock, sample_scope):
    sample_scope(1)
    session = running_session(processes)
    make_sample_db(PROFILE, ["done"], 1)
    answers = iter([None, None, None, ok({"modal": False, "main_thread_ms": 10.0}), ok({"modal": False, "main_thread_ms": 12.0})])
    node.handler = staticmethod(lambda op, args, dst: next(answers))

    result = session.wait_idle(30.0, None)

    assert result["idle"] is True
    assert len(node.instances[0].requests) == 5


def test_wait_idle_reports_a_main_thread_that_never_answers(app_data, processes, node, clock, sample_scope):
    sample_scope(1)
    session = running_session(processes)
    make_sample_db(PROFILE, ["done"], 1)
    node.handler = staticmethod(lambda op, args, dst: None)

    text = tool_text(build_server(session), "wait_idle", {"timeout": 2})

    assert text.startswith("Still busy after 2s: main thread did not answer")
    assert len(node.instances[0].requests) > 1


def test_tools_answer_while_launch_prepares_the_profile(tmp_path, app_data, processes, node, monkeypatch):
    processes.append(FakeProcess(70, profile="debug-other"))
    entered, release = threading.Event(), threading.Event()

    def ensure(path, *, fresh, on_progress):
        entered.set()
        assert release.wait(10)
        return PROFILE

    def launch(path, profile):
        processes.append(FakeProcess(20))
        return 20

    monkeypatch.setattr(profile_setup, "profile_name_for", lambda path: PROFILE)
    monkeypatch.setattr(profile_setup, "stop_profile", lambda profile: None)
    monkeypatch.setattr(profile_setup, "ensure_profile", ensure)
    monkeypatch.setattr(profile_setup, "launch_process", launch)
    session = DebugSession()
    session.profile = "debug-other"
    server = build_server(session)
    launched = threading.Thread(target=lambda: session.launch(str(tmp_path)))
    launched.start()
    try:
        assert entered.wait(10)
        answers = []
        probe = threading.Thread(target=lambda: answers.append(tool_text(server, "get_state")))
        probe.start()
        probe.join(5)
        assert answers == [NO_RUNNING_MESSAGE]
    finally:
        release.set()
        launched.join(10)
    assert session.profile == PROFILE


class LaunchInTheMiddle:
    def __init__(self, tmp_path, processes, monkeypatch):
        self.entered, self.release = threading.Event(), threading.Event()
        self.thread: threading.Thread | None = None
        self.roots: list = []
        processes.extend([FakeProcess(70, profile="debug-other"), FakeProcess(71, "--webui", profile="debug-other")])

        def ensure(path, *, fresh, on_progress):
            self.entered.set()
            assert self.release.wait(10)
            return PROFILE

        def launch(path, profile):
            processes.append(FakeProcess(20))
            return 20

        real_root = mcp_server.profile_data_root
        monkeypatch.setattr(mcp_server, "profile_data_root", lambda profile: self.roots.append(profile) or real_root(profile))
        monkeypatch.setattr(profile_setup, "profile_name_for", lambda path: PROFILE)
        monkeypatch.setattr(profile_setup, "stop_profile", lambda profile: None)
        monkeypatch.setattr(profile_setup, "ensure_profile", ensure)
        monkeypatch.setattr(profile_setup, "launch_process", launch)
        self.session = DebugSession()
        self.session.profile = "debug-other"
        self.checkout = str(tmp_path)

    def start_launch(self) -> None:
        if self.thread is None:
            self.thread = threading.Thread(target=lambda: self.session.launch(self.checkout))
            self.thread.start()
            assert self.entered.wait(10)
            assert self.session.profile is None

    def finish(self) -> None:
        self.release.set()
        if self.thread is not None:
            self.thread.join(10)
            assert not self.thread.is_alive()


@pytest.fixture
def launch_in_the_middle(tmp_path, app_data, processes, node, monkeypatch):
    race = LaunchInTheMiddle(tmp_path, processes, monkeypatch)
    yield race
    race.finish()


def launch_while_listing_processes(race, monkeypatch):
    real_list = AppProcess.list_profile_processes

    def list_then_launch(profile):
        found = real_list(profile)
        race.start_launch()
        return found

    monkeypatch.setattr(AppProcess, "list_profile_processes", list_then_launch)


def test_status_during_a_launch_never_reads_the_normal_wafer(launch_in_the_middle, node, monkeypatch):
    launch_while_listing_processes(launch_in_the_middle, monkeypatch)

    status = launch_in_the_middle.session.status()

    assert launch_in_the_middle.thread is not None
    assert status["profile"] == "debug-other"
    assert None not in launch_in_the_middle.roots
    assert launch_in_the_middle.roots


def test_a_call_during_a_launch_never_builds_a_node_without_a_profile(launch_in_the_middle, node, monkeypatch):
    launch_while_listing_processes(launch_in_the_middle, monkeypatch)

    launch_in_the_middle.session.call("get_state", {}, None, 5.0)

    assert launch_in_the_middle.thread is not None
    launch_in_the_middle.finish()
    assert node.instances
    assert None not in [n.profile for n in node.instances]


def test_tail_log_during_a_launch_never_reads_the_normal_wafer(launch_in_the_middle, node):
    race = launch_in_the_middle
    log_dir = profile_data_root("debug-other") / ".log"
    log_dir.mkdir(parents=True)
    (log_dir / "viewer_70.log").write_text("2026-11-19 10:00:01,000 INFO other\n", encoding="utf-8")

    class LaunchWhileReadingTheLevel(str):
        def upper(self):
            race.start_launch()
            return str.upper(self)

    assert race.session.tail_log(5, LaunchWhileReadingTheLevel("")) == "2026-11-19 10:00:01,000 INFO other"
    assert race.thread is not None
    assert race.roots == ["debug-other"]


def test_helpers_refuse_to_work_without_a_profile(app_data, processes, node):
    session = DebugSession()
    for helper in (lambda: session._ensure_node(None), lambda: session._webui_url(None), lambda: session._index_counts(None), lambda: session._processes(None)):
        with pytest.raises(ValueError):
            helper()
    assert node.instances == []


def test_expected_input_errors_are_logged_as_info_and_unexpected_ones_as_warnings(tmp_path, app_data, processes, node, monkeypatch):
    logged = []
    monkeypatch.setattr(AppLogger, "info", staticmethod(lambda text: logged.append(("info", text, None))))
    monkeypatch.setattr(AppLogger, "warning", staticmethod(lambda text, *, exc=None: logged.append(("warning", text, exc))))
    server = build_server(running_session(processes))

    assert "Not a Wafer checkout" in tool_text(server, "launch", {"checkout": str(tmp_path / "elsewhere")})
    assert [entry[0] for entry in logged] == ["info"]

    def broken_stop(profile):
        raise RuntimeError("boom")

    logged.clear()
    monkeypatch.setattr(profile_setup, "stop_profile", broken_stop)
    assert tool_text(server, "stop") == "RuntimeError: boom"
    assert [(entry[0], type(entry[2])) for entry in logged] == [("warning", RuntimeError)]


def test_status_treats_an_unreadable_webui_state_as_no_url_yet(app_data, processes, node):
    session = running_session(processes)
    temp = profile_data_root(PROFILE) / ".temp"
    temp.mkdir(parents=True)
    (temp / "webui.json").write_text('{"url": "http://127.0.0.1:6', encoding="utf-8")

    assert session.status()["webui_url"] == ""


def test_server_argv_selects_the_tooling_profile(app_data, monkeypatch):
    monkeypatch.setattr(sys, "argv", [mcp_server.__file__, "--profile", TOOLS_PROFILE])
    current_profile.cache_clear()
    try:
        assert current_profile() == TOOLS_PROFILE
        assert resolve_data_path(".log").startswith(normalize_path(app_data / "Wafer-debug" / TOOLS_PROFILE))
    finally:
        current_profile.cache_clear()
    assert mcp_server.parse_args(["--profile", TOOLS_PROFILE]).profile == TOOLS_PROFILE
    for argv in ([], ["--profile", "debug-main"], ["--prof", TOOLS_PROFILE]):
        with pytest.raises(SystemExit):
            mcp_server.parse_args(argv)


def test_server_process_is_never_a_profile_process(monkeypatch):
    class Proc:
        pid = 5

    server_cmdline = [sys.executable, "-m", "debug.mcp_server", "--profile", TOOLS_PROFILE]
    wafer_cmdline = [sys.executable, "main.py", "--profile", TOOLS_PROFILE]
    monkeypatch.setattr(AppProcess, "_iter_cmdlines", staticmethod(lambda: iter([(Proc(), server_cmdline)])))
    assert AppProcess.list_profile_processes(TOOLS_PROFILE) == []
    monkeypatch.setattr(AppProcess, "_iter_cmdlines", staticmethod(lambda: iter([(Proc(), wafer_cmdline)])))
    assert len(AppProcess.list_profile_processes(TOOLS_PROFILE)) == 1


@pytest.mark.timeout(180)
def test_server_started_with_python_m_keeps_its_data_in_the_tooling_profile(tmp_path):
    appdata = tmp_path / "appdata"
    env = {**os.environ, "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(appdata), "WIN_PD_OVERRIDE_APPDATA": str(appdata)}
    root = Path(mcp_server.__file__).resolve().parent.parent
    done = subprocess.run(
        [sys.executable, "-m", "debug.mcp_server", "--profile", TOOLS_PROFILE],
        cwd=root,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=150,
    )

    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert done.stdout == b""
    log_dir = appdata / "Wafer-debug" / TOOLS_PROFILE / ".log"
    assert [p.name.startswith("debug_mcp_") for p in log_dir.glob("*.log")] == [True]
    assert not (appdata / "Wafer").exists()

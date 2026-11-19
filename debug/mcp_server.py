import argparse
import functools
import json
import re
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psutil
from mcp.server.mcpserver import Image, MCPServer

from debug import profile_setup
from wafer.core.common.paths import profile_data_root
from wafer.core.common.profile import PROFILE_ARG, TOOLS_PROFILE, current_profile
from wafer.core.db.db_utils import open_readonly
from wafer.core.ipc.node import Node
from wafer.core.logs import AppLogger
from wafer.core.platform.process import AppProcess

SERVER_NAME = "wafer-debug"
LOG_ROLE = "debug_mcp"
NODE_ROLE = "debug"
AGENT_ROLE = "debug_agent"
CALL_TOPIC = "debug.call"
NO_RUNNING_MESSAGE = "No debug Wafer is running. Call launch(checkout=...) first."
TIMEOUT_MESSAGE = "The debug Wafer did not answer within {timeout}s."
AGENT_ROLES = ("viewer", "tray", "webui")
WORKER_FLAGS = ("--indexer", "--collector", "--parser")
CALL_TIMEOUT = 10.0
PING_TIMEOUT = 2.0
LAUNCH_TIMEOUT = 120.0
MODAL_WAIT_SECONDS = 1.5
POLL_SECONDS = 0.1
IDLE_MAIN_THREAD_MS = 200.0
IDLE_FAST_ANSWERS = 2
DEFAULT_SCREENSHOT_SIDE = 1600
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
LOG_ENTRY = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3} (DEBUG|INFO|WARNING|ERROR|CRITICAL) ")


class DebugError(Exception):
    pass


class CallTimeout(DebugError):
    pass


def _role_of(cmdline: list[str]) -> str:
    if "--tray" in cmdline:
        return "tray"
    if "--webui" in cmdline:
        return "webui"
    if any(flag in cmdline for flag in WORKER_FLAGS):
        return "worker"
    return "viewer"


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}{'' if count == 1 else 's'}"


class DebugSession:
    def __init__(self):
        self.profile: str | None = None
        self.checkout: Path | None = None
        self._node: Node | None = None
        self._lock = threading.RLock()
        self._launch_lock = threading.Lock()

    def launch(self, checkout: str, fresh: bool = False, on_progress: Callable[[str], None] | None = None) -> dict:
        path = Path(checkout)
        profile = profile_setup.profile_name_for(path)
        progress: list[str] = []

        def report(message: str) -> None:
            progress.append(message)
            AppLogger.info(f"[debug-mcp] {message}")
            if on_progress is not None:
                on_progress(message)

        with self._launch_lock:
            with self._lock:
                self._close_node()
                self.profile = None
            profile_setup.stop_profile(profile)
            profile_setup.ensure_profile(path, fresh=fresh, on_progress=report)
            pid = profile_setup.launch_process(path, profile)
            with self._lock:
                self.profile, self.checkout = profile, path
            viewer = self._wait_for_viewer(LAUNCH_TIMEOUT)
        AppLogger.info(f"[debug-mcp] {profile} is up ({viewer})")
        return {"profile": profile, "checkout": str(path), "pid": pid, "viewer": viewer, "processes": self._processes(), "progress": progress}

    def stop(self) -> dict:
        with self._lock:
            self._require_running()
            profile = self.profile
            self._close_node()
            profile_setup.stop_profile(profile)
        return {"stopped": profile}

    def status(self) -> dict:
        processes = self._require_running()
        has_webui = any(p["role"] == "webui" for p in processes)
        return {
            "profile": self.profile,
            "checkout": str(self.checkout) if self.checkout else "",
            "processes": processes,
            "webui_url": self._webui_url() if has_webui else "",
            "index": self._index_counts(),
        }

    def rebuild_template(self, checkout: str = "") -> dict:
        path = Path(checkout) if checkout else self.checkout
        if path is None:
            raise DebugError("Pass checkout=... or call launch(checkout=...) first.")
        profile_setup.main_root_of(path)
        progress: list[str] = []

        def report(message: str) -> None:
            progress.append(message)
            AppLogger.info(f"[debug-mcp] {message}")

        target = profile_setup.rebuild_template(path, on_progress=report)
        return {"template": str(target), "progress": progress}

    def call(self, op: str, args: dict, target: str | None, timeout: float) -> Any:
        pid = self._resolve_target(target)
        deadline = time.monotonic() + timeout
        node = self._ensure_node()
        if not node.wait_registered(timeout=timeout):
            raise CallTimeout(TIMEOUT_MESSAGE.format(timeout=timeout))
        remaining = max(deadline - time.monotonic(), 0.0)
        reply = node.request(CALL_TOPIC, {"op": op, "args": args}, dst=f"{AGENT_ROLE}-{pid}", timeout=remaining)
        if reply is None:
            raise CallTimeout(TIMEOUT_MESSAGE.format(timeout=timeout))
        payload = reply.payload if isinstance(reply.payload, dict) else {}
        if not payload.get("ok"):
            raise DebugError(f"{op} failed: {payload.get('error') or 'the agent sent no result'}")
        return payload.get("result")

    def run_command(self, command_id: str, args: dict | None, target: str | None) -> dict:
        started = self.call("run_command", {"id": command_id, "args": args}, target, CALL_TIMEOUT)
        deadline = time.monotonic() + MODAL_WAIT_SECONDS
        while True:
            state = self.call("modal_state", {}, target, CALL_TIMEOUT)
            if state:
                return {**started, "modal": state.get("title")}
            if time.monotonic() >= deadline:
                return {**started, "modal": None}
            time.sleep(POLL_SECONDS)

    def wait_idle(self, timeout: float, target: str | None) -> dict:
        started = time.monotonic()
        deadline = started + timeout
        fast_answers = 0
        while True:
            remaining = max(deadline - time.monotonic(), POLL_SECONDS)
            try:
                idle = self.call("idle", {}, target, min(CALL_TIMEOUT, remaining))
            except CallTimeout:
                idle = None
            main_thread_ms = None if idle is None else float(idle["main_thread_ms"])
            fast_answers = fast_answers + 1 if main_thread_ms is not None and main_thread_ms < IDLE_MAIN_THREAD_MS else 0
            collected = profile_setup._collected_source_count(profile_setup._sample_data_db(self.profile))
            if fast_answers >= IDLE_FAST_ANSWERS and collected:
                return {"idle": True, "modal": idle["modal"], "waited": round(time.monotonic() - started, 1)}
            if time.monotonic() >= deadline:
                raise DebugError(f"Still busy after {timeout:g}s: {'; '.join(self._busy_reasons(fast_answers, main_thread_ms, collected))}")
            time.sleep(POLL_SECONDS)

    def tail_log(self, n: int, level: str) -> str:
        if self.profile is None:
            raise DebugError(NO_RUNNING_MESSAGE)
        if n <= 0:
            raise DebugError(f"n must be positive, not {n}")
        minimum = level.upper()
        if minimum and minimum not in LOG_LEVELS:
            raise DebugError(f"Unknown level {level!r}: use one of {', '.join(LOG_LEVELS)}")
        log_dir = profile_data_root(self.profile) / ".log"
        logs = list(log_dir.glob("*.log"))
        if not logs:
            raise DebugError(f"No log files in {log_dir}")
        newest = max(logs, key=lambda path: path.stat().st_mtime)
        lines = newest.read_text(encoding="utf-8", errors="replace").splitlines()
        if minimum:
            lines = self._lines_at_or_above(lines, LOG_LEVELS.index(minimum))
        return "\n".join(lines[-n:])

    def close(self) -> None:
        with self._lock:
            self._close_node()

    @staticmethod
    def _lines_at_or_above(lines: list[str], minimum: int) -> list[str]:
        kept, keep = [], False
        for line in lines:
            match = LOG_ENTRY.match(line)
            if match:
                keep = LOG_LEVELS.index(match.group(1)) >= minimum
            if keep:
                kept.append(line)
        return kept

    def _busy_reasons(self, fast_answers: int, main_thread_ms: float | None, collected: int) -> list[str]:
        reasons = []
        if main_thread_ms is None:
            reasons.append(f"main thread did not answer within {CALL_TIMEOUT:g}s")
        elif fast_answers < IDLE_FAST_ANSWERS:
            reasons.append(f"main thread answered in {main_thread_ms:.0f} ms (needs < {IDLE_MAIN_THREAD_MS:.0f} ms twice in a row)")
        if not collected:
            pending = self._index_counts()["pending"]
            reasons.append(f"{_plural(pending, 'collection task')} pending" if pending else "the sample DB has no collected sources yet")
        return reasons

    def _processes(self) -> list[dict]:
        if self.profile is None:
            return []
        processes = []
        for proc in AppProcess.list_profile_processes(self.profile):
            try:
                role = _role_of(proc.cmdline())
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                AppLogger.debug(f"[debug-mcp] skipped pid {proc.pid}: {type(e).__name__}")
                continue
            processes.append({"pid": proc.pid, "role": role, "target": f"{role}:{proc.pid}" if role in AGENT_ROLES else None})
        return processes

    def _require_running(self) -> list[dict]:
        processes = self._processes()
        if not processes:
            raise DebugError(NO_RUNNING_MESSAGE)
        return processes

    def _resolve_target(self, target: str | None) -> int:
        processes = self._require_running()
        targets = [p["target"] for p in processes if p["target"]]
        if target is None:
            viewers = [p["pid"] for p in processes if p["role"] == "viewer"]
            if not viewers:
                raise DebugError(f"{self.profile} has no Viewer; pass target= one of {targets}")
            return viewers[0]
        if target not in targets:
            raise DebugError(f"Unknown target {target!r}; use one of {targets} from status")
        return int(target.split(":", 1)[1])

    def _wait_for_viewer(self, timeout: float) -> str:
        deadline = time.monotonic() + timeout
        node = self._ensure_node()
        while True:
            processes = self._processes()
            if not processes:
                raise DebugError(f"{self.profile} exited before its Viewer answered; see tail_log")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise DebugError(f"The Viewer of {self.profile} did not answer within {timeout:g}s; see tail_log")
            if node.wait_registered(timeout=min(PING_TIMEOUT, remaining)):
                for viewer in (p for p in processes if p["role"] == "viewer"):
                    reply = node.request(CALL_TOPIC, {"op": "ping", "args": {}}, dst=f"{AGENT_ROLE}-{viewer['pid']}", timeout=min(PING_TIMEOUT, remaining))
                    if reply is not None and isinstance(reply.payload, dict) and reply.payload.get("ok"):
                        return viewer["target"]
            time.sleep(POLL_SECONDS)

    def _ensure_node(self) -> Node:
        with self._lock:
            if self._node is not None and self._node.profile != self.profile:
                self._close_node()
            if self._node is None:
                self._node = Node(NODE_ROLE, profile=self.profile)
                self._node.start()
            return self._node

    def _close_node(self) -> None:
        if self._node is not None:
            self._node.stop()
            self._node = None

    def _webui_url(self) -> str:
        state = profile_data_root(self.profile) / ".temp" / "webui.json"
        if not state.is_file():
            return ""
        try:
            data = json.loads(state.read_text(encoding="utf-8"))
        except (OSError, ValueError) as e:
            AppLogger.info(f"[debug-mcp] {state} is not readable yet, so the WebUI URL is not available yet: {e}")
            return ""
        return str(data.get("url", "")) if isinstance(data, dict) else ""

    def _index_counts(self) -> dict:
        db_path = profile_setup._sample_data_db(self.profile)
        if not db_path.is_file():
            return {"sources": 0, "pending": 0}
        conn = open_readonly(db_path)
        try:
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('sources', 'collection_status')")}
            sources = conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] if "sources" in tables else 0
            placeholders = ", ".join("?" for _ in profile_setup.UNFINISHED_STATUSES)
            pending = conn.execute(f"SELECT COUNT(*) FROM collection_status WHERE status IN ({placeholders})", profile_setup.UNFINISHED_STATUSES).fetchone()[0] if "collection_status" in tables else 0
        finally:
            conn.close()
        return {"sources": sources, "pending": pending}


def _as_text(result: Any) -> str:
    return result if isinstance(result, str) else json.dumps(result, ensure_ascii=False, indent=2)


TARGET_HELP = 'target is a process from status ("viewer:<pid>", "tray:<pid>", "webui:<pid>"); the first Viewer when omitted.'
WIDGET_HELP = "widget is an objectName or the visible text of a widget."

SERVER_INSTRUCTIONS = (
    "Drives a debug Wafer that runs on sample data only. Call launch(checkout=<path of the main checkout or a .claude/worktrees/<task>>) first; "
    "every other tool works on the profile that launch started. Use status for process targets and the WebUI URL (drive the WebUI with Playwright)."
)


def build_server(session: DebugSession) -> MCPServer:
    server = MCPServer(SERVER_NAME, instructions=SERVER_INSTRUCTIONS)

    def tool(description: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        def register(fn: Callable[..., Any]) -> Callable[..., Any]:
            @functools.wraps(fn)
            def guarded(*args: Any, **kwargs: Any) -> Any:
                try:
                    result = fn(*args, **kwargs)
                except DebugError as e:
                    AppLogger.info(f"[debug-mcp] {fn.__name__}: {e}")
                    return str(e)
                except (ValueError, LookupError) as e:
                    AppLogger.info(f"[debug-mcp] {fn.__name__} rejected its input: {type(e).__name__}: {e}")
                    return f"{type(e).__name__}: {e}"
                except Exception as e:
                    AppLogger.warning(f"[debug-mcp] {fn.__name__} failed: {type(e).__name__}: {e}", exc=e)
                    return f"{type(e).__name__}: {e}"
                return result if isinstance(result, Image) else _as_text(result)

            server.tool(description=description, structured_output=False)(guarded)
            return fn

        return register

    def agent(op: str, process: str | None, **args: Any) -> Any:
        return session.call(op, args, process, CALL_TIMEOUT)

    @tool(
        "Launch the debug Wafer of a checkout (the main checkout or .claude/worktrees/<task>) on its sample profile. Quits that profile first if it runs; fresh=True recreates it from the sample template. Returns when the Viewer answers."
    )
    def launch(checkout: str, fresh: bool = False) -> Any:
        return session.launch(checkout, fresh)

    @tool("Quit every process of the launched debug profile.")
    def stop() -> Any:
        return session.stop()

    @tool("Processes (pid, role, target), the WebUI URL and the sample index progress of the launched debug profile.")
    def status() -> Any:
        return session.status()

    @tool("Rebuild the sample template for a checkout's schema (defaults to the launched checkout). Takes a few minutes.")
    def rebuild_template(checkout: str = "") -> Any:
        return session.rebuild_template(checkout)

    @tool(f"PNG of a window, panel or modal (the active window when widget is omitted), scaled to max_side. {WIDGET_HELP} {TARGET_HELP}")
    def screenshot(widget: str | None = None, max_side: int = DEFAULT_SCREENSHOT_SIDE, target: str | None = None) -> Any:
        return Image(data=agent("screenshot", target, target=widget, max_side=max_side), format="png")

    @tool(f"The Viewer's database, folder paths, query, selection and item count. {TARGET_HELP}")
    def get_state(target: str | None = None) -> Any:
        return agent("get_state", target)

    @tool(f"Tree of visible widgets (class, objectName, text, geometry) from root, depth levels deep. {TARGET_HELP}")
    def widget_tree(root: str | None = None, depth: int = 3, target: str | None = None) -> Any:
        return agent("widget_tree", target, root=root, depth=depth)

    @tool(f"Read the Qt property prop of a widget. {WIDGET_HELP} {TARGET_HELP}")
    def get_property(widget: str, prop: str, target: str | None = None) -> Any:
        return agent("get_property", target, name=widget, prop=prop)

    @tool("The last n lines of the newest log file of the launched profile; level keeps entries at or above DEBUG/INFO/WARNING/ERROR/CRITICAL.")
    def tail_log(n: int = 100, level: str = "") -> Any:
        return session.tail_log(n, level)

    @tool(f"Commands of the CommandRegistry whose id or name contains filter. {TARGET_HELP}")
    def list_commands(filter: str = "", target: str | None = None) -> Any:
        return agent("list_commands", target, filter=filter)

    @tool(f"Run a command by id with keyword args; reports the title of a modal it opens. {TARGET_HELP}")
    def run_command(id: str, args: dict | None = None, target: str | None = None) -> Any:
        return session.run_command(id, args, target)

    @tool(f"Title, labels, fields and buttons of the open modal dialog or popup (null when none). {TARGET_HELP}")
    def modal_state(target: str | None = None) -> Any:
        return agent("modal_state", target)

    @tool(f"Enter value into a field of the open modal (objectName, label or placeholder). {TARGET_HELP}")
    def modal_input(field: str, value: str, target: str | None = None) -> Any:
        return agent("modal_input", target, field=field, value=value)

    @tool(f"Press a button or menu item of the open modal by its text; runs after the reply. {TARGET_HELP}")
    def modal_click(text: str, target: str | None = None) -> Any:
        return agent("modal_click", target, text=text)

    @tool(f"Click a widget; runs after the reply. {WIDGET_HELP} {TARGET_HELP}")
    def click(widget: str, target: str | None = None) -> Any:
        return agent("click", target, target=widget)

    @tool(f"Type text into a widget. {WIDGET_HELP} {TARGET_HELP}")
    def type_text(widget: str, text: str, target: str | None = None) -> Any:
        return agent("type_text", target, target=widget, text=text)

    @tool(f"Send a key sequence such as Ctrl+A to a widget (the focused one when omitted); runs after the reply. {WIDGET_HELP} {TARGET_HELP}")
    def key(sequence: str, widget: str | None = None, target: str | None = None) -> Any:
        return agent("key", target, target=widget, sequence=sequence)

    @tool(f"Wait until the main thread answers in < 200 ms twice in a row and the sample index has nothing pending, or say what is still busy. {TARGET_HELP}")
    def wait_idle(timeout: float = 30, target: str | None = None) -> Any:
        return session.wait_idle(timeout, target)

    return server


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m debug.mcp_server", description="MCP server (stdio) that launches and drives debug profiles of Wafer.", allow_abbrev=False)
    parser.add_argument(
        PROFILE_ARG,
        required=True,
        choices=[TOOLS_PROFILE],
        help=f"Always {TOOLS_PROFILE}: keeps this server's own data and logs out of the normal Wafer's data folder.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    parse_args(sys.argv[1:] if argv is None else argv)
    AppLogger.set_role(LOG_ROLE)
    AppLogger.info(f"[debug-mcp] {SERVER_NAME} serves on stdio (profile {current_profile()})")
    session = DebugSession()
    try:
        build_server(session).run("stdio")
    finally:
        session.close()


if __name__ == "__main__":
    main()

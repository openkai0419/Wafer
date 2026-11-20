import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import psutil
from PIL import Image

import wafer.core.common.paths as paths
from wafer.core.common.profile import profile_from_args
from wafer.core.ipc.node import Node
from wafer.core.platform import explorer_menu
from wafer.core.platform.process import MAIN_SCRIPT, AppProcess

CHECKOUT = paths.get_app_root_dir()
AGENT_ROLE = "debug_agent"
CALL_TOPIC = "debug.call"
POLL_SECONDS = 0.1
WORKER_FLAGS = ("--collector", "--parser")
CORE_ROLES = ("tray", "viewer", "indexer")
SAMPLE_COLORS = ((200, 40, 40), (40, 200, 40), (40, 40, 200), (200, 200, 40))


@dataclass(frozen=True)
class IsolatedDirs:
    app_data: Path
    sample: Path
    cwd: Path


def wait_until(predicate, timeout: float, what: str):
    deadline = time.monotonic() + timeout
    while True:
        result = predicate()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"timed out after {timeout:g}s waiting for {what}")
        time.sleep(POLL_SECONDS)


def write_sample(root: Path) -> None:
    val = root / "coco" / "val2017"
    val.mkdir(parents=True)
    for index, color in enumerate(SAMPLE_COLORS):
        Image.new("RGB", (64 + index * 8, 48), color).save(val / f"{index:012d}.jpg", quality=90)
    for index, color in enumerate(SAMPLE_COLORS[:2]):
        Image.new("RGB", (40, 40 + index * 8), color).save(root / f"top_{index}.png")


def isolate_debug_dirs(tmp_path: Path, monkeypatch) -> IsolatedDirs:
    dirs = IsolatedDirs(app_data=tmp_path / "appdata", sample=tmp_path / "sample", cwd=tmp_path / "cwd")
    for path in (dirs.app_data, dirs.cwd):
        path.mkdir(parents=True)
    write_sample(dirs.sample)
    root = str(dirs.app_data)

    class TmpPlatformDirs:
        def __init__(self, appname=None):
            self.user_data_dir = root
            self.user_config_dir = root

    monkeypatch.setattr(paths, "PlatformDirs", TmpPlatformDirs)
    monkeypatch.setenv("WIN_PD_OVERRIDE_LOCAL_APPDATA", root)
    monkeypatch.setenv("WAFER_DEBUG_SAMPLE_ROOT", str(dirs.sample))
    return dirs


def explorer_menu_snapshot() -> tuple[bool, str | None]:
    return explorer_menu.is_enabled(), explorer_menu.stored_command()


def role_of(cmdline: list[str]) -> str:
    if "--tray" in cmdline:
        return "tray"
    if "--webui" in cmdline:
        return "webui"
    if "--indexer" in cmdline:
        return "indexer"
    if any(flag in cmdline for flag in WORKER_FLAGS):
        return "worker"
    return "viewer"


def _same_path(a, b) -> bool:
    return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))


def checkout_processes(cwd: Path) -> list[psutil.Process]:
    found = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = proc.info.get("cmdline") or []
            script = next((arg for arg in cmdline if os.path.normcase(os.path.basename(arg)) == "main.py"), None)
            if script is None or not os.path.isabs(script) or not _same_path(script, MAIN_SCRIPT):
                continue
            if profile_from_args(cmdline) is not None or not _same_path(proc.cwd(), cwd):
                continue
            found.append(proc)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            continue
    return found


def roles(procs: list[psutil.Process]) -> dict[str, list[int]]:
    by_role: dict[str, list[int]] = {}
    for proc in procs:
        try:
            by_role.setdefault(role_of(proc.cmdline()), []).append(proc.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return by_role


def core_pids(procs: list[psutil.Process]) -> dict[str, list[int]]:
    found = roles(procs)
    if not all(found.get(role) for role in CORE_ROLES):
        return {}
    return found


def still_running(pids: dict[str, list[int]]) -> bool:
    return all(psutil.pid_exists(pid) for role in CORE_ROLES for pid in pids[role])


def visible_window_titles(pid: int) -> list[str]:
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    titles: list[str] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value:
                titles.append(buffer.value)
        return True

    user32.EnumWindows(collect, 0)
    return titles


def spawn_normal(cwd: Path) -> None:
    exe = AppProcess.base_command()[0]
    AppProcess.spawn([exe, MAIN_SCRIPT, "--tray"], cwd=str(cwd))
    AppProcess.spawn([exe, MAIN_SCRIPT, "--viewer"], cwd=str(cwd))


QUIT_ALL_DRIVER = """
import sys, time
from wafer.core.ipc.node import Node
from wafer.core.platform.process import AppProcess
node = Node("smoke_quit_all")
node.start()
try:
    if not node.wait_registered(30):
        sys.exit(2)
    node.send("app.quit_all", dst="tray")
    deadline = time.monotonic() + 60
    while AppProcess.tray_pid() is not None and time.monotonic() < deadline:
        time.sleep(0.1)
finally:
    node.stop()
"""


def quit_all_normal(cwd: Path) -> None:
    env = os.environ | {"PYTHONPATH": str(CHECKOUT)}
    result = subprocess.run([sys.executable, "-c", QUIT_ALL_DRIVER], cwd=str(cwd), env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, f"quit_all driver exited with {result.returncode}: {result.stderr[-2000:]}"


def agent_call(node: Node, pid: int, op: str, args: dict | None = None, timeout: float = 5.0):
    reply = node.request(CALL_TOPIC, {"op": op, "args": args or {}}, dst=f"{AGENT_ROLE}-{pid}", timeout=timeout)
    if reply is None or not isinstance(reply.payload, dict) or not reply.payload.get("ok"):
        return None
    return reply.payload


def terminate_checkout_processes(cwd: Path) -> None:
    procs = checkout_processes(cwd)
    if procs:
        AppProcess.terminate_tree(procs)

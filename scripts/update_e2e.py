from __future__ import annotations

import argparse
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

import psutil

from scripts.build import EXTENSION_RUNTIME_DIRS
from scripts.make_local_update import write_update_source

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DIST = ROOT / "dist" / "Wafer"
STARTUP_TIMEOUT = 120
APPLY_TIMEOUT = 180
HELPER_WAIT_SECONDS = 60
DRIVER_TIMEOUT = 120
POLL_INTERVAL = 0.5

LIB_MARKER = "extensions/ffmpeg/lib/e2e_marker.txt"
PACKAGES_MARKER = "extensions/.packages/e2e_marker.txt"
USER_EXTENSION_MARKER = "extensions/e2e_user_ext/README.md"
MARKERS = (LIB_MARKER, PACKAGES_MARKER, USER_EXTENSION_MARKER)

# AppData is isolated by env, the registry is not: when the real entry points at a missing file,
# explorer_menu.sync() rewrites it to the Wafer.exe it runs from, which here is deleted afterwards.
E2E_MENU_KEY = r"Software\Wafer-update-e2e\explorer-menu"
WEBUI_SHUTDOWN_LOG = "WebUI received app.shutdown."

_FALLBACK_RE = re.compile(r'(FALLBACK_VERSION\s*=\s*["\'])(.+?)(["\'])')
_FORCE_RE = re.compile(r"^FORCE_UPDATE_ENABLED = False$", re.MULTILINE)
_MENU_KEY_RE = re.compile(r'^MENU_KEY = r".+"$', re.MULTILINE)
_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")

DISABLE_AUTO_CHECK_DRIVER = """
from wafer.builtins.updater.state import set_auto_check_enabled
set_auto_check_enabled(False)
"""

WEBUI_PORT_DRIVER = """
from wafer.app.webui.settings import DEFAULT_HOST, WebUISettings
WebUISettings().save(DEFAULT_HOST, {port})
"""

STAGE_DRIVER = """
import sys
from wafer.builtins.updater import service, stage
info = service.check_for_updates().info
if info is None or not info.is_newer:
    sys.exit(2)
stage.stage_update(info.tag_name, info.latest_version)
sys.exit(0 if stage.staged_version() else 3)
"""

RESTART_DRIVER = """
import sys
from types import SimpleNamespace
from wafer.core.ipc.node import Node
from wafer.builtins.updater.stage import restart_into_launcher
node = Node("launcher")
node.start()
if not node.wait_registered(30):
    sys.exit(2)
host = SimpleNamespace(_node=node, slot_id=None, close=lambda: None)
restarted = restart_into_launcher(host)
node.stop()
sys.exit(0 if restarted else 3)
"""


class E2EFailure(Exception):
    pass


def version_file(app_root: Path) -> Path:
    return app_root / "wafer" / "_version.py"


def read_fallback_version(app_root: Path) -> str:
    match = _FALLBACK_RE.search(version_file(app_root).read_text(encoding="utf-8"))
    if match is None:
        raise E2EFailure(f"FALLBACK_VERSION not found in {version_file(app_root)}")
    return match.group(2)


def set_fallback_version(app_root: Path, version: str) -> None:
    path = version_file(app_root)
    text, count = _FALLBACK_RE.subn(lambda m: f"{m.group(1)}{version}{m.group(3)}", path.read_text(encoding="utf-8"), count=1)
    if count != 1:
        raise E2EFailure(f"FALLBACK_VERSION not found in {path}")
    path.write_text(text, encoding="utf-8")


def next_version(version: str) -> str:
    match = _RELEASE_RE.match(version)
    if match is None:
        raise E2EFailure(f"not a release version: {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def force_local_updates(app_root: Path) -> None:
    path = app_root / "wafer" / "_dev.py"
    text, count = _FORCE_RE.subn("FORCE_UPDATE_ENABLED = True", path.read_text(encoding="utf-8"), count=1)
    if count != 1:
        raise E2EFailure(f"'FORCE_UPDATE_ENABLED = False' not found in {path}")
    path.write_text(text, encoding="utf-8")


def isolate_explorer_menu(app_root: Path) -> None:
    path = app_root / "wafer" / "core" / "platform" / "explorer_menu.py"
    text, count = _MENU_KEY_RE.subn(lambda _: f'MENU_KEY = r"{E2E_MENU_KEY}"', path.read_text(encoding="utf-8"), count=1)
    if count != 1:
        raise E2EFailure(f"MENU_KEY not found in {path}")
    path.write_text(text, encoding="utf-8")


def explorer_menu_command() -> str | None:
    from wafer.core.platform import explorer_menu

    return explorer_menu.stored_command()


def require_explorer_menu_unchanged(before: str | None) -> None:
    after = explorer_menu_command()
    if after != before:
        raise E2EFailure(f"the real Explorer menu entry changed: {before!r} -> {after!r}")


def copy_release(dist: Path, dst: Path) -> None:
    extensions = os.path.normcase(str(dist / "extensions"))

    def ignore(directory: str, names: list[str]) -> set[str]:
        ignored = {"__pycache__"}
        here = os.path.normcase(directory)
        if here == os.path.normcase(str(dist)):
            ignored.add(".update")
        if here == extensions or here.startswith(extensions + os.sep):
            ignored |= EXTENSION_RUNTIME_DIRS
        return {name for name in names if name in ignored}

    shutil.copytree(dist, dst, ignore=ignore)


def seed_markers(app_root: Path) -> None:
    for rel in MARKERS:
        path = app_root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rel, encoding="utf-8")


def missing_markers(app_root: Path) -> list[str]:
    return [rel for rel in MARKERS if not (app_root / rel).is_file()]


def isolated_env(work: Path) -> dict[str, str]:
    temp = work / "tmp"
    temp.mkdir(parents=True, exist_ok=True)
    return {
        "WIN_PD_OVERRIDE_LOCAL_APPDATA": str(work / "appdata"),
        "WAFER_UPDATE_SOURCE_DIR": str(work / "source"),
        "WAFER_UPDATE_BUSY_ACTION": "skip",
        "WAFER_UPDATE_WAIT_SECONDS": str(HELPER_WAIT_SECONDS),
        "TEMP": str(temp),
        "TMP": str(temp),
    }


def processes_under(folder: Path) -> list[psutil.Process]:
    prefix = os.path.normcase(str(folder)).rstrip("\\") + "\\"
    found = []
    for proc in psutil.process_iter(["exe"]):
        exe = proc.info.get("exe")
        if exe and os.path.normcase(exe).startswith(prefix):
            found.append(proc)
    return found


def describe(procs: list[psutil.Process]) -> str:
    lines = []
    for proc in procs:
        try:
            lines.append(f"  pid={proc.pid} {' '.join(proc.cmdline()[1:])}")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return "\n".join(lines) or "  (none)"


def stop_processes_under(folder: Path) -> None:
    procs = processes_under(folder)
    for proc in procs:
        try:
            proc.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    psutil.wait_procs(procs, timeout=10)


def wait_until(condition: Callable[[], bool], timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() >= deadline:
            raise E2EFailure(f"timed out after {timeout}s waiting for {what}")
        time.sleep(POLL_INTERVAL)


def run_driver(app_root: Path, env: dict[str, str], code: str, what: str) -> None:
    pythonw = app_root / "python" / "wafer-pythonw.exe"
    try:
        proc = subprocess.run([str(pythonw), "-c", code], cwd=app_root, env=env, timeout=DRIVER_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        raise E2EFailure(f"{what} did not finish within {DRIVER_TIMEOUT}s") from exc
    if proc.returncode != 0:
        raise E2EFailure(f"{what} failed (exit {proc.returncode})")


def log_dir(work: Path) -> Path:
    return work / "appdata" / "Wafer" / ".log"


def old_version_logs(work: Path) -> Path:
    return work / "logs-old-version"


def keep_old_version_logs(work: Path) -> None:
    shutil.copytree(log_dir(work), old_version_logs(work), dirs_exist_ok=True)


def logs_contain(folder: Path, text: str) -> bool:
    return any(text in path.read_text(encoding="utf-8", errors="replace") for path in folder.glob("*.log*"))


def open_workspaces() -> set[str]:
    from wafer.core.platform.workspace_lock import WorkspaceLock
    from wafer.core.store.workspace import WorkspaceStore

    store = WorkspaceStore.instance()
    return WorkspaceLock.open_slot_ids(slot.slot_id for slot in store.list_slots())


def registered_workspaces() -> set[str]:
    from wafer.core.store.workspace import WorkspaceStore

    return set(WorkspaceStore.instance().get_active_slot_ids())


def background_running() -> bool:
    from wafer.constants import APP_DATA_DIR_NAME, DEFAULT_DB_NAME, TRAY_LOCK_NAME
    from wafer.core.platform.process_lock import SafeProcessLock

    return SafeProcessLock.is_held(TRAY_LOCK_NAME) and SafeProcessLock.is_held(f"{APP_DATA_DIR_NAME}_{DEFAULT_DB_NAME}")


def prepare(dist: Path, work: Path) -> tuple[Path, str]:
    app_root = work / "app" / "Wafer"
    new_root = work / "new" / "Wafer"
    print(f"[update-e2e] Copying {dist} -> {app_root}")
    copy_release(dist, app_root)
    copy_release(dist, new_root)
    new_version = next_version(read_fallback_version(app_root))
    set_fallback_version(new_root, new_version)
    force_local_updates(app_root)
    force_local_updates(new_root)
    isolate_explorer_menu(app_root)
    isolate_explorer_menu(new_root)
    seed_markers(app_root)
    write_update_source(new_root, work / "source", new_version)
    shutil.rmtree(new_root.parent)
    return app_root, new_version


def start_old_version(app_root: Path, env: dict[str, str]) -> str:
    print("[update-e2e] Turning off the automatic update check (no network, no update panel)")
    run_driver(app_root, env, DISABLE_AUTO_CHECK_DRIVER, "turning off the automatic update check")
    print("[update-e2e] Starting the old version. Its windows open for about a minute; leave them alone.")
    subprocess.Popen([str(app_root / "Wafer.exe")], cwd=app_root, env=env)
    wait_until(lambda: bool(open_workspaces() & registered_workspaces()) and background_running(), STARTUP_TIMEOUT, "the old Viewer, tray and indexer to start")
    slot_id = sorted(open_workspaces() & registered_workspaces())[0]
    print(f"[update-e2e] Old version running with workspace {slot_id}:\n{describe(processes_under(app_root))}")
    return slot_id


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def start_old_webui(app_root: Path, env: dict[str, str]) -> subprocess.Popen:
    from wafer.core.store.workspace import WorkspaceStore

    run_driver(app_root, env, WEBUI_PORT_DRIVER.format(port=free_port()), "choosing the WebUI port")
    print("[update-e2e] Opening the old WebUI")
    proc = subprocess.Popen([str(app_root / "python" / "wafer-pythonw.exe"), str(app_root / "main.py"), "--webui", "--no-browser"], cwd=app_root, env=env)
    wait_until(WorkspaceStore.instance().get_restore_webui, STARTUP_TIMEOUT, "the old WebUI to connect to the tray")
    return proc


def webui_running(app_root: Path) -> bool:
    for proc in processes_under(app_root):
        try:
            if "--webui" in proc.cmdline():
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def require_webui_closed(work: Path, old_webui: subprocess.Popen) -> None:
    if old_webui.poll() is None:
        raise E2EFailure("the old WebUI is still running after restart_into_launcher")
    if not logs_contain(old_version_logs(work), WEBUI_SHUTDOWN_LOG):
        raise E2EFailure(f"the old WebUI exited without receiving app.shutdown (logs: {old_version_logs(work)})")


def verify_update(work: Path, app_root: Path, new_version: str, slot_id: str) -> None:
    update_dir = app_root / ".update"

    def applied_and_reported() -> bool:
        failed = update_dir / "failed.txt"
        if failed.is_file():
            raise E2EFailure(f"update failed: {failed.read_text(encoding='utf-8', errors='replace')}")
        return logs_contain(log_dir(work), f"Update applied successfully: v{new_version}") and not (update_dir / "applied.txt").exists() and not (update_dir / "next").exists()

    wait_until(applied_and_reported, APPLY_TIMEOUT, f"v{new_version} to be applied and reported by the new version")
    wait_until(lambda: slot_id in open_workspaces(), STARTUP_TIMEOUT, f"workspace {slot_id} to be restored")
    wait_until(lambda: webui_running(app_root), STARTUP_TIMEOUT, "the WebUI to reopen in the new version")
    if read_fallback_version(app_root) != new_version:
        raise E2EFailure(f"app root still has v{read_fallback_version(app_root)}")
    if missing := missing_markers(app_root):
        raise E2EFailure(f"lost across the update: {missing}")
    if logs_contain(old_version_logs(work), "wait_procs_then_kill: force-killed"):
        raise E2EFailure(f"the old Viewer or WebUI did not close by itself on shutdown and had to be killed (logs: {old_version_logs(work)})")
    print(f"[update-e2e] New version running:\n{describe(processes_under(app_root))}")


def report_failure(work: Path, app_root: Path) -> None:
    apply_log = app_root / ".update" / "apply.log"
    if apply_log.is_file():
        print(f"[update-e2e] {apply_log}:\n{apply_log.read_text(encoding='utf-8', errors='replace')}")
    print(f"[update-e2e] Processes still running:\n{describe(processes_under(work))}")
    print(f"[update-e2e] App logs: {log_dir(work)}")


def run(dist: Path, keep: bool) -> int:
    if not (dist / "Wafer.exe").is_file():
        print(f"[update-e2e] No portable build at {dist}. Run scripts/build.py first.", file=sys.stderr)
        return 1
    work = Path(tempfile.mkdtemp(prefix="wafer-update-e2e-"))
    app_root = work / "app" / "Wafer"
    failed = True
    try:
        app_root, new_version = prepare(dist, work)
        os.environ.update(isolated_env(work))
        env = dict(os.environ)
        menu_command = explorer_menu_command()
        print(f"[update-e2e] Real Explorer menu entry (must not change): {menu_command}")
        slot_id = start_old_version(app_root, env)
        old_webui = start_old_webui(app_root, env)
        print(f"[update-e2e] Staging v{new_version}")
        run_driver(app_root, env, STAGE_DRIVER, "staging")
        print("[update-e2e] Restarting into the launcher")
        run_driver(app_root, env, RESTART_DRIVER, "restart_into_launcher")
        keep_old_version_logs(work)
        require_webui_closed(work, old_webui)
        verify_update(work, app_root, new_version, slot_id)
        require_explorer_menu_unchanged(menu_command)
        failed = False
        print(f"[update-e2e] Real Explorer menu entry after the run: {explorer_menu_command()}")
        print(f"[update-e2e] OK: updated to v{new_version}, workspace and WebUI restored, lib/.packages/user extension kept, Explorer menu untouched")
        return 0
    except E2EFailure as exc:
        print(f"[update-e2e] FAILED: {exc}", file=sys.stderr)
        report_failure(work, app_root)
        return 1
    finally:
        stop_processes_under(work)
        if failed or keep:
            print(f"[update-e2e] Kept {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Update a copy of the portable build to a newer copy through the real updater, launcher and app processes.")
    parser.add_argument("--dist", type=Path, default=DEFAULT_DIST, help="portable build to test (default: dist/Wafer)")
    parser.add_argument("--keep", action="store_true", help="keep the work folder even when the run succeeds")
    args = parser.parse_args(argv)
    if sys.platform != "win32":
        print("[update-e2e] Windows only", file=sys.stderr)
        return 1
    return run(args.dist.resolve(), args.keep)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

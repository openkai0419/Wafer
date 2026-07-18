import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import psutil
import pytest

from scripts.build import find_csc
from wafer.builtins.updater.plan import PlanOp, execute_plan, generate_plan, plan_path, read_plan, write_plan


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="launcher update apply is Windows-only")

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER_CS = ROOT / "scripts" / "launcher" / "Wafer.cs"

OLD_TREE = {
    "python/wafer-pythonw.exe": "old-python",
    "python/Lib/site.py": "old-site",
    "main.py": "old-main",
    "wafer/_version.py": 'FALLBACK_VERSION = "1.0.0"\n',
    "_resources/translations.json": "old-res",
    "Uninstaller.exe": "old-uninstaller",
    "extensions/image/__init__.py": "old-image",
    "extensions/ffmpeg/__init__.py": "old-ffmpeg",
    "extensions/ffmpeg/lib/ffmpeg.exe": "ffmpeg-bin",
    "extensions/myext/__init__.py": "user-ext",
    "extensions/.packages/numpy/__init__.py": "site-package",
}

NEW_TREE = {
    ".update/next/python/wafer-pythonw.exe": "new-python",
    ".update/next/main.py": "new-main",
    ".update/next/Wafer.exe": "new-launcher",
    ".update/next/Uninstaller.exe": "new-uninstaller",
    ".update/next/wafer/_version.py": 'FALLBACK_VERSION = "2.0.0"\n',
    ".update/next/_resources/translations.json": "new-res",
    ".update/next/extensions/image/__init__.py": "new-image",
    ".update/next/extensions/ffmpeg/__init__.py": "new-ffmpeg",
}

IGNORED_SNAPSHOT_FILES = {"Wafer.exe", ".update/apply.log", ".update/applied.txt", ".update/failed.txt"}


@pytest.fixture(scope="module")
def launcher_exe(tmp_path_factory):
    try:
        csc = find_csc()
    except FileNotFoundError:
        pytest.skip(".NET Framework csc.exe not available")
    exe = tmp_path_factory.mktemp("launcher") / "Wafer.exe"
    refs = ["/r:System.dll", "/r:System.Drawing.dll", "/r:System.Windows.Forms.dll"]
    subprocess.run([csc, "/nologo", "/target:exe", *refs, f"/out:{exe}", str(LAUNCHER_CS)], check=True, capture_output=True)
    return exe


def build_tree(root: Path, launcher_exe: Path) -> None:
    for spec in (OLD_TREE, NEW_TREE):
        for rel, content in spec.items():
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    shutil.copy(launcher_exe, root / "Wafer.exe")
    ops = generate_plan(root)
    write_plan(plan_path(root), ops)
    (root / ".update/ready.json").write_text(json.dumps({"schema": 1, "target_version": "2.0.0"}), encoding="utf-8")


def run_helper(root: Path, launcher_exe: Path, wait_seconds: int = 0, busy_action: str = "skip") -> subprocess.CompletedProcess:
    env = dict(os.environ, WAFER_UPDATE_WAIT_SECONDS=str(wait_seconds), WAFER_UPDATE_BUSY_ACTION=busy_action)
    cmd = [str(launcher_exe), "--wafer-apply", str(root), "--wafer-no-launch"]
    return subprocess.run(cmd, cwd=launcher_exe.parent, env=env, timeout=25, capture_output=True)


def snapshot(root: Path) -> dict:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if rel in IGNORED_SNAPSHOT_FILES:
            continue
        result[rel] = path.read_text(encoding="utf-8", errors="replace")
    return result


def test_csharp_apply_succeeds(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)

    proc = run_helper(root, launcher_exe)

    log = (root / ".update/apply.log").read_text(encoding="utf-8", errors="replace")
    assert proc.returncode == 0, log
    assert (root / ".update/applied.txt").read_text(encoding="utf-8") == "2.0.0", log
    assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "new-python"
    assert (root / "main.py").read_text(encoding="utf-8") == "new-main"
    assert "2.0.0" in (root / "wafer/_version.py").read_text(encoding="utf-8")
    assert (root / "extensions/ffmpeg/lib/ffmpeg.exe").read_text(encoding="utf-8") == "ffmpeg-bin"
    assert (root / "extensions/myext/__init__.py").read_text(encoding="utf-8") == "user-ext"
    assert (root / "extensions/.packages/numpy/__init__.py").read_text(encoding="utf-8") == "site-package"
    assert (root / ".update/backup/python/wafer-pythonw.exe").read_text(encoding="utf-8") == "old-python"
    assert not (root / ".update/apply.plan").exists()
    assert not (root / ".update/ready.json").exists()
    assert not (root / ".update/next").exists()
    assert (root / "Wafer.exe").read_text(encoding="utf-8", errors="replace") == "new-launcher"
    assert (root / "Uninstaller.exe").read_text(encoding="utf-8") == "new-uninstaller"


def test_csharp_matches_python_reference_executor(tmp_path, launcher_exe):
    cs_root = tmp_path / "cs"
    py_root = tmp_path / "py"
    build_tree(cs_root, launcher_exe)
    build_tree(py_root, launcher_exe)

    proc = run_helper(cs_root, launcher_exe)
    assert proc.returncode == 0

    execute_plan(read_plan(plan_path(py_root)), py_root)
    (py_root / ".update/apply.plan").unlink()
    (py_root / ".update/ready.json").unlink()
    shutil.rmtree(py_root / ".update/next")

    assert snapshot(cs_root) == snapshot(py_root)


def test_csharp_rolls_back_on_failure(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    before = snapshot(root)

    ops = read_plan(plan_path(root))
    broken = ops[:6] + [PlanOp(src=".update/next/does_not_exist", dst="ghost")] + ops[6:]
    write_plan(plan_path(root), broken)
    before[".update/apply.plan"] = plan_path(root).read_text(encoding="utf-8")

    proc = run_helper(root, launcher_exe)

    assert proc.returncode == 1
    log = (root / ".update/apply.log").read_text(encoding="utf-8", errors="replace")
    assert (root / ".update/failed.txt").is_file(), log
    assert not (root / ".update/apply.plan").exists()
    assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "old-python"
    assert (root / "main.py").read_text(encoding="utf-8") == "old-main"
    after = snapshot(root)
    after.pop(".update/ready.json", None)
    before.pop(".update/ready.json", None)
    before.pop(".update/apply.plan", None)
    assert after == before


def spawn_blocker(root: Path) -> subprocess.Popen:
    dummy = root / "python" / "dummy.exe"
    shutil.copy(Path(os.environ["ComSpec"]), dummy)
    holder = subprocess.Popen([str(dummy), "/c", "ping", "-n", "20", "127.0.0.1"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    deadline = time.monotonic() + 10
    while psutil.Process(holder.pid).exe() != str(dummy):
        assert time.monotonic() < deadline
        time.sleep(0.05)
    return holder


def test_csharp_skips_when_other_process_running(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    holder = spawn_blocker(root)
    try:
        proc = run_helper(root, launcher_exe, wait_seconds=1, busy_action="skip")

        assert proc.returncode == 1
        assert (root / ".update/apply.plan").is_file()
        assert (root / ".update/ready.json").is_file()
        assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "old-python"
        assert not (root / ".update/applied.txt").exists()
        assert not (root / ".update/failed.txt").exists()
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_csharp_force_closes_blocker_then_applies(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    holder = spawn_blocker(root)
    try:
        proc = run_helper(root, launcher_exe, wait_seconds=1, busy_action="close")

        log = (root / ".update/apply.log").read_text(encoding="utf-8", errors="replace")
        assert proc.returncode == 0, log
        assert holder.wait(timeout=10) != 0
        assert (root / ".update/applied.txt").read_text(encoding="utf-8") == "2.0.0", log
        assert (root / "main.py").read_text(encoding="utf-8") == "new-main"
        assert not (root / ".update/apply.plan").exists()
        assert not (root / ".update/ready.json").exists()
    finally:
        holder.kill()
        holder.wait(timeout=10)


def test_csharp_refuses_apply_without_ready_json(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    (root / ".update/ready.json").unlink()

    proc = run_helper(root, launcher_exe)

    assert proc.returncode == 1
    log = (root / ".update/apply.log").read_text(encoding="utf-8", errors="replace")
    assert "staging incomplete" in (root / ".update/failed.txt").read_text(encoding="utf-8"), log
    assert not (root / ".update/apply.plan").exists()
    assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "old-python"
    assert (root / "main.py").read_text(encoding="utf-8") == "old-main"


def test_launcher_mode_discards_staging_without_ready_json(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    (root / ".update/ready.json").unlink()

    proc = subprocess.run([str(root / "Wafer.exe")], cwd=root, timeout=25, capture_output=True)

    assert proc.returncode == 1
    assert "staging incomplete" in (root / ".update/failed.txt").read_text(encoding="utf-8")
    assert not (root / ".update/apply.plan").exists()
    assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "old-python"


def test_launcher_mode_hands_off_to_staged_helper(tmp_path, launcher_exe):
    root = tmp_path / "app"
    build_tree(root, launcher_exe)
    shutil.copy(launcher_exe, root / ".update/next/Wafer.exe")

    env = dict(os.environ, WAFER_UPDATE_WAIT_SECONDS="10")
    proc = subprocess.run([str(root / "Wafer.exe")], cwd=root, env=env, timeout=25, capture_output=True)
    assert proc.returncode == 0

    applied = root / ".update/applied.txt"
    deadline = time.monotonic() + 20
    while not applied.exists() and time.monotonic() < deadline:
        time.sleep(0.2)
    log_path = root / ".update/apply.log"
    log = log_path.read_text(encoding="utf-8", errors="replace") if log_path.exists() else "<no log>"
    assert applied.exists(), log
    assert applied.read_text(encoding="utf-8") == "2.0.0", log
    assert "helper" in log
    assert (root / "python/wafer-pythonw.exe").read_text(encoding="utf-8") == "new-python"
    assert (root / "main.py").read_text(encoding="utf-8") == "new-main"
    assert not (root / ".update/apply.plan").exists()
    assert not (root / ".update/ready.json").exists()

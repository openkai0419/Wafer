import os
import sys
import pytest
import psutil
from wafer.core.platform.process import ProcessMatcher, AppProcess


def test_process_matcher_empty_cmd_raises():
    with pytest.raises(ValueError):
        ProcessMatcher([])


def test_normalize_path():
    result = ProcessMatcher._normalize_path(sys.executable)
    assert os.path.isabs(result)


def test_same_executable_self():
    assert ProcessMatcher._same_executable(
        sys.executable,
        ProcessMatcher._normalize_path(sys.executable),
    )


def test_same_executable_nonexistent():
    assert not ProcessMatcher._same_executable(
        "/nonexistent/path",
        ProcessMatcher._normalize_path(sys.executable),
    )


def test_find_by_args_subset_self():
    matcher = ProcessMatcher([sys.executable])
    procs = matcher.find_by_args_subset()
    pids = [p.pid for p in procs]
    assert os.getpid() in pids


def test_find_by_args_exact_with_impossible_args():
    matcher = ProcessMatcher([sys.executable, "--impossible-flag-xyz"])
    procs = matcher.find_by_args_exact()
    assert len(procs) == 0


def test_app_process_base_command():
    cmd = AppProcess.base_command()
    assert len(cmd) >= 1
    exe_dir = os.path.dirname(sys.executable)
    assert os.path.dirname(cmd[0]) == exe_dir


def test_app_process_children():
    children = AppProcess.children()
    assert isinstance(children, list)


def test_app_process_terminate_empty():
    AppProcess.terminate([])


def test_app_process_terminate_and_wait_empty():
    AppProcess.terminate_and_wait([])


def test_app_process_terminate_and_wait_kills_process():
    import subprocess
    import time

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ps = psutil.Process(proc.pid)
        AppProcess.terminate_and_wait([ps], timeout=3, kill_timeout=2)
        proc.wait(timeout=3)
        assert proc.returncode is not None
    finally:
        try:
            proc.kill()
        except OSError:
            pass


def test_app_process_terminate_tree_kills_descendants():
    import subprocess
    import time

    code = (
        "import subprocess, sys, time; "
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']); "
        "print(child.pid, flush=True); "
        "time.sleep(60)"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", code],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    child_pid = int(proc.stdout.readline().strip())
    try:
        ps = psutil.Process(proc.pid)
        assert psutil.pid_exists(child_pid)
        AppProcess.terminate_tree([ps], timeout=3, kill_timeout=2)
        time.sleep(0.3)
        assert not psutil.pid_exists(child_pid)
    finally:
        for pid in (child_pid, proc.pid):
            if psutil.pid_exists(pid):
                try:
                    psutil.Process(pid).kill()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass


def test_app_process_shutdown_children():
    AppProcess.shutdown_children()

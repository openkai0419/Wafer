import os
import sys
import subprocess
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


def test_same_executable_cross_interpreter_rejected():
    # After the venv-redirector fix every process runs under the same real
    # interpreter, so matching is strict: distinct interpreters do NOT match.
    venv_pythonw = r"F:\proj\.venv\Scripts\pythonw.exe"
    base_pythonw = r"C:\Python311\pythonw.exe"
    assert not ProcessMatcher._same_executable(
        venv_pythonw, ProcessMatcher._normalize_path(base_pythonw)
    )


def test_same_executable_portable_identical_exe():
    portable = r"C:\App\python\wafer-pythonw.exe"
    assert ProcessMatcher._same_executable(
        portable, ProcessMatcher._normalize_path(portable)
    )


def test_find_by_args_subset_self():
    matcher = ProcessMatcher([AppProcess.base_command()[0]])
    procs = matcher.find_by_args_subset()
    pids = [p.pid for p in procs]
    assert os.getpid() in pids


def test_find_by_args_exact_with_impossible_args():
    matcher = ProcessMatcher([sys.executable, "--impossible-flag-xyz"])
    procs = matcher.find_by_args_exact()
    assert len(procs) == 0


class _FakeProc:
    def __init__(self, pid, cmdline):
        self.pid = pid
        self.info = {"pid": pid, "cmdline": cmdline}


def test_find_by_args_subset_matches_relative_script(monkeypatch):
    # The user-launched root process has a relative "main.py" in its cmdline
    # (dev: `python main.py`), while base_command() uses the absolute path.
    # ProcessMatcher must normalize the script path so both still match,
    # otherwise force_close_all()/list_viewers() silently miss the root viewer.
    abs_script = os.path.abspath("main.py")
    fake = _FakeProc(4321, [sys.executable, "main.py", "--viewer"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [fake])
    matcher = ProcessMatcher([sys.executable, abs_script])
    procs = matcher.find_by_args_subset()
    assert [p.pid for p in procs] == [4321]


def test_find_by_args_subset_rejects_different_script(monkeypatch):
    abs_script = os.path.abspath("main.py")
    fake = _FakeProc(9999, [sys.executable, "other_entry.py", "--viewer"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [fake])
    matcher = ProcessMatcher([sys.executable, abs_script])
    assert matcher.find_by_args_subset() == []


def test_find_by_args_subset_matches_portable_absolute_script(monkeypatch):
    # Portable (exe) launch: the Wafer.exe launcher runs
    # `wafer-pythonw.exe <appRoot>\main.py ...`, so cmdline[1] is already an
    # absolute path. Matching must still succeed (and stays robust with the
    # script-path normalization).
    exe = r"C:\App\python\wafer-pythonw.exe"
    script = r"C:\App\main.py"
    fake = _FakeProc(4321, [exe, script, "--viewer"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [fake])
    matcher = ProcessMatcher([exe, script])
    assert [p.pid for p in matcher.find_by_args_subset()] == [4321]


@pytest.mark.skipif(os.name != "nt", reason="Windows path normalization")
def test_find_by_args_subset_matches_windows_case_and_separator(monkeypatch):
    # Portable installs under paths like "C:\Program Files\Wafer" can surface
    # in psutil cmdline with different casing or forward slashes than
    # base_command()'s abspath. Normalization must absorb both.
    exe = r"C:\App\python\wafer-pythonw.exe"
    fake = _FakeProc(4321, [exe.lower(), "c:/app/MAIN.py", "--viewer"])
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: [fake])
    matcher = ProcessMatcher([exe, r"C:\App\main.py"])
    assert [p.pid for p in matcher.find_by_args_subset()] == [4321]


def test_list_viewers_captures_relative_root_and_excludes_workers(monkeypatch):
    # End-to-end guard for the reported bug: a dev root viewer launched with a
    # relative "main.py" must be enumerated by list_viewers(), while tray and
    # worker processes are excluded by WORKER_FLAGS.
    exe = sys.executable
    abs_script = os.path.abspath("main.py")
    monkeypatch.setattr(AppProcess, "base_command", staticmethod(lambda: [exe, abs_script]))
    root_viewer = _FakeProc(101, [exe, "main.py"])
    child_viewer = _FakeProc(102, [exe, abs_script, "--viewer", "--slot", "s1"])
    tray = _FakeProc(201, [exe, abs_script, "--tray"])
    indexer = _FakeProc(202, [exe, abs_script, "--indexer", "lib"])
    monkeypatch.setattr(
        psutil, "process_iter",
        lambda attrs=None: [root_viewer, child_viewer, tray, indexer],
    )
    pids = sorted(p.pid for p in AppProcess.list_viewers(exclude_self=False))
    assert pids == [101, 102]


def test_list_app_captures_relative_root_viewer(monkeypatch):
    exe = sys.executable
    abs_script = os.path.abspath("main.py")
    monkeypatch.setattr(AppProcess, "base_command", staticmethod(lambda: [exe, abs_script]))
    root_viewer = _FakeProc(101, [exe, "main.py"])
    tray = _FakeProc(201, [exe, abs_script, "--tray"])
    monkeypatch.setattr(
        psutil, "process_iter",
        lambda attrs=None: [root_viewer, tray],
    )
    pids = sorted(p.pid for p in AppProcess.list_app(exclude_self=False))
    assert pids == [101, 201]


def test_app_process_base_command():
    cmd = AppProcess.base_command()
    assert len(cmd) == 2
    assert os.path.isfile(cmd[0])
    assert cmd[1] == os.path.abspath(sys.argv[0])


def test_base_command_prefers_base_executable_in_venv(monkeypatch):
    monkeypatch.setattr(sys, "executable", r"X:\proj\.venv\Scripts\pythonw.exe", raising=False)
    monkeypatch.setattr(sys, "_base_executable", r"X:\Python311\pythonw.exe", raising=False)
    monkeypatch.setattr(sys, "prefix", r"X:\proj\.venv", raising=False)
    monkeypatch.setattr(sys, "base_prefix", r"X:\Python311", raising=False)
    cmd = AppProcess.base_command()
    assert cmd[0] == r"X:\Python311\pythonw.exe"


def test_base_command_uses_sys_executable_when_not_in_venv(monkeypatch):
    portable = r"X:\app\python\wafer-pythonw.exe"
    monkeypatch.setattr(sys, "executable", portable, raising=False)
    monkeypatch.setattr(sys, "_base_executable", portable, raising=False)
    monkeypatch.setattr(sys, "prefix", r"X:\app\python", raising=False)
    monkeypatch.setattr(sys, "base_prefix", r"X:\app\python", raising=False)
    cmd = AppProcess.base_command()
    assert cmd[0] == portable


def test_new_main_sets_pyvenv_launcher_in_venv(monkeypatch):
    captured = {}
    monkeypatch.setattr(sys, "prefix", r"X:\proj\.venv", raising=False)
    monkeypatch.setattr(sys, "base_prefix", r"X:\Python311", raising=False)
    monkeypatch.setattr(sys, "executable", r"X:\proj\.venv\Scripts\pythonw.exe", raising=False)
    monkeypatch.setattr(AppProcess, "base_command", staticmethod(lambda: ["exe", "main.py"]))

    class _P:
        pid = 123

    def fake_popen(cmd, env=None, **kw):
        captured["env"] = env
        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    AppProcess.new_main("--tray")
    assert captured["env"]["__PYVENV_LAUNCHER__"] == r"X:\proj\.venv\Scripts\pythonw.exe"


def test_new_main_no_pyvenv_launcher_when_not_in_venv(monkeypatch):
    captured = {}
    monkeypatch.setattr(sys, "prefix", r"X:\app\python", raising=False)
    monkeypatch.setattr(sys, "base_prefix", r"X:\app\python", raising=False)
    monkeypatch.setattr(AppProcess, "base_command", staticmethod(lambda: ["exe", "main.py"]))

    class _P:
        pid = 123

    def fake_popen(cmd, env=None, **kw):
        captured["env"] = env
        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    AppProcess.new_main("--tray")
    assert "__PYVENV_LAUNCHER__" not in captured["env"]


def test_new_main_merges_extra_env(monkeypatch):
    captured = {}
    monkeypatch.setattr(sys, "prefix", r"X:\app\python", raising=False)
    monkeypatch.setattr(sys, "base_prefix", r"X:\app\python", raising=False)
    monkeypatch.setattr(AppProcess, "base_command", staticmethod(lambda: ["exe", "main.py"]))

    class _P:
        pid = 123

    def fake_popen(cmd, env=None, **kw):
        captured["env"] = env
        return _P()

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    AppProcess.new_main(extra_env={"WAFER_REPLACE_TRAY": "1"})
    assert captured["env"]["WAFER_REPLACE_TRAY"] == "1"


def test_app_process_children():
    children = AppProcess.children()
    assert isinstance(children, list)


def test_app_process_terminate_empty():
    AppProcess.terminate([])


def test_app_process_terminate_and_wait_empty():
    AppProcess.terminate_and_wait([])


def test_app_process_terminate_and_wait_delegates_to_wait_procs_then_kill(monkeypatch):
    calls = []
    processes = [object()]
    monkeypatch.setattr(
        AppProcess,
        "terminate",
        staticmethod(lambda procs: calls.append(("terminate", procs))),
    )
    monkeypatch.setattr(
        AppProcess,
        "wait_procs_then_kill",
        staticmethod(lambda procs, wait=5, kill_timeout=3: calls.append(("wait", procs, wait, kill_timeout))),
    )

    AppProcess.terminate_and_wait(processes, timeout=7, kill_timeout=2)

    assert calls == [
        ("terminate", processes),
        ("wait", processes, 7, 2),
    ]


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


def test_list_app_excludes_self():
    procs = AppProcess.list_app(exclude_self=True)
    assert os.getpid() not in [p.pid for p in procs]


def test_wait_procs_then_kill_empty():
    AppProcess.wait_procs_then_kill([])


def test_wait_procs_then_kill_force_kills_unresponsive():
    import subprocess

    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        ps = psutil.Process(proc.pid)
        AppProcess.wait_procs_then_kill([ps], wait=1, kill_timeout=2)
        proc.wait(timeout=3)
        assert proc.returncode is not None
    finally:
        try:
            proc.kill()
        except OSError:
            pass


def test_force_close_all_no_app_processes(monkeypatch):
    calls = {}
    monkeypatch.setattr(AppProcess, "list_app", classmethod(lambda cls, exclude_self=True: []))
    monkeypatch.setattr(
        AppProcess,
        "terminate_and_wait",
        staticmethod(lambda procs, timeout=5, kill_timeout=3: calls.setdefault("terminated", procs)),
    )
    count = AppProcess.force_close_all(timeout=1, kill_timeout=1)
    assert count == 0
    assert calls["terminated"] == []


def test_list_viewers_excludes_workers(monkeypatch):
    class _FakeProc:
        def __init__(self, pid, cmdline):
            self.pid = pid
            self.info = {"pid": pid, "cmdline": cmdline}

    exe, main = AppProcess.base_command()
    fakes = [
        _FakeProc(101, [exe, main]),
        _FakeProc(102, [exe, main, "--viewer", "--slot", "abc"]),
        _FakeProc(103, [exe, main, "--tray"]),
        _FakeProc(104, [exe, main, "--indexer", "db"]),
        _FakeProc(105, [exe, main, "--collector", "db"]),
        _FakeProc(106, [exe, main, "--parser", "db"]),
    ]
    monkeypatch.setattr(psutil, "process_iter", lambda attrs=None: iter(fakes))
    pids = sorted(p.pid for p in AppProcess.list_viewers(exclude_self=False))
    assert pids == [101, 102]



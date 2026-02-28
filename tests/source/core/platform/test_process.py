import os
import sys
import pytest
from source.core.platform.process import ProcessMatcher, AppProcess


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
    assert sys.executable in cmd[0] or os.path.samefile(cmd[0], sys.executable)


def test_app_process_children():
    children = AppProcess.children()
    assert isinstance(children, list)


def test_app_process_terminate_empty():
    AppProcess.terminate([])

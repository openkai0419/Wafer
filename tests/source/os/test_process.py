import os
import sys
import pytest
from source.os.process import ProcessMatcher, Proc


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


def test_find_subset_self():
    matcher = ProcessMatcher([sys.executable])
    procs = matcher.find_subset()
    pids = [p.pid for p in procs]
    assert os.getpid() in pids


def test_find_exact_with_impossible_args():
    matcher = ProcessMatcher([sys.executable, "--impossible-flag-xyz"])
    procs = matcher.find_exact()
    assert len(procs) == 0


def test_proc_cmd():
    cmd = Proc.cmd()
    assert len(cmd) >= 1
    assert sys.executable in cmd[0] or os.path.samefile(cmd[0], sys.executable)


def test_proc_children():
    children = Proc.children()
    assert isinstance(children, list)


def test_proc_terminate_empty():
    Proc.terminate([])

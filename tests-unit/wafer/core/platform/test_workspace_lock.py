import os
import subprocess
import sys
from pathlib import Path

import pytest

from wafer.core.platform import workspace_lock
from wafer.core.platform.workspace_lock import WorkspaceLock, WorkspaceOwner


@pytest.fixture(autouse=True)
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_lock, "resolve_temp_path", lambda name: str(tmp_path / name))
    return tmp_path / "workspaces"


def test_second_acquire_fails_while_held():
    first = WorkspaceLock.acquire("s1")
    assert first is not None
    assert WorkspaceLock.acquire("s1") is None
    first.release()
    again = WorkspaceLock.acquire("s1")
    assert again is not None
    again.release()


def test_acquire_exposes_slot_id():
    lock = WorkspaceLock.acquire("s1")
    assert lock.slot_id == "s1"
    lock.release()


def test_different_slots_are_independent():
    first = WorkspaceLock.acquire("a")
    second = WorkspaceLock.acquire("b")
    assert first is not None
    assert second is not None
    first.release()
    second.release()


def test_open_slot_ids_reports_only_held():
    held = WorkspaceLock.acquire("a")
    assert WorkspaceLock.open_slot_ids(["a", "b"]) == {"a"}
    held.release()
    assert WorkspaceLock.open_slot_ids(["a", "b"]) == set()


def test_open_slot_ids_does_not_keep_probed_locks():
    WorkspaceLock.open_slot_ids(["a"])
    lock = WorkspaceLock.acquire("a")
    assert lock is not None
    lock.release()


def test_read_owner_returns_window_after_set_window():
    lock = WorkspaceLock.acquire("s1")
    lock.set_window(4242)
    assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=os.getpid(), hwnd=4242)
    lock.release()


def test_read_owner_is_none_without_window():
    assert WorkspaceLock.read_owner("missing") is None


def test_read_owner_is_none_before_set_window():
    lock = WorkspaceLock.acquire("s1")
    assert WorkspaceLock.read_owner("s1") is None
    lock.release()


def test_read_owner_is_none_after_release():
    lock = WorkspaceLock.acquire("s1")
    lock.set_window(7)
    lock.release()
    assert WorkspaceLock.read_owner("s1") is None


def test_acquire_clears_stale_owner_from_crashed_process(lock_dir):
    lock_dir.mkdir()
    (lock_dir / "s1.lock").write_text('{"pid": 99999, "hwnd": 1234}')
    assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=99999, hwnd=1234)
    lock = WorkspaceLock.acquire("s1")
    assert lock is not None
    assert WorkspaceLock.read_owner("s1") is None
    lock.release()


def test_failed_acquire_keeps_owner_of_holder():
    lock = WorkspaceLock.acquire("s1")
    lock.set_window(321)
    assert WorkspaceLock.acquire("s1") is None
    assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=os.getpid(), hwnd=321)
    lock.release()


def test_read_owner_ignores_corrupt_file(lock_dir):
    lock_dir.mkdir()
    (lock_dir / "bad.lock").write_text("not json")
    assert WorkspaceLock.read_owner("bad") is None


def test_set_window_twice_keeps_latest():
    lock = WorkspaceLock.acquire("s1")
    lock.set_window(1234567)
    lock.set_window(9)
    assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=os.getpid(), hwnd=9)
    lock.release()


def test_release_twice_is_safe():
    lock = WorkspaceLock.acquire("s1")
    lock.release()
    lock.release()


def test_other_process_holds_lock_and_owner_is_readable(tmp_path):
    code = (
        "import os, sys\n"
        "from wafer.core.platform import workspace_lock\n"
        "workspace_lock.resolve_temp_path = lambda name: os.path.join(sys.argv[1], name)\n"
        "lock = workspace_lock.WorkspaceLock.acquire('s1')\n"
        "lock.set_window(555)\n"
        "print(os.getpid(), flush=True)\n"
        "sys.stdin.readline()\n"
    )
    child = subprocess.Popen(
        [sys.executable, "-c", code, str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        cwd=Path(__file__).parents[4],
    )
    try:
        child_pid = int(child.stdout.readline())
        assert WorkspaceLock.acquire("s1") is None
        assert WorkspaceLock.open_slot_ids(["s1"]) == {"s1"}
        assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=child_pid, hwnd=555)
    finally:
        child.communicate("\n", timeout=10)
    lock = WorkspaceLock.acquire("s1")
    assert lock is not None
    lock.release()


def test_delete_file_if_unused_removes_a_free_lock_file(lock_dir):
    WorkspaceLock.acquire("s1").release()
    assert (lock_dir / "s1.lock").exists()
    assert WorkspaceLock.delete_file_if_unused("s1") is True
    assert not (lock_dir / "s1.lock").exists()


def test_delete_file_if_unused_keeps_a_held_lock_file(lock_dir):
    lock = WorkspaceLock.acquire("s1")
    try:
        assert WorkspaceLock.delete_file_if_unused("s1") is False
        assert (lock_dir / "s1.lock").exists()
        assert WorkspaceLock.acquire("s1") is None
    finally:
        lock.release()


def test_delete_file_if_unused_without_a_file_creates_nothing(lock_dir):
    assert WorkspaceLock.delete_file_if_unused("s1") is False
    assert not lock_dir.exists()


def test_probing_a_slot_this_process_holds_keeps_its_lock_and_owner(monkeypatch):
    monkeypatch.setattr(workspace_lock, "lock_byte", lambda fd: None)
    monkeypatch.setattr(workspace_lock, "unlock_byte", lambda fd: None)
    held = WorkspaceLock.acquire("s1")
    held.set_window(77)
    try:
        assert WorkspaceLock.open_slot_ids(["s1"]) == {"s1"}
        assert WorkspaceLock.delete_file_if_unused("s1") is False
        assert WorkspaceLock.acquire("s1") is None
        assert WorkspaceLock.read_owner("s1") == WorkspaceOwner(pid=os.getpid(), hwnd=77)
    finally:
        held.release()
    assert WorkspaceLock.open_slot_ids(["s1"]) == set()

import os
import subprocess
import sys
from pathlib import Path

from wafer.core.platform.workspace_lock import WorkspaceLock, WorkspaceOwner


def test_second_acquire_fails_while_held(tmp_path):
    first = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert first is not None
    assert WorkspaceLock.acquire("s1", lock_dir=str(tmp_path)) is None
    first.release()
    again = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert again is not None
    again.release()


def test_acquire_exposes_slot_id(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert lock.slot_id == "s1"
    lock.release()


def test_different_slots_are_independent(tmp_path):
    first = WorkspaceLock.acquire("a", lock_dir=str(tmp_path))
    second = WorkspaceLock.acquire("b", lock_dir=str(tmp_path))
    assert first is not None
    assert second is not None
    first.release()
    second.release()


def test_open_slot_ids_reports_only_held(tmp_path):
    held = WorkspaceLock.acquire("a", lock_dir=str(tmp_path))
    assert WorkspaceLock.open_slot_ids(["a", "b"], lock_dir=str(tmp_path)) == {"a"}
    held.release()
    assert WorkspaceLock.open_slot_ids(["a", "b"], lock_dir=str(tmp_path)) == set()


def test_open_slot_ids_does_not_keep_probed_locks(tmp_path):
    WorkspaceLock.open_slot_ids(["a"], lock_dir=str(tmp_path))
    lock = WorkspaceLock.acquire("a", lock_dir=str(tmp_path))
    assert lock is not None
    lock.release()


def test_read_owner_returns_window_after_set_window(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    lock.set_window(4242)
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) == WorkspaceOwner(pid=os.getpid(), hwnd=4242)
    lock.release()


def test_read_owner_is_none_without_window(tmp_path):
    assert WorkspaceLock.read_owner("missing", lock_dir=str(tmp_path)) is None


def test_read_owner_is_none_before_set_window(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) is None
    lock.release()


def test_read_owner_is_none_after_release(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    lock.set_window(7)
    lock.release()
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) is None


def test_acquire_clears_stale_owner_from_crashed_process(tmp_path):
    (tmp_path / "s1.lock").write_text('{"pid": 99999, "hwnd": 1234}')
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) == WorkspaceOwner(pid=99999, hwnd=1234)
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert lock is not None
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) is None
    lock.release()


def test_failed_acquire_keeps_owner_of_holder(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    lock.set_window(321)
    assert WorkspaceLock.acquire("s1", lock_dir=str(tmp_path)) is None
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) == WorkspaceOwner(pid=os.getpid(), hwnd=321)
    lock.release()


def test_read_owner_ignores_corrupt_file(tmp_path):
    (tmp_path / "bad.lock").write_text("not json")
    assert WorkspaceLock.read_owner("bad", lock_dir=str(tmp_path)) is None


def test_set_window_twice_keeps_latest(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    lock.set_window(1234567)
    lock.set_window(9)
    assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) == WorkspaceOwner(pid=os.getpid(), hwnd=9)
    lock.release()


def test_release_twice_is_safe(tmp_path):
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    lock.release()
    lock.release()


def test_other_process_holds_lock_and_owner_is_readable(tmp_path):
    code = (
        "import sys\n"
        "from wafer.core.platform.workspace_lock import WorkspaceLock\n"
        "lock = WorkspaceLock.acquire('s1', lock_dir=sys.argv[1])\n"
        "lock.set_window(555)\n"
        "import os\n"
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
        assert WorkspaceLock.acquire("s1", lock_dir=str(tmp_path)) is None
        assert WorkspaceLock.open_slot_ids(["s1"], lock_dir=str(tmp_path)) == {"s1"}
        assert WorkspaceLock.read_owner("s1", lock_dir=str(tmp_path)) == WorkspaceOwner(pid=child_pid, hwnd=555)
    finally:
        child.communicate("\n", timeout=10)
    lock = WorkspaceLock.acquire("s1", lock_dir=str(tmp_path))
    assert lock is not None
    lock.release()


def test_default_lock_dir_is_under_temp_workspaces(tmp_path, monkeypatch):
    from wafer.core.platform import workspace_lock

    monkeypatch.setattr(workspace_lock, "resolve_temp_path", lambda name: str(tmp_path / name))
    lock = WorkspaceLock.acquire("s1")
    assert lock is not None
    assert (tmp_path / "workspaces" / "s1.lock").exists()
    lock.release()

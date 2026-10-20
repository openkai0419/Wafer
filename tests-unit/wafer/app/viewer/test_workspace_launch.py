import pytest

from wafer.app.viewer import workspace_launch
from wafer.core.platform.workspace_lock import WorkspaceLock
from wafer.core.store.workspace import WindowSlot, WorkspaceStore


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    path = str(tmp_path / "locks")
    monkeypatch.setattr(workspace_launch, "_lock_dir", lambda: path)
    return path


@pytest.fixture
def activated(monkeypatch):
    calls = []
    monkeypatch.setattr(workspace_launch, "activate_window", calls.append)
    return calls


def store_with_slot(monkeypatch, tmp_path, slot_id=None):
    store = WorkspaceStore(path=str(tmp_path / "workspace.json"))
    if slot_id:
        store.save_slot(WindowSlot(slot_id=slot_id))
    monkeypatch.setattr(WorkspaceStore, "_instance", store)
    return store


def test_claim_workspace_activates_owner_when_already_open(tmp_path, monkeypatch, lock_dir, activated):
    held = WorkspaceLock.acquire("s1", lock_dir=lock_dir)
    held.set_window(77)
    store_with_slot(monkeypatch, tmp_path, "s1")
    try:
        assert workspace_launch.claim_workspace("s1") is None
        assert activated == [77]
    finally:
        held.release()


def test_claim_workspace_skips_activation_when_owner_has_no_window_yet(tmp_path, monkeypatch, lock_dir, activated):
    held = WorkspaceLock.acquire("s1", lock_dir=lock_dir)
    store_with_slot(monkeypatch, tmp_path, "s1")
    try:
        assert workspace_launch.claim_workspace("s1") is None
        assert activated == []
    finally:
        held.release()


def test_claim_workspace_locks_a_known_free_slot(tmp_path, monkeypatch, lock_dir, activated):
    store_with_slot(monkeypatch, tmp_path, "s1")
    lock = workspace_launch.claim_workspace("s1")
    try:
        assert lock.slot_id == "s1"
        assert WorkspaceLock.open_slot_ids(["s1"], lock_dir=lock_dir) == {"s1"}
        assert activated == []
    finally:
        lock.release()


def test_claim_workspace_creates_slot_for_none(tmp_path, monkeypatch, lock_dir):
    store = store_with_slot(monkeypatch, tmp_path, "s1")
    lock = workspace_launch.claim_workspace(None)
    try:
        assert lock.slot_id != "s1"
        assert store.get_slot(lock.slot_id) is not None
    finally:
        lock.release()


def test_claim_workspace_creates_slot_instead_of_adopting_unknown_id(tmp_path, monkeypatch, lock_dir):
    store = store_with_slot(monkeypatch, tmp_path)
    lock = workspace_launch.claim_workspace("ghost")
    try:
        assert lock.slot_id != "ghost"
        assert store.get_slot("ghost") is None
        assert store.get_slot(lock.slot_id) is not None
    finally:
        lock.release()


def test_lock_dir_uses_the_default_location():
    assert workspace_launch._lock_dir() is None

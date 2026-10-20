import pytest

from wafer.app.viewer import workspace_launch
from wafer.app.viewer.widgets.workspace_picker import PickResult
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


class Viewed(Exception):
    pass


@pytest.fixture
def pick_flow(tmp_path, monkeypatch, lock_dir):
    store = store_with_slot(monkeypatch, tmp_path, "seed")
    flow = {"store": store, "claimed": [], "asked": [], "answer": None, "lock": None}

    def ask(slots, open_ids, **kwargs):
        flow["asked"].append((slots, open_ids, kwargs))
        return flow["answer"]

    def claim(slot_id):
        flow["claimed"].append(slot_id)
        return flow["lock"]

    def run_viewer(app, lock):
        raise Viewed(lock)

    monkeypatch.setattr(workspace_launch.WorkspacePickerDialog, "ask", staticmethod(ask))
    monkeypatch.setattr(workspace_launch, "claim_workspace", claim)
    monkeypatch.setattr(workspace_launch, "run_viewer", run_viewer)
    return flow


def test_run_pick_cancel_exits_without_creating(pick_flow):
    with pytest.raises(SystemExit) as exit_info:
        workspace_launch.run_pick(object(), "seed")
    assert exit_info.value.code == 0
    assert pick_flow["claimed"] == []
    assert [s.slot_id for s in pick_flow["store"].list_slots()] == ["seed"]


def test_run_pick_asks_with_open_slots_disabled(pick_flow, lock_dir):
    held = WorkspaceLock.acquire("seed", lock_dir=lock_dir)
    try:
        with pytest.raises(SystemExit):
            workspace_launch.run_pick(object(), "seed")
    finally:
        held.release()
    slots, open_ids, kwargs = pick_flow["asked"][0]
    assert [s.slot_id for s in slots] == ["seed"]
    assert open_ids == {"seed"}
    assert kwargs == {"allow_open": False, "databases": []}


def test_run_pick_new_seeds_from_caller(pick_flow):
    pick_flow["answer"] = PickResult(None, "")
    pick_flow["lock"] = "lock"
    with pytest.raises(Viewed):
        workspace_launch.run_pick(object(), "seed")
    new_ids = [s.slot_id for s in pick_flow["store"].list_slots() if s.slot_id != "seed"]
    assert len(new_ids) == 1
    assert pick_flow["claimed"] == new_ids


def test_run_pick_existing_claims_it(pick_flow):
    pick_flow["answer"] = PickResult("seed", "")
    pick_flow["lock"] = "lock"
    with pytest.raises(Viewed):
        workspace_launch.run_pick(object(), "other")
    assert pick_flow["claimed"] == ["seed"]
    assert len(pick_flow["store"].list_slots()) == 1


def test_run_pick_exits_when_claim_fails(pick_flow):
    pick_flow["answer"] = PickResult("seed", "")
    with pytest.raises(SystemExit) as exit_info:
        workspace_launch.run_pick(object(), "other")
    assert exit_info.value.code == 0

import pytest

from wafer.app.viewer import workspace_launch
from wafer.app.viewer.widgets.workspace_picker import PickResult
from wafer.core.common.paths import normalize_path
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


def test_run_pick_new_without_seed_uses_the_latest_slot(pick_flow, monkeypatch):
    seeds = []
    create = pick_flow["store"].create_slot_from
    monkeypatch.setattr(pick_flow["store"], "create_slot_from", lambda seed: seeds.append(seed) or create(seed))
    pick_flow["answer"] = PickResult(None, "")
    pick_flow["lock"] = "lock"
    with pytest.raises(Viewed):
        workspace_launch.run_pick(object(), None)
    assert seeds == ["seed"]


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


def test_slots_to_restore_skips_chosen():
    assert workspace_launch.slots_to_restore(["a", "b", "c"], "b") == ["a", "c"]
    assert workspace_launch.slots_to_restore(["a"], None) == ["a"]


def test_openable_path_accepts_files_only(tmp_path, monkeypatch):
    warnings = []
    monkeypatch.setattr(workspace_launch.AppLogger, "warning", lambda message, **kwargs: warnings.append(message))
    file_path = tmp_path / "a.png"
    file_path.write_bytes(b"x")
    assert workspace_launch.is_openable_path(str(file_path)) is True
    assert warnings == []
    for path in (str(tmp_path), str(tmp_path / "missing.png"), "", None):
        assert workspace_launch.is_openable_path(path) is False
    assert len(warnings) == 4


def test_restore_session_spawns_other_slots_and_webui(tmp_path, monkeypatch):
    store = store_with_slot(monkeypatch, tmp_path, "a")
    store.save_slot(WindowSlot(slot_id="b"))
    store.set_restore_slot_ids(["a", "b"])
    store.set_restore_webui(True)
    spawned = []
    monkeypatch.setattr(workspace_launch.AppProcess, "new_main", lambda *args: spawned.append(args))
    workspace_launch.restore_session("a")
    assert spawned == [("--viewer", "--slot", "b"), ("--webui", "--no-browser")]
    assert store.get_restore_webui() is False


def test_restore_session_without_skip_spawns_every_slot(tmp_path, monkeypatch):
    store = store_with_slot(monkeypatch, tmp_path, "a")
    store.set_restore_slot_ids(["a"])
    spawned = []
    monkeypatch.setattr(workspace_launch.AppProcess, "new_main", lambda *args: spawned.append(args))
    workspace_launch.restore_session(None)
    assert spawned == [("--viewer", "--slot", "a")]


class FakeNode:
    def __init__(self, role, flow):
        self.role = role
        self.flow = flow
        self.events = []
        flow["nodes"].append(self)

    def start(self):
        self.events.append("start")

    def wait_registered(self, timeout):
        self.events.append(("wait_registered", timeout))
        return self.flow["registered"]

    def request(self, topic, payload, *, dst, timeout):
        self.events.append(("request", topic, payload, dst, timeout))
        return self.flow["reply"]

    def stop(self):
        self.events.append("stop")


@pytest.fixture
def open_flow(tmp_path, monkeypatch, lock_dir, activated):
    store = store_with_slot(monkeypatch, tmp_path, "s1")
    store.save_slot(WindowSlot(slot_id="s2", name="Second"))
    file_path = tmp_path / "a.png"
    file_path.write_bytes(b"x")
    flow = {
        "store": store,
        "path": str(file_path),
        "asked": [],
        "answer": None,
        "databases": [],
        "claimed": [],
        "restored": [],
        "nodes": [],
        "registered": True,
        "reply": None,
        "warnings": [],
        "activated": activated,
    }

    def ask(slots, open_ids, **kwargs):
        flow["asked"].append((slots, open_ids, kwargs))
        return flow["answer"]

    def claim(slot_id):
        flow["claimed"].append(slot_id)
        return "lock"

    def run_viewer(app, lock, **kwargs):
        raise Viewed(kwargs)

    monkeypatch.setattr(workspace_launch.WorkspacePickerDialog, "ask", staticmethod(ask))
    monkeypatch.setattr(workspace_launch, "claim_workspace", claim)
    monkeypatch.setattr(workspace_launch, "run_viewer", run_viewer)
    monkeypatch.setattr(workspace_launch, "restore_session", flow["restored"].append)
    monkeypatch.setattr(workspace_launch, "databases_containing", lambda path: flow["databases"])
    monkeypatch.setattr(workspace_launch, "Node", lambda role: FakeNode(role, flow))
    monkeypatch.setattr(workspace_launch.AppLogger, "warning", lambda message, **kwargs: flow["warnings"].append(message))
    return flow


def opened_request(viewed):
    return viewed.value.args[0]["open_request"]


def run_open_path_with_open_slot(flow, lock_dir, slot_id="s2"):
    held = WorkspaceLock.acquire(slot_id, lock_dir=lock_dir)
    held.set_window(77)
    try:
        with pytest.raises(SystemExit) as exit_info:
            workspace_launch.run_open_path(object(), flow["path"])
    finally:
        held.release()
    return exit_info.value.code


def test_running_and_open_choice_sends_request_and_activates(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    open_flow["reply"] = object()
    assert run_open_path_with_open_slot(open_flow, lock_dir) == 0
    node = open_flow["nodes"][0]
    assert node.role == "launcher"
    payload = {"slot_id": "s2", "path": normalize_path(open_flow["path"]), "database_name": ""}
    assert node.events == ["start", ("wait_registered", 5), ("request", "slot.open_path", payload, "viewer", 5), "stop"]
    assert open_flow["activated"] == [77]
    assert open_flow["claimed"] == []
    assert open_flow["restored"] == []


def test_open_choice_without_reply_warns_and_exits(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path_with_open_slot(open_flow, lock_dir) == 0
    assert len(open_flow["warnings"]) == 1
    assert "Second" in open_flow["warnings"][0]
    assert open_flow["nodes"][0].events[-1] == "stop"
    assert open_flow["activated"] == []
    assert open_flow["claimed"] == []


def test_open_choice_without_broker_warns_without_requesting(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    open_flow["registered"] = False
    assert run_open_path_with_open_slot(open_flow, lock_dir) == 0
    assert open_flow["nodes"][0].events == ["start", ("wait_registered", 5), "stop"]
    assert len(open_flow["warnings"]) == 1
    assert open_flow["activated"] == []


def test_running_and_closed_choice_opens_a_window_without_restoring(open_flow, lock_dir):
    held = WorkspaceLock.acquire("s2", lock_dir=lock_dir)
    open_flow["answer"] = PickResult("s1", "")
    try:
        with pytest.raises(Viewed) as viewed:
            workspace_launch.run_open_path(object(), open_flow["path"])
    finally:
        held.release()
    assert open_flow["asked"][0][1] == {"s2"}
    assert open_flow["claimed"] == ["s1"]
    assert open_flow["restored"] == []
    assert open_flow["nodes"] == []
    assert opened_request(viewed) == workspace_launch.OpenRequest(normalize_path(open_flow["path"]), "")


def test_not_running_marks_restore_ids_open_and_restores_others(open_flow):
    open_flow["store"].set_restore_slot_ids(["s1", "s2"])
    open_flow["answer"] = PickResult("s2", "")
    with pytest.raises(Viewed):
        workspace_launch.run_open_path(object(), open_flow["path"])
    slots, open_ids, kwargs = open_flow["asked"][0]
    assert open_ids == {"s1", "s2"}
    assert kwargs["allow_open"] is True
    assert open_flow["restored"] == ["s2"]
    assert open_flow["claimed"] == ["s2"]
    assert open_flow["nodes"] == []


def test_cancel_opens_nothing(open_flow):
    open_flow["store"].set_restore_slot_ids(["s1"])
    with pytest.raises(SystemExit) as exit_info:
        workspace_launch.run_open_path(object(), open_flow["path"])
    assert exit_info.value.code == 0
    assert open_flow["restored"] == []
    assert open_flow["claimed"] == []
    assert open_flow["nodes"] == []
    assert len(open_flow["store"].list_slots()) == 2


def test_new_from_path_seeds_from_latest_slot(open_flow, monkeypatch):
    store = open_flow["store"]
    seeds = []
    create = store.create_slot_from
    monkeypatch.setattr(store, "create_slot_from", lambda seed: seeds.append(seed) or create(seed))
    latest = store.latest_slot_id()
    open_flow["answer"] = PickResult(None, "")
    with pytest.raises(Viewed):
        workspace_launch.run_open_path(object(), open_flow["path"])
    assert seeds == [latest]
    new_id = open_flow["claimed"][0]
    assert new_id not in ("s1", "s2")
    assert open_flow["restored"] == [new_id]


def test_single_database_is_used_without_choice(open_flow):
    open_flow["databases"] = ["a"]
    open_flow["answer"] = PickResult("s1", "")
    with pytest.raises(Viewed) as viewed:
        workspace_launch.run_open_path(object(), open_flow["path"])
    assert open_flow["asked"][0][2] == {"allow_open": True, "databases": []}
    assert opened_request(viewed) == workspace_launch.OpenRequest(normalize_path(open_flow["path"]), "a")


def test_multiple_databases_offer_a_choice(open_flow):
    open_flow["databases"] = ["a", "b"]
    open_flow["answer"] = PickResult("s1", "b")
    with pytest.raises(Viewed) as viewed:
        workspace_launch.run_open_path(object(), open_flow["path"])
    assert open_flow["asked"][0][2] == {"allow_open": True, "databases": ["a", "b"]}
    assert opened_request(viewed).database_name == "b"


def test_run_viewer_passes_the_open_request_to_the_window(monkeypatch):
    created = []

    class FakeWindow:
        def __init__(self, icon, **kwargs):
            created.append(kwargs)

        def show(self):
            pass

    class FakeApp:
        def exec(self):
            return 0

    monkeypatch.setattr("wafer.app.viewer.mainwindow.MainWindow", FakeWindow)
    monkeypatch.setattr(workspace_launch, "get_icon", lambda: "icon")
    request = workspace_launch.OpenRequest("C:/a.png", "db")
    with pytest.raises(SystemExit):
        workspace_launch.run_viewer(FakeApp(), "lock", open_request=request)
    assert created == [{"workspace_lock": "lock", "open_request": request}]

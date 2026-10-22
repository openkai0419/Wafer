from types import SimpleNamespace

import pytest

from wafer.app.viewer import workspace_launch
from wafer.app.viewer.widgets.workspace_picker import PickResult
from wafer.core.common.paths import normalize_path
from wafer.core.lang.manager import t
from wafer.core.platform import workspace_lock
from wafer.core.platform.workspace_lock import WorkspaceLock
from wafer.core.store.workspace import WindowSlot, WorkspaceStore


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace_lock, "resolve_temp_path", lambda name: str(tmp_path / name))
    return tmp_path / "workspaces"


@pytest.fixture(autouse=True)
def retry_waits(monkeypatch):
    waits = []
    monkeypatch.setattr(workspace_launch, "sleep", waits.append)
    return waits


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


def test_claim_workspace_activates_owner_when_already_open(tmp_path, monkeypatch, lock_dir, activated, retry_waits):
    held = WorkspaceLock.acquire("s1")
    held.set_window(77)
    store_with_slot(monkeypatch, tmp_path, "s1")
    try:
        assert workspace_launch.claim_workspace("s1") is None
        assert activated == [77]
        assert retry_waits == []
    finally:
        held.release()


def test_claim_workspace_gives_up_when_the_owner_never_shows_a_window(tmp_path, monkeypatch, lock_dir, activated, retry_waits):
    held = WorkspaceLock.acquire("s1")
    store_with_slot(monkeypatch, tmp_path, "s1")
    try:
        assert workspace_launch.claim_workspace("s1") is None
        assert activated == []
        assert retry_waits == [workspace_launch.CLAIM_RETRY_INTERVAL] * workspace_launch.CLAIM_RETRIES
    finally:
        held.release()


def test_claim_workspace_retries_while_a_status_probe_holds_the_lock(tmp_path, monkeypatch, lock_dir, activated, retry_waits):
    probe = WorkspaceLock.acquire("s1")
    store_with_slot(monkeypatch, tmp_path, "s1")
    monkeypatch.setattr(workspace_launch, "sleep", lambda seconds: retry_waits.append(seconds) or probe.release())
    lock = workspace_launch.claim_workspace("s1")
    try:
        assert lock is not None
        assert lock.slot_id == "s1"
        assert retry_waits == [workspace_launch.CLAIM_RETRY_INTERVAL]
        assert activated == []
    finally:
        lock.release()


def test_claim_workspace_stops_retrying_once_the_owner_shows_its_window(tmp_path, monkeypatch, lock_dir, activated, retry_waits):
    held = WorkspaceLock.acquire("s1")
    store_with_slot(monkeypatch, tmp_path, "s1")
    monkeypatch.setattr(workspace_launch, "sleep", lambda seconds: retry_waits.append(seconds) or held.set_window(88))
    try:
        assert workspace_launch.claim_workspace("s1") is None
        assert activated == [88]
        assert len(retry_waits) == 1
    finally:
        held.release()


def test_activate_workspace_window_brings_the_owner_forward(lock_dir, activated):
    held = WorkspaceLock.acquire("s1")
    try:
        assert workspace_launch.activate_workspace_window("s1") is False
        held.set_window(55)
        assert workspace_launch.activate_workspace_window("s1") is True
        assert activated == [55]
    finally:
        held.release()


def test_claim_workspace_locks_a_known_free_slot(tmp_path, monkeypatch, lock_dir, activated):
    store_with_slot(monkeypatch, tmp_path, "s1")
    lock = workspace_launch.claim_workspace("s1")
    try:
        assert lock.slot_id == "s1"
        assert WorkspaceLock.open_slot_ids(["s1"]) == {"s1"}
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
    pick_flow["store"].save_slot(WindowSlot(slot_id="closed"))
    held = WorkspaceLock.acquire("seed")
    try:
        with pytest.raises(SystemExit):
            workspace_launch.run_pick(object(), "seed")
    finally:
        held.release()
    slots, open_ids, kwargs = pick_flow["asked"][0]
    assert sorted(s.slot_id for s in slots) == ["closed", "seed"]
    assert open_ids == {"seed"}
    assert kwargs == {"allow_open": False, "databases": []}


def test_run_pick_opens_a_new_workspace_without_asking_when_every_workspace_is_open(pick_flow, lock_dir, monkeypatch):
    seeds = []
    create = pick_flow["store"].create_slot_from
    monkeypatch.setattr(pick_flow["store"], "create_slot_from", lambda seed: seeds.append(seed) or create(seed))
    pick_flow["lock"] = "lock"
    held = WorkspaceLock.acquire("seed")
    try:
        with pytest.raises(Viewed):
            workspace_launch.run_pick(object(), "seed")
    finally:
        held.release()
    assert pick_flow["asked"] == []
    assert seeds == ["seed"]
    new_ids = [s.slot_id for s in pick_flow["store"].list_slots() if s.slot_id != "seed"]
    assert pick_flow["claimed"] == new_ids


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
        "spawned": [],
        "allowed": [],
        "nodes": [],
        "registered": True,
        "reply": None,
        "warnings": [],
        "dialogs": [],
        "activated": activated,
        "events": [],
    }

    def ask(slots, open_ids, **kwargs):
        flow["events"].append("ask")
        flow["asked"].append((slots, open_ids, kwargs))
        return flow["answer"]

    def run_viewer(app, lock, **kwargs):
        raise Viewed(kwargs)

    monkeypatch.setattr(workspace_launch, "VIEWER_REJOIN_SECONDS", 0)
    monkeypatch.setattr(workspace_launch.WorkspacePickerDialog, "ask", staticmethod(ask))
    monkeypatch.setattr(workspace_launch, "claim_workspace", flow["claimed"].append)
    monkeypatch.setattr(workspace_launch, "run_viewer", run_viewer)
    monkeypatch.setattr(workspace_launch, "restore_session", flow["restored"].append)
    def spawn(slot_id, request=None):
        flow["spawned"].append((slot_id, request))
        return SimpleNamespace(pid=1000 + len(flow["spawned"]))

    monkeypatch.setattr(workspace_launch, "spawn_viewer", spawn)
    monkeypatch.setattr(workspace_launch, "wait_for_pending_install", lambda app: flow["events"].append("install"))
    monkeypatch.setattr(workspace_launch, "allow_foreground", flow["allowed"].append)
    monkeypatch.setattr(workspace_launch, "databases_containing", lambda path: flow["databases"])
    monkeypatch.setattr(workspace_launch, "Node", lambda role: FakeNode(role, flow))
    monkeypatch.setattr(workspace_launch.AppLogger, "warning", lambda message, **kwargs: flow["warnings"].append(message))
    monkeypatch.setattr(workspace_launch.QtWidgets.QMessageBox, "warning", lambda *args: flow["dialogs"].append(args))
    return flow


def run_open_path(flow, held_slot_id=None):
    held = WorkspaceLock.acquire(held_slot_id) if held_slot_id else None
    if held is not None:
        held.set_window(77)
    try:
        with pytest.raises(SystemExit) as exit_info:
            workspace_launch.run_open_path(object(), flow["path"])
    finally:
        if held is not None:
            held.release()
    assert flow["claimed"] == []
    return exit_info.value.code


def request_for(flow, database_name=""):
    return workspace_launch.OpenRequest(normalize_path(flow["path"]), database_name)


def test_running_and_open_choice_sends_request_and_activates(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    open_flow["reply"] = object()
    assert run_open_path(open_flow, "s2") == 0
    node = open_flow["nodes"][0]
    assert node.role == "launcher"
    payload = {"slot_id": "s2", "path": normalize_path(open_flow["path"]), "database_name": ""}
    request = ("request", "slot.open_path", payload, "viewer", workspace_launch.OPEN_PATH_ATTEMPT_TIMEOUT)
    assert node.events == ["start", ("wait_registered", 5), request, "stop"]
    assert open_flow["activated"] == [77]
    assert open_flow["spawned"] == []
    assert open_flow["allowed"] == []
    assert open_flow["restored"] == []
    assert open_flow["dialogs"] == []


def test_open_request_is_resent_until_the_workspace_rejoins(open_flow, lock_dir, monkeypatch):
    replies = iter([None, None, object()])
    monkeypatch.setattr(FakeNode, "request", lambda self, *a, **k: self.events.append("request") or next(replies))
    monkeypatch.setattr(workspace_launch, "VIEWER_REJOIN_SECONDS", 60)
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path(open_flow, "s2") == 0
    assert open_flow["nodes"][0].events.count("request") == 3
    assert open_flow["activated"] == [77]
    assert open_flow["dialogs"] == []


def test_open_choice_without_reply_warns_and_exits(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path(open_flow, "s2") == 0
    assert len(open_flow["warnings"]) == 1
    assert "Second" in open_flow["warnings"][0]
    assert open_flow["nodes"][0].events[-1] == "stop"
    assert open_flow["activated"] == []
    assert open_flow["spawned"] == []


def test_open_choice_without_reply_tells_the_user(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path(open_flow, "s2") == 0
    assert len(open_flow["dialogs"]) == 1
    parent, title, text = open_flow["dialogs"][0]
    assert parent is None
    assert title == t("Open Path")
    assert "Second" in text


def test_open_choice_without_broker_warns_without_requesting(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s2", "")
    open_flow["registered"] = False
    assert run_open_path(open_flow, "s2") == 0
    assert open_flow["nodes"][0].events == ["start", ("wait_registered", 5), "stop"]
    assert len(open_flow["warnings"]) == 1
    assert len(open_flow["dialogs"]) == 1
    assert open_flow["activated"] == []


def test_running_and_closed_choice_spawns_its_viewer_without_restoring(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s1", "")
    assert run_open_path(open_flow, "s2") == 0
    assert open_flow["asked"][0][1] == {"s2"}
    assert open_flow["spawned"] == [("s1", request_for(open_flow))]
    assert open_flow["allowed"] == [1001]
    assert open_flow["restored"] == []
    assert open_flow["nodes"] == []


def test_not_running_marks_restore_ids_open_and_spawns_every_window(open_flow):
    open_flow["store"].set_restore_slot_ids(["s1", "s2"])
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path(open_flow) == 0
    slots, open_ids, kwargs = open_flow["asked"][0]
    assert open_ids == {"s1", "s2"}
    assert kwargs["allow_open"] is True
    assert open_flow["restored"] == ["s2"]
    assert open_flow["spawned"] == [("s2", request_for(open_flow))]
    assert open_flow["nodes"] == []


def test_not_running_waits_for_pending_installs_before_asking(open_flow):
    open_flow["store"].set_restore_slot_ids(["s1"])
    open_flow["answer"] = PickResult("s2", "")
    assert run_open_path(open_flow) == 0
    assert open_flow["events"] == ["install", "ask"]


def test_running_does_not_wait_for_installs(open_flow, lock_dir):
    open_flow["answer"] = PickResult("s1", "")
    assert run_open_path(open_flow, "s2") == 0
    assert open_flow["events"] == ["ask"]


def test_cancel_while_running_opens_nothing(open_flow, lock_dir):
    open_flow["store"].set_restore_slot_ids(["s1"])
    assert run_open_path(open_flow, "s2") == 0
    assert open_flow["restored"] == []
    assert open_flow["spawned"] == []
    assert open_flow["nodes"] == []
    assert len(open_flow["store"].list_slots()) == 2


def test_cancel_while_not_running_restores_the_previous_windows(open_flow):
    open_flow["store"].set_restore_slot_ids(["s1", "s2"])
    assert run_open_path(open_flow) == 0
    assert open_flow["restored"] == [None]
    assert open_flow["spawned"] == []
    assert open_flow["nodes"] == []
    assert len(open_flow["store"].list_slots()) == 2


def record_seeds(store, monkeypatch):
    seeds = []
    create = store.create_slot_from
    monkeypatch.setattr(store, "create_slot_from", lambda seed: seeds.append(seed) or create(seed))
    return seeds


def test_new_from_path_without_restore_ids_seeds_from_latest_slot(open_flow, monkeypatch):
    store = open_flow["store"]
    seeds = record_seeds(store, monkeypatch)
    latest = store.latest_slot_id()
    open_flow["answer"] = PickResult(None, "")
    run_open_path(open_flow)
    assert seeds == [latest]
    new_id, request = open_flow["spawned"][0]
    assert new_id not in ("s1", "s2")
    assert store.get_slot(new_id) is not None
    assert request == request_for(open_flow)
    assert open_flow["restored"] == [new_id]


def test_new_from_path_while_not_running_seeds_from_the_first_restored_window(open_flow, monkeypatch):
    store = open_flow["store"]
    store.set_restore_slot_ids(["s1"])
    assert store.latest_slot_id() == "s2"
    seeds = record_seeds(store, monkeypatch)
    open_flow["answer"] = PickResult(None, "")
    run_open_path(open_flow)
    assert seeds == ["s1"]


def test_new_from_path_while_running_seeds_from_latest_slot(open_flow, monkeypatch, lock_dir):
    store = open_flow["store"]
    store.set_restore_slot_ids(["s1"])
    seeds = record_seeds(store, monkeypatch)
    open_flow["answer"] = PickResult(None, "")
    run_open_path(open_flow, "s1")
    assert seeds == ["s2"]
    assert open_flow["restored"] == []


def test_single_database_is_used_without_choice(open_flow):
    open_flow["databases"] = ["a"]
    open_flow["answer"] = PickResult("s1", "")
    run_open_path(open_flow)
    assert open_flow["asked"][0][2] == {"allow_open": True, "databases": []}
    assert open_flow["spawned"] == [("s1", request_for(open_flow, "a"))]


def test_multiple_databases_offer_a_choice(open_flow):
    open_flow["databases"] = ["a", "b"]
    open_flow["answer"] = PickResult("s1", "b")
    run_open_path(open_flow)
    assert open_flow["asked"][0][2] == {"allow_open": True, "databases": ["a", "b"]}
    assert open_flow["spawned"] == [("s1", request_for(open_flow, "b"))]


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(workspace_launch.AppProcess, "new_main", lambda *args: calls.append(args) or f"proc{len(calls)}")
    return calls


def test_spawn_viewer_passes_the_file_and_database(spawned):
    assert workspace_launch.spawn_viewer("s1", workspace_launch.OpenRequest("C:/a b.png", "db")) == "proc1"
    assert spawned ==[("--viewer", "--slot", "s1", "--open-path", "C:/a b.png", "--open-database", "db")]


def test_spawn_viewer_leaves_out_an_empty_database(spawned):
    workspace_launch.spawn_viewer("s1", workspace_launch.OpenRequest("C:/a.png", ""))
    workspace_launch.spawn_viewer("s2")
    assert spawned == [("--viewer", "--slot", "s1", "--open-path", "C:/a.png"), ("--viewer", "--slot", "s2")]


@pytest.fixture
def hand_over(tmp_path, monkeypatch):
    store = store_with_slot(monkeypatch, tmp_path, "s1")
    flow = {"store": store, "lock": None, "claimed": [], "sent": []}

    def claim(slot_id):
        flow["claimed"].append(slot_id)
        return flow["lock"]

    monkeypatch.setattr(workspace_launch, "claim_workspace", claim)
    monkeypatch.setattr(workspace_launch, "send_open_request", lambda slot, request: flow["sent"].append((slot.slot_id, request)))
    return flow


def test_claim_or_hand_over_returns_the_claimed_lock(hand_over):
    hand_over["lock"] = "lock"
    request = workspace_launch.OpenRequest("C:/a.png", "")
    assert workspace_launch.claim_or_hand_over("s1", request) == "lock"
    assert hand_over["sent"] == []


def test_claim_or_hand_over_sends_the_file_to_the_window_that_took_the_workspace(hand_over):
    request = workspace_launch.OpenRequest("C:/a.png", "db")
    assert workspace_launch.claim_or_hand_over("s1", request) is None
    assert hand_over["claimed"] == ["s1"]
    assert hand_over["sent"] == [("s1", request)]


def test_claim_or_hand_over_without_a_file_sends_nothing(hand_over):
    assert workspace_launch.claim_or_hand_over("s1", None) is None
    assert workspace_launch.claim_or_hand_over("ghost", workspace_launch.OpenRequest("C:/a.png", "")) is None
    assert hand_over["sent"] == []


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

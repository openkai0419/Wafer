import pytest

from wafer.app.webui import instance
from wafer.app.webui.instance import WebUILock, activate_webui_window, claim_webui, replace_webui, restore_webui
from wafer.core.platform import window_lock
from wafer.core.store.workspace import WorkspaceStore


@pytest.fixture(autouse=True)
def lock_file(tmp_path, monkeypatch):
    monkeypatch.setattr(instance, "resolve_temp_path", lambda name: str(tmp_path / name))
    monkeypatch.setattr(window_lock, "sleep", lambda seconds: None)


@pytest.fixture
def activated(monkeypatch):
    calls = []
    monkeypatch.setattr(instance, "activate_window", calls.append)
    return calls


@pytest.fixture
def store(tmp_path, monkeypatch):
    store = WorkspaceStore(path=str(tmp_path / "workspace.json"))
    monkeypatch.setattr(WorkspaceStore, "_instance", store)
    return store


@pytest.fixture
def spawned(monkeypatch):
    calls = []
    monkeypatch.setattr(instance.AppProcess, "new_main", lambda *args, **kwargs: calls.append((args, kwargs)))
    return calls


def test_is_open_follows_the_lock():
    assert WebUILock.is_open() is False
    lock = WebUILock.acquire()
    try:
        assert WebUILock.is_open() is True
        assert WebUILock.acquire() is None
    finally:
        lock.release()
    assert WebUILock.is_open() is False


def test_claim_webui_takes_a_free_lock(activated):
    lock = claim_webui()
    try:
        assert lock is not None
        assert WebUILock.is_open() is True
        assert activated == []
    finally:
        lock.release()


def test_claim_webui_brings_the_running_window_forward(activated):
    held = WebUILock.acquire()
    held.set_window(77)
    try:
        assert claim_webui() is None
        assert activated == [77]
    finally:
        held.release()


def test_claim_webui_gives_up_when_the_owner_has_no_window(activated):
    held = WebUILock.acquire()
    try:
        assert claim_webui() is None
        assert activated == []
    finally:
        held.release()


def test_activate_webui_window_needs_an_owner(activated):
    assert activate_webui_window() is False
    assert activated == []


def test_restore_webui_spawns_without_clearing_the_record(store, spawned):
    store.set_restore_webui(True)
    restore_webui()
    assert spawned == [(("--webui", "--no-browser"), {})]
    assert store.get_restore_webui() is True


def test_restore_webui_does_nothing_when_not_recorded(store, spawned):
    restore_webui()
    assert spawned == []


def test_restore_webui_does_not_spawn_a_second_one(store, spawned):
    store.set_restore_webui(True)
    held = WebUILock.acquire()
    try:
        restore_webui()
        assert spawned == []
    finally:
        held.release()


def test_replace_webui_asks_the_new_process_to_take_over(spawned):
    replace_webui()
    assert spawned == [(("--webui", "--no-browser"), {"extra_env": {"WAFER_REPLACE_WEBUI": "1"}})]

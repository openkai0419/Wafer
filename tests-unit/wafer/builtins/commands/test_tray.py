from types import SimpleNamespace
from unittest.mock import MagicMock

from wafer.builtins.commands import tray as tray_commands


class _Ctx:
    def __init__(self, broker_viewers=0):
        self.tray = MagicMock()
        self.tray.show_state = False
        self.tray.broker.peer_counts.return_value = {"viewer": broker_viewers}

    def get_instance(self, name):
        return self.tray if name == "Tray" else None


def _patch_store(monkeypatch, restore_ids, open_ids=()):
    store = MagicMock()
    store.get_restore_slot_ids.return_value = restore_ids
    store.list_slots.return_value = [SimpleNamespace(slot_id=sid) for sid in ("s1", "s2")]
    monkeypatch.setattr(tray_commands, "WorkspaceStore", MagicMock(instance=staticmethod(lambda: store)))
    monkeypatch.setattr(tray_commands.WorkspaceLock, "open_slot_ids", staticmethod(lambda ids: set(ids) & set(open_ids)))


def _record(monkeypatch):
    calls = []
    monkeypatch.setattr(tray_commands.AppProcess, "new_main", lambda *args: calls.append(args))
    monkeypatch.setattr(tray_commands, "restore_webui", lambda: calls.append("webui"))
    return calls


def test_show_window_restores_viewers_and_the_webui_when_nothing_is_open(monkeypatch):
    calls = _record(monkeypatch)
    _patch_store(monkeypatch, ["s1"])
    tray_commands.show_window(_Ctx())
    assert calls == [("--viewer", "--slot", "s1"), "webui"]


def test_show_window_toggles_an_open_viewer(monkeypatch):
    calls = _record(monkeypatch)
    _patch_store(monkeypatch, ["s1"], open_ids=["s2"])
    ctx = _Ctx(broker_viewers=1)
    tray_commands.show_window(ctx)
    assert calls == []
    assert ctx.tray.show_state is True
    ctx.tray.broker.dispatch.assert_called_once()


def test_show_window_spawns_nothing_while_a_viewer_has_not_rejoined_a_restarted_broker(monkeypatch):
    calls = _record(monkeypatch)
    _patch_store(monkeypatch, [], open_ids=["s1"])
    tray_commands.show_window(_Ctx(broker_viewers=0))
    assert calls == []

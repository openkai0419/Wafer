from unittest.mock import MagicMock

from wafer.builtins.commands import tray as tray_commands


class _Ctx:
    def __init__(self, viewers):
        self.tray = MagicMock()
        self.tray.broker.peer_counts.return_value = {"viewer": viewers}

    def get_instance(self, name):
        return self.tray if name == "Tray" else None


def _patch_store(monkeypatch, restore_ids):
    store = MagicMock()
    store.get_restore_slot_ids.return_value = restore_ids
    monkeypatch.setattr(tray_commands, "WorkspaceStore", MagicMock(instance=staticmethod(lambda: store)))


def test_show_window_restores_viewers_and_the_webui_when_nothing_is_open(monkeypatch):
    calls = []
    _patch_store(monkeypatch, ["s1"])
    monkeypatch.setattr(tray_commands.AppProcess, "new_main", lambda *args: calls.append(args))
    monkeypatch.setattr(tray_commands, "restore_webui", lambda: calls.append("webui"))
    tray_commands.show_window(_Ctx(viewers=0))
    assert calls == [("--viewer", "--slot", "s1"), "webui"]


def test_show_window_leaves_the_webui_alone_while_a_viewer_is_open(monkeypatch):
    calls = []
    _patch_store(monkeypatch, ["s1"])
    monkeypatch.setattr(tray_commands.AppProcess, "new_main", lambda *args: calls.append(args))
    monkeypatch.setattr(tray_commands, "restore_webui", lambda: calls.append("webui"))
    tray_commands.show_window(_Ctx(viewers=1))
    assert calls == []

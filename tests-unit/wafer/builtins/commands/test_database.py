from types import SimpleNamespace

from wafer.builtins.commands import database as database_mod
from wafer.core.lang.manager import t


class _Combo:
    def __init__(self, names):
        self.names = list(names)

    def count(self):
        return len(self.names)

    def removeItem(self, name):
        self.names.remove(name)

    def currentText(self):
        return self.names[0]


def test_create_database_seeds_the_setting_db_then_starts_its_indexer(monkeypatch, tmp_path):
    from wafer.core.db.setting_db import SettingDB

    started = []
    monkeypatch.setattr(database_mod, "setting_db_path", lambda name: str(tmp_path / f"{name}.db"))
    monkeypatch.setattr("wafer.plugin.settings.PluginSettings.resolve_default_collectors", lambda self: ["image", "color"])
    monkeypatch.setattr(database_mod.AppProcess, "start_indexer", classmethod(lambda cls, name: started.append(name)))

    database_mod.create_database("new_db")

    assert sorted(SettingDB(str(tmp_path / "new_db.db")).get_enabled_collectors()) == ["color", "image"]
    assert started == ["new_db"]


def test_remove_database_delegates_deletion_to_indexer_over_ipc(monkeypatch):
    sent = []
    reloaded = []
    window = SimpleNamespace(
        database_name="old",
        database_combo=_Combo(["keep", "old"]),
        _node=SimpleNamespace(send_reliable=lambda *args, **kwargs: sent.append((args, kwargs))),
        reload_database=reloaded.append,
    )
    monkeypatch.setattr(database_mod.ConfirmDialog, "ask", lambda *a, **k: t.tr("Delete"))

    database_mod.remove_database(SimpleNamespace(get_instance=lambda name: window))

    assert sent == [(("db.delete", "old"), {"dst": "indexer", "db": "old"})]
    assert window.database_combo.names == ["keep"]
    assert reloaded == ["keep"]


def test_add_database_rejects_a_name_that_is_not_a_valid_filename(monkeypatch):
    created, warnings = [], []
    window = SimpleNamespace(reload_database=lambda name: None)
    monkeypatch.setattr(database_mod.InputDialog, "get_text", lambda *a, **k: "a?b")
    monkeypatch.setattr(database_mod, "list_setting_db_names", lambda: ["db"])
    monkeypatch.setattr(database_mod, "create_database", created.append)
    monkeypatch.setattr(database_mod.Notifier, "warning", warnings.append)

    database_mod.add_database(SimpleNamespace(get_instance=lambda name: window))

    assert created == []
    assert warnings == ["Invalid database name: invalid_chars"]

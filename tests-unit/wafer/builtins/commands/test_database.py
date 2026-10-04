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

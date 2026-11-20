from wafer.qt.commands.binding.key.editors import KeyBindingEditor
from wafer.qt.commands.binding.key.sequence import Key
from wafer.qt.commands.binding.key.store import KeyBindingStore
from wafer.qt.commands.binding.manager import BindingManager
from wafer.qt.commands.command.payload import CommandPayload


def test_ok_applies_through_the_binding_manager(qtbot, monkeypatch):
    store = KeyBindingStore.instance()
    old = store.get_all()
    applied = []
    manager = BindingManager.instance()
    monkeypatch.setattr(manager, "apply_registered", lambda: applied.append(store.get_all()))
    monkeypatch.setattr(KeyBindingEditor, "_save_store", lambda self, path: None)
    try:
        store.set_all({})
        editor = KeyBindingEditor([])
        qtbot.addWidget(editor)
        editor._draft.update(Key("SC30"), {"*": CommandPayload("mark.toggle")})
        editor._apply()
        assert len(applied) == 1
        assert Key("SC30") in applied[0]
    finally:
        store.set_all(old)

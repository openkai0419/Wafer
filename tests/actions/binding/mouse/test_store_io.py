from source.actions.binding.mouse.store import MouseBindingStore
from source.actions.binding.mouse.mouseeventmanager import MouseActionKey
from source.actions.command.payload import CommandPayload


def test_mouse_store_save_load_roundtrip(tmp_path):
    store = MouseBindingStore()
    k = MouseActionKey("LEFT", "SINGLE", (), ())
    data = {k: {"*": CommandPayload("viewer.next", {})}}
    store.set_all(data)
    p = tmp_path / "mouse.json"
    store.save_to_file(str(p))
    store.set_all({})
    assert store.get_all() == {}
    assert store.load_from_file(str(p))
    got = store.get_all()
    assert set(got.keys()) == {k}
    assert got[k]["*"].to_dict() == {"id": "viewer.next", "args": {}}

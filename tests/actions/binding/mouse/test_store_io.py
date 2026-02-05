from source.actions.binding.mouse.store import MouseBindingStore
from source.actions.binding.mouse.mouseeventmanager import MouseActionKey
from source.actions.command.payload import CommandPayload
from source.actions.binding.seed import get_seed_mouse_bindings, get_seed_key_bindings, set_seed_bindings


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

def test_mouse_store_diff_saves_deletions(tmp_path):
    prev_mouse = get_seed_mouse_bindings()
    prev_key = get_seed_key_bindings()
    try:
        k = MouseActionKey("LEFT", "SINGLE", (), ())
        seed = {k: {"*": CommandPayload("viewer.next", {})}}
        set_seed_bindings(mouse_bindings=seed, key_bindings=prev_key)
        store = MouseBindingStore()
        store.set_all({})
        p = tmp_path / "mouse_diff.json"
        store.save_to_file(str(p))
        store.set_all(seed)
        assert store.load_from_file(str(p))
        assert store.get_all() == {}
    finally:
        set_seed_bindings(mouse_bindings=prev_mouse, key_bindings=prev_key)

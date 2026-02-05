from source.actions.binding.key.store import KeyBindingStore
from source.actions.binding.key.sequence import Key
from source.actions.command.payload import CommandPayload
from source.actions.binding.seed import get_seed_mouse_bindings, get_seed_key_bindings, set_seed_bindings


def test_key_store_save_load_roundtrip(tmp_path):
    store = KeyBindingStore()
    data = {Key("Ctrl", "W"): {"*": CommandPayload("viewer.close", {})}}
    store.set_all(data)
    p = tmp_path / "keys.json"
    store.save_to_file(str(p))
    store.set_all({})
    assert store.get_all() == {}
    assert store.load_from_file(str(p))
    got = store.get_all()
    assert set(got.keys()) == set(data.keys())
    assert got[next(iter(data.keys()))]["*"].to_dict() == {"id": "viewer.close", "args": {}}

def test_key_store_diff_saves_deletions(tmp_path):
    prev_mouse = get_seed_mouse_bindings()
    prev_key = get_seed_key_bindings()
    try:
        seed = {Key("Ctrl", "W"): {"*": CommandPayload("viewer.close", {})}}
        set_seed_bindings(mouse_bindings=prev_mouse, key_bindings=seed)
        store = KeyBindingStore()
        store.set_all({})
        p = tmp_path / "keys_diff.json"
        store.save_to_file(str(p))
        store.set_all(seed)
        assert store.load_from_file(str(p))
        assert store.get_all() == {}
    finally:
        set_seed_bindings(mouse_bindings=prev_mouse, key_bindings=prev_key)

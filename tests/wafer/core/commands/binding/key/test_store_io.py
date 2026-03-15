import json

from wafer.core.commands.binding.key.store import KeyBindingStore
from wafer.core.commands.binding.key.sequence import Key
from wafer.core.commands.command.payload import CommandPayload
from wafer.core.commands.binding.presets import set_presets


def test_key_store_save_load_roundtrip(tmp_path):
    store = KeyBindingStore.instance()
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

def test_key_store_diff_saves_deletions(tmp_path, monkeypatch):
    seed_dir = tmp_path / "key_bindings"
    seed_dir.mkdir()
    k = Key("Ctrl", "W")
    seed_json = {"items": [{"key": k.to_dict(), "scopes": {"*": {"id": "viewer.close", "args": {}}}}]}
    (seed_dir / "test_preset.json").write_text(json.dumps(seed_json), encoding="utf-8")
    monkeypatch.setattr("wafer.core.commands.binding.presets.get_resource_path", lambda: tmp_path)
    set_presets(key="test_preset")
    try:
        store = KeyBindingStore.instance()
        store.set_all({})
        p = tmp_path / "keys_diff.json"
        store.save_to_file(str(p))
        store._data = store._seed_data()
        assert store.load_from_file(str(p))
        assert store.get_all() == {}
    finally:
        set_presets(key="standard")

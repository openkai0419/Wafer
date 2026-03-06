import json

from wayfer.core.actions.binding.mouse.store import MouseBindingStore
from wayfer.core.actions.binding.mouse.types import MouseActionKey
from wayfer.core.actions.command.payload import CommandPayload
from wayfer.core.actions.binding.presets import set_presets, get_mouse_preset, get_mouse_preset_path


def test_mouse_store_save_load_roundtrip(tmp_path):
    store = MouseBindingStore.instance()
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

def test_mouse_store_diff_saves_deletions(tmp_path, monkeypatch):
    seed_dir = tmp_path / "mouse_bindings"
    seed_dir.mkdir()
    k = MouseActionKey("LEFT", "SINGLE", (), ())
    seed_json = {"items": [{"key": k.to_dict(), "scopes": {"*": {"id": "viewer.next", "args": {}}}}]}
    (seed_dir / "test_preset.json").write_text(json.dumps(seed_json), encoding="utf-8")
    monkeypatch.setattr("wayfer.core.actions.binding.presets.get_resource_path", lambda: tmp_path)
    set_presets(mouse="test_preset")
    try:
        store = MouseBindingStore.instance()
        store.set_all({})
        p = tmp_path / "mouse_diff.json"
        store.save_to_file(str(p))
        store._data = store._seed_data()
        assert store.load_from_file(str(p))
        assert store.get_all() == {}
    finally:
        set_presets(mouse="standard")

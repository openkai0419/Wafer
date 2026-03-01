import pytest

from afterimages.core.actions.binding.key.store import KeyBindingStore


def test_keybindingstore_rejects_tuple_keys_in_specs():
    s = KeyBindingStore()
    with pytest.raises(TypeError):
        s.set_all({("H",): {"*": {"id": "x", "args": {}}}})

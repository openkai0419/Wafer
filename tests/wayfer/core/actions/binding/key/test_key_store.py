import pytest

from wayfer.core.actions.binding.key.store import KeyBindingStore


def test_keybindingstore_rejects_tuple_keys_in_specs():
    s = KeyBindingStore.instance()
    with pytest.raises(TypeError):
        s.set_all({("H",): {"*": {"id": "x", "args": {}}}})

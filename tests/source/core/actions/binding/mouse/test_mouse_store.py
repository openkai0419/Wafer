import pytest

from source.core.actions.binding.mouse.store import MouseBindingStore


def test_mousebindingstore_rejects_tuple_keys_in_specs():
    s = MouseBindingStore()
    with pytest.raises(TypeError):
        s.set_all({("RIGHT", "SINGLE", ()): {"*": {"id": "x", "args": {}}}})

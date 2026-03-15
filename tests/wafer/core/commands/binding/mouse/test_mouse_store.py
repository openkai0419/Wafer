import pytest

from wafer.core.commands.binding.mouse.store import MouseBindingStore


def test_mousebindingstore_rejects_tuple_keys_in_specs():
    s = MouseBindingStore.instance()
    with pytest.raises(TypeError):
        s.set_all({("RIGHT", "SINGLE", ()): {"*": {"id": "x", "args": {}}}})

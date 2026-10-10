from wafer.qt.commands.binding.key.sequence import KeySequence
from wafer.qt.commands.binding.key.store import KeyBindingStore
from wafer.qt.commands.binding.mouse.types import MouseActionKey
from wafer.qt.commands.binding.mouse.store import MouseBindingStore
from wafer.qt.commands.binding.presets import set_presets
from wafer.qt.commands.command.core import CommandRegistry


def test_preset_mouse_bindings_load():
    set_presets(mouse="standard")
    data = MouseBindingStore.instance()._seed_data()
    assert data
    assert all(isinstance(k, MouseActionKey) for k in data.keys())


def test_preset_key_bindings_load():
    set_presets(key="standard")
    data = KeyBindingStore.instance()._seed_data()
    assert data
    assert all(isinstance(k, KeySequence) for k in data.keys())


def test_preset_key_bindings_reference_registered_commands():
    set_presets(key="standard")
    data = KeyBindingStore.instance()._seed_data()
    registry = CommandRegistry.instance()

    validated_keys = [
        KeySequence(["Down"]),
        KeySequence(["Del"]),
        KeySequence(["Control", "A"]),
        KeySequence(["Up"]),
        KeySequence(["1"]),
        KeySequence(["Control", "X"]),
        KeySequence(["Control", "V"]),
        KeySequence(["Control", "C"]),
        KeySequence(["K"]),
        KeySequence(["Control", "N"]),
        KeySequence(["Space"]),
    ]
    missing = [data[key]["*"].id for key in validated_keys if registry.get_command(data[key]["*"].id) is None]
    assert missing == []

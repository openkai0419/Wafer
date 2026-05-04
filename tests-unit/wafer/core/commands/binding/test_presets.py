from wafer.core.commands.binding.key.sequence import KeySequence
from wafer.core.commands.binding.key.store import KeyBindingStore
from wafer.core.commands.binding.mouse.types import MouseActionKey, MouseButton, ClickType
from wafer.core.commands.binding.mouse.store import MouseBindingStore
from wafer.core.commands.binding.presets import set_presets
from wafer.core.commands.command.core import CommandRegistry
from wafer.core.commands.bridge import ActionKit


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


def test_preset_key_bindings_content():
    set_presets(key="standard")
    data = KeyBindingStore.instance()._seed_data()

    assert data[KeySequence(["Down"])]["*"].id == "fv.next_file"
    assert data[KeySequence(["Del"])]["*"].id == "file.delete"
    assert data[KeySequence(["Control", "A"])]["*"].id == "grid.select_all"
    assert data[KeySequence(["Up"])]["*"].id == "fv.prev_file"
    assert data[KeySequence(["1"])]["*"].id == "mark.toggle"
    assert data[KeySequence(["Control", "X"])]["*"].id == "file.cut"
    assert data[KeySequence(["Control", "V"])]["*"].id == "file.paste"
    assert data[KeySequence(["Control", "C"])]["*"].id == "file.copy"
    assert data[KeySequence(["K"])]["*"].id == "setting.keybind"
    assert data[KeySequence(["Control", "N"])]["*"].id == "file.new_folder"
    assert data[KeySequence(["M"])]["*"].id in {"mousebind", "setting.mousebind"}
    assert data[KeySequence(["Space"])]["*"].id == "panel.solo_current"


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


def test_preset_mouse_bindings_content():
    set_presets(mouse="standard")
    data = MouseBindingStore.instance()._seed_data()
    right_single = ActionKit.Mouse("RIGHT", "SINGLE")
    assert right_single in data
    assert data[right_single]["*"].id == "allmenu"

    wheel_up = ActionKit.Mouse("NONE", "WHEEL_UP")
    assert data[wheel_up]["ImageView"].id == "imgv.zoom_in"
    assert data[wheel_up]["GridView"].id == "grid.scroll_up"

    wheel_down = ActionKit.Mouse("NONE", "WHEEL_DOWN")
    assert data[wheel_down]["ImageView"].id == "imgv.zoom_out"

    left_single = ActionKit.Mouse("LEFT", "SINGLE")
    assert data[left_single]["ImageView"].id == "fv.navigate_file_by_mouse_position"
    assert data[left_single]["VideoView"].id == "fv.navigate_file_by_mouse_position"

    dbl = ActionKit.Mouse("LEFT", "DOUBLE")
    assert "ImageView" not in data[dbl]

    drag = ActionKit.Mouse("LEFT", "DRAG_START")
    assert data[drag]["ImageView"].id == "imgv.pan"


def test_kit_key_factory():
    k = ActionKit.Key("H")
    assert isinstance(k, KeySequence)
    assert k == KeySequence(["H"])


def test_kit_mouse_factory():
    m = ActionKit.Mouse("RIGHT", "SINGLE")
    assert isinstance(m, MouseActionKey)
    assert m.button == MouseButton.RIGHT
    assert m.click_type == ClickType.SINGLE
